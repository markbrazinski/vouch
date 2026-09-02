"""Production AWS adapters (P0-3, P0-5, P0-6).

Each adapter implements the same interface as its local counterpart, so the
architecture is identical whether it runs against DynamoDB/S3/Guardrails or the
local simulations. What differs is durability and enforcement:

  * `DynamoCapabilityStore` — capability issuance and consumption as a single
    DynamoDB `TransactWriteItems`. Consume, state-version check, target
    mutation and ledger append either all commit or none do. This is not "an
    in-memory lock that behaves like a transaction"; it is the transaction.

  * `S3EvidenceStore` — versioned S3 objects with SHA-256 content hashes,
    Object Lock where the bucket supports it, and the returned VersionId
    persisted into the DecisionRecord so exact bytes are re-fetchable.

  * `BedrockGuardrailDetector` — the real `ApplyGuardrail` prompt-attack call,
    recording guardrail id, version and outcome.

Honesty rules this module follows, per the commission:
  * nothing here claims to have run if it did not;
  * a missing/denied AWS resource raises a typed failure — it never degrades
    silently to a local simulation, because a silent downgrade would make an
    audit of "is this real" impossible.

ponytail: boto3 clients are created lazily and cached per adapter, not wrapped
in a connection-pool abstraction. botocore already pools.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

from .authority import (
    ACTION_TARGET_TYPES,
    CAPABILITY_TTL_SECONDS,
    LOT_TRANSITIONS,
    MUTATIONS,
    ORDER_TRANSITIONS,
    Action,
    CapabilityRecord,
    IssuerViolation,
    TargetType,
    freeze_parameters,
)
from .issuance import IssuanceAuthority
from .issuance import verify as verify_proof
from .state import corpus_item, corpus_pk
from .contracts import FailureCategory, GuardrailOutcome, ScanStatus, VouchFailure
from .corpus import Corpus
from .lifecycle import utcnow
from .reconcile import POLICY_VERSION


def _client(service: str, region: str | None = None):
    """A boto3 client under the Vouch profile, or a typed failure."""
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - boto3 is a declared dep
        raise VouchFailure(
            FailureCategory.PERSISTENCE_FAILURE, f"boto3 unavailable: {exc}"
        ) from exc

    from ..config import load

    config = load()
    session_kwargs: dict[str, Any] = {"region_name": region or config.region}
    profile = os.environ.get("AWS_PROFILE") or config.aws_profile
    if profile:
        session_kwargs["profile_name"] = profile
    return boto3.Session(**session_kwargs).client(service)


# ==========================================================================
# P0-5 — S3 evidence storage
# ==========================================================================


class S3EvidenceStore:
    """Versioned, hash-addressed evidence storage in S3.

    Object Lock (WORM) is a BUCKET property that must be enabled at creation. If
    the bucket has it, retention is applied per object; if it does not, this
    adapter records that fact rather than claiming WORM it cannot provide. See
    `lock_mode`, which the DecisionRecord and docs report verbatim.
    """

    kind = "AWS_S3"

    def __init__(
        self,
        bucket: str | None = None,
        *,
        prefix: str = "evidence",
        retain_days: int = 0,
        region: str | None = None,
    ) -> None:
        from ..config import load

        self.bucket = bucket or load().evidence_bucket
        if not self.bucket:
            raise VouchFailure(
                FailureCategory.PERSISTENCE_FAILURE,
                "no evidence bucket configured (VOUCH_EVIDENCE_BUCKET)",
            )
        self.prefix = prefix.strip("/")
        self.retain_days = retain_days
        self._region = region
        self._s3 = None
        #: Set on first write: "COMPLIANCE" | "GOVERNANCE" | "NONE" | "UNKNOWN".
        self.lock_mode = "UNKNOWN"

    @property
    def s3(self):
        if self._s3 is None:
            self._s3 = _client("s3", self._region)
        return self._s3

    def _key(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key

    def put_original(self, key: str, raw: bytes) -> tuple[str, str, str]:
        """Write the original. Returns (uri, sha256, version_id).

        The SHA-256 is computed locally AND handed to S3 as a checksum, so a
        corrupted upload is rejected by the service rather than silently stored.
        """
        digest = hashlib.sha256(raw).hexdigest()
        full_key = self._key(key)
        params: dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": full_key,
            "Body": raw,
            "ChecksumAlgorithm": "SHA256",
            "Metadata": {"sha256": digest, "received_at": utcnow()},
        }
        if self.retain_days > 0:
            params["ObjectLockMode"] = "COMPLIANCE"
            params["ObjectLockRetainUntilDate"] = datetime.now(timezone.utc) + timedelta(
                days=self.retain_days
            )

        try:
            response = self.s3.put_object(**params)
            self.lock_mode = "COMPLIANCE" if self.retain_days > 0 else "NONE"
        except Exception as exc:  # noqa: BLE001
            name = type(exc).__name__
            if self.retain_days > 0 and "InvalidRequest" in str(exc):
                # Bucket has no Object Lock configuration. Record the truth and
                # store without it rather than pretending WORM applied.
                params.pop("ObjectLockMode", None)
                params.pop("ObjectLockRetainUntilDate", None)
                response = self.s3.put_object(**params)
                self.lock_mode = "NONE"
            else:
                raise VouchFailure(
                    FailureCategory.PERSISTENCE_FAILURE, f"s3 put_object {name}: {exc}"
                ) from exc

        version_id = response.get("VersionId", "")
        if not version_id:
            # No VersionId means bucket versioning is off: originals are NOT
            # protected from overwrite. Report it; do not claim immutability.
            self.lock_mode = "NONE"
        return f"s3://{self.bucket}/{full_key}", digest, version_id

    def get_original(self, key: str, version_id: str = "") -> bytes:
        params: dict[str, Any] = {"Bucket": self.bucket, "Key": self._key(key)}
        if version_id:
            params["VersionId"] = version_id
        try:
            return self.s3.get_object(**params)["Body"].read()
        except Exception as exc:  # noqa: BLE001
            raise VouchFailure(
                FailureCategory.PERSISTENCE_FAILURE, f"s3 get_object: {exc}"
            ) from exc

    #: Upper bound on a view reference's life. A source link is for looking at
    #: one document now, not a durable handle: anything longer starts behaving
    #: like an unauthenticated copy of evidence that is supposed to be
    #: access-controlled.
    MAX_VIEW_TTL_SECONDS = 300

    def _signing_client(self):
        """An S3 client pinned to SigV4 for presigning.

        Without an explicit signature version botocore falls back to SigV2 for
        presigned GETs, which was observed live: the URL came back carrying
        `AWSAccessKeyId`, `Signature` and a full `x-amz-security-token` — the
        session credential itself in a query string — and silently ignored the
        expiry this method computes. SigV4 keeps the credential out of the URL
        and honours `ExpiresIn`.

        Only the presigning client is pinned; `self.s3` stays the shared client
        used for reads and writes.
        """
        if getattr(self, "_signer", None) is None:
            # An injected client (tests, or a caller that supplied its own) is
            # used as-is rather than replaced by a real one.
            if self._s3 is not None:
                self._signer = self._s3
                return self._signer
            try:
                from botocore.config import Config

                import boto3

                self._signer = boto3.client(
                    "s3",
                    region_name=self._region,
                    config=Config(signature_version="s3v4"),
                )
            except Exception:  # noqa: BLE001 — fall back rather than lose the viewer
                self._signer = self.s3
        return self._signer

    def presigned_get(
        self, key: str, version_id: str = "", expires_in: int = MAX_VIEW_TTL_SECONDS
    ) -> str:
        """A short-lived URL a browser can open, without holding credentials.

        The alternative was streaming bytes back through the runtime, which
        would mean evidence documents travelling through an agent invocation
        path and being copied into a second store. Signing keeps the original
        the only copy and keeps the runtime out of the data path.

        The caller never sees a credential; the signature is derived from the
        runtime role and expires on its own.
        """
        ttl = max(1, min(int(expires_in), self.MAX_VIEW_TTL_SECONDS))
        params: dict[str, Any] = {"Bucket": self.bucket, "Key": self._key(key)}
        signer = self._signing_client()
        if version_id:
            # Pin the exact object version the decision actually read. Without
            # it a viewer could be shown a later overwrite of the same key and
            # believe it was the evidence.
            params["VersionId"] = version_id
        try:
            return signer.generate_presigned_url(
                "get_object", Params=params, ExpiresIn=ttl
            )
        except Exception as exc:  # noqa: BLE001
            # Never include the exception's own text: a signing error can echo
            # back the parameters it was signing.
            raise VouchFailure(
                FailureCategory.PERSISTENCE_FAILURE,
                f"could not sign a view reference: {type(exc).__name__}",
            ) from exc


# ==========================================================================
# P0-6 — Bedrock Guardrails prompt-attack detection
# ==========================================================================


class BedrockGuardrailDetector:
    """The real Guardrails prompt-attack filter (contract D7 / S2).

    Detection, not the trust boundary. The structural controls (supplier text
    never in instruction position, extraction model has zero authority,
    authority sourced only internally, deterministic recompute before mutation)
    hold whether or not this returns True — which is exactly what
    `test_injection_is_inert_even_when_detection_fails` proves.
    """

    def __init__(
        self,
        guardrail_id: str | None = None,
        guardrail_version: str = "DRAFT",
        *,
        region: str | None = None,
    ) -> None:
        from ..config import env_var

        self.guardrail_id = guardrail_id or env_var("GUARDRAIL_ID") or ""
        self.guardrail_version = guardrail_version
        self.__name__ = f"bedrock-guardrails:{self.guardrail_id}:{guardrail_version}"
        self._region = region
        self._runtime = None

    @property
    def runtime(self):
        if self._runtime is None:
            self._runtime = _client("bedrock-runtime", self._region)
        return self._runtime

    def __call__(self, text: str) -> tuple[bool, str]:
        """Returns (detected, detail). Raises on API failure.

        Raising matters: `inspect` turns an exception into GuardrailOutcome
        ERROR and fails closed. A guardrail that could not run must never be
        recorded as a guardrail that found nothing.
        """
        if not self.guardrail_id:
            raise VouchFailure(
                FailureCategory.TOOL_FAILURE,
                "no guardrail configured (VOUCH_GUARDRAIL_ID)",
            )
        response = self.runtime.apply_guardrail(
            guardrailIdentifier=self.guardrail_id,
            guardrailVersion=self.guardrail_version,
            source="INPUT",
            content=[{"text": {"text": text, "qualifiers": ["guard_content"]}}],
        )
        action = response.get("action", "NONE")
        assessments = response.get("assessments", [])
        detected = action == "GUARDRAIL_INTERVENED"
        detail = ""
        if detected:
            # The filters that actually fired live under
            # assessments[].contentPolicy.filters, each a dict with a `type`.
            # The previous reading walked invocationMetrics.guardrailCoverage,
            # whose entries are STRINGS — so this raised AttributeError the
            # first time a guardrail genuinely intervened, which no test could
            # catch while no guardrail was provisioned.
            kinds = sorted(
                {
                    filt.get("type", "")
                    for assessment in assessments
                    for policy in ("contentPolicy", "topicPolicy", "wordPolicy")
                    for filt in _policy_findings(assessment.get(policy, {}))
                    if isinstance(filt, dict) and filt.get("type")
                }
            )
            detail = f"guardrail intervened: {action}" + (f" {kinds}" if kinds else "")
        return detected, detail


def _policy_findings(policy: dict) -> list:
    """The findings a guardrail policy block reports, whatever it calls them.

    Content policies list `filters`, topic policies `topics`, word policies
    `customWords` and `managedWordLists`. Returning them uniformly keeps the
    caller from having to know which shape it got.
    """
    return [
        finding
        for key in ("filters", "topics", "customWords", "managedWordLists")
        for finding in policy.get(key, []) or []
    ]


class ClamAVScanner:
    """Malware scanning via a clamd daemon (P0-7).

    Present so the security field can be truthfully PASSED/FLAGGED where a
    scanner genuinely runs. With no daemon reachable it raises, and `inspect`
    records FAILED — never a fabricated pass.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 3310) -> None:
        self.host = host
        self.port = port

    def __call__(self, raw: bytes) -> tuple[ScanStatus, str]:
        import socket

        try:
            with socket.create_connection((self.host, self.port), timeout=5) as sock:
                sock.sendall(b"zINSTREAM\x00")
                sock.sendall(len(raw).to_bytes(4, "big") + raw + b"\x00\x00\x00\x00")
                reply = sock.recv(4096).decode("utf-8", errors="replace")
        except OSError as exc:
            return ScanStatus.FAILED, f"clamd unreachable: {exc}"

        if "OK" in reply and "FOUND" not in reply:
            return ScanStatus.PASSED, reply.strip()
        if "FOUND" in reply:
            return ScanStatus.FLAGGED, reply.strip()
        return ScanStatus.FAILED, reply.strip()


# ==========================================================================
# P0-3 — transactional capability consumption
# ==========================================================================

#: Which status each lot action writes. The DynamoDB transaction expresses the
#: mutation as a conditional update, so the closed dispatch table (P0-2) is
#: mirrored here as data rather than code.
_LOT_STATUS = {
    Action.RELEASE_LOT: "RELEASED",
    Action.QUARANTINE_LOT: "QUARANTINED",
    Action.CREATE_QA_REVIEW: "PENDING_QA",
}

#: Which lot statuses each action may legally transition FROM (audit-2 F6).
#: Derived from the same LOT_TRANSITIONS table the local store enforces, so
#: the two paths cannot drift.
_LEGAL_SOURCE_STATES: dict[Action, frozenset[str]] = {
    action: frozenset(
        source for source, targets in LOT_TRANSITIONS.items() if status in targets
    )
    for action, status in _LOT_STATUS.items()
}
#: A lot already PENDING_QA may receive another QA review without transitioning.
_LEGAL_SOURCE_STATES[Action.CREATE_QA_REVIEW] = frozenset(
    _LEGAL_SOURCE_STATES[Action.CREATE_QA_REVIEW] | {"PENDING_QA"}
)
_LEGAL_SOURCE_STATES[Action.HOLD_PRODUCTION_ORDER] = frozenset(
    source for source, targets in ORDER_TRANSITIONS.items() if "BLOCKED" in targets
)


def corpus_key(kind: str, key: str) -> dict:
    """The DynamoDB key of one corpus object. One representation, shared."""
    return {"pk": {"S": corpus_pk(kind)}, "sk": {"S": key}}


def _in_list(values: set[str], prefix: str) -> tuple[str, dict]:
    """An `IN (...)` fragment plus its expression values, sorted for stability."""
    ordered = sorted(values)
    names = [f":{prefix}{i}" for i in range(len(ordered))]
    return (
        "(" + ", ".join(names) + ")",
        {name: {"S": value} for name, value in zip(names, ordered)},
    )


class DynamoCapabilityStore:
    """Capability records in DynamoDB with atomic conditional consumption.

    Table layout (single-table, pk/sk — matches the provisioned table):

        CAP#<capability_id>    / META          capability row (+ issuer proof)
        CORPUS#lot             / <lot_id>      the lot: document + live status,
                                               state_version
        CORPUS#inventory       / <lot_id>      usable flag + quantity
        CORPUS#production_order/ <order_id>    order: status, planned_slot,
                                               state_version
        CORPUS#qa_review       / QA-<record>   QA review created by escalation
        SLOT#<resource>#<slot> / RESERVATION   exclusive schedule-slot holder
        LEDGER#<record_id>     / SEQ#<n>       append-only authority ledger

    Note that the mutation targets are the SAME `CORPUS#` items `DynamoCorpus`
    reads (audit-2 F5): there is one authoritative representation of a lot, not
    a corpus copy and a separate authority copy that could disagree. The fields
    the transaction conditions on and sets are top-level attributes, because a
    `ConditionExpression` cannot reach inside a JSON document.

    ## The trust boundary (audit-2 F2)

    The audit's finding was that ANY code under the runtime role could `PutItem`
    a syntactically correct `CAP#` row and have `consume()` honour it, because
    consume read the row's own fields and validated nothing an attacker could
    not also write.

    The correction has two independent halves, and the code is honest about
    which one is enforced where:

    1. **Cryptographic (enforced by this code, unconditionally).** Every
       capability row carries `issuer_proof`, an HMAC over the complete binding
       produced by the `issuance` module's private key. `consume()` recomputes
       and verifies that proof BEFORE building any transaction. A forged row —
       correct target, correct action, correct version, `used=false`,
       `issuer_identity="vouch.policy-engine"` — has no valid proof and is
       refused. Tampering with any bound field, including the signed action
       parameters, invalidates the proof. This holds even when the attacker has
       full `PutItem` on the table, which is precisely the audited condition.

    2. **IAM (enforced by deployment, verified by a static policy test).** The
       runtime policy denies `dynamodb:PutItem`/`UpdateItem`/`DeleteItem` on
       `CAP#*` items to the agent/tool execution identity via a
       `dynamodb:LeadingKeys` condition, so decision-agent code cannot write a
       capability row at all. See `iam/` for the policy documents and
       `test_iam_policy.py` for the test that asserts them.

    Half 1 is the load-bearing one: it does not depend on the deployment being
    correct. Half 2 is defence in depth. The key is process-local to whichever
    process runs the Policy Engine; where actor and Policy Engine share one
    runtime, the honest statement is that agent code cannot *reach* the signer
    (no exported minting path) but is not memory-isolated from it. That
    limitation is documented rather than papered over.

    ## The transaction (audit-2 F6)

    Consumption is ONE `TransactWriteItems` whose contents are derived from the
    STORED, AUTHENTICATED capability and contain EVERY authoritative item the
    action changes:

      * consume the capability   — exists, unused, unexpired, binding matches
      * mutate the target        — state_version matches AND source state legal
      * update inventory         — release/quarantine flip usability
      * reserve the slot         — resequence takes the slot exclusively
      * create the QA review     — escalation writes its review item
      * append the ledger        — complete before/after facts, idempotent

    All items commit together or none do. `TransactionCanceledException`
    carries per-item reasons, mapped back to the specific refusal.
    """

    kind = "AWS_DYNAMODB"

    def __init__(self, table: str | None = None, *, region: str | None = None) -> None:
        from ..config import load

        self.table = table or load().state_table
        if not self.table:
            raise VouchFailure(
                FailureCategory.PERSISTENCE_FAILURE,
                "no state table configured (VOUCH_STATE_TABLE)",
            )
        self._region = region
        self._ddb = None

    @property
    def ddb(self):
        if self._ddb is None:
            self._ddb = _client("dynamodb", self._region)
        return self._ddb

    # -- issuance (audit-2 F1/F2) ------------------------------------------
    # There is deliberately NO `_mint_issuer` here, under any name. This class
    # holds no key material; it can verify a proof and cannot create one.

    def issue(
        self,
        issuer: IssuanceAuthority,
        *,
        decision_record_id: str,
        target_type: TargetType,
        target_id: str,
        action: Action,
        observed_state_version: int,
        parameters: dict | None = None,
        ttl_seconds: int = CAPABILITY_TTL_SECONDS,
    ) -> CapabilityRecord:
        """Write the capability row, signed by the Policy Engine's authority.

        The signature is verified before the row is written, so an
        unauthorized caller produces ZERO rows rather than a row that would be
        rejected later.
        """
        if not isinstance(issuer, IssuanceAuthority):
            identity = getattr(issuer, "identity", type(issuer).__name__)
            raise IssuerViolation(
                f"{identity!r} is not authorized to issue capabilities"
            )

        capability_id = f"CAP-{uuid.uuid4().hex[:16]}"

        # A lot transition that moves inventory must also pin the inventory
        # row's OWN version, because the two counters do not move in lockstep:
        # an abstention takes the lot to PENDING_QA and leaves inventory alone.
        # Binding it here — signed, at authorization time — keeps the race
        # detection exact (a concurrent inventory write still invalidates this
        # capability) without inheriting the lot's unrelated version drift.
        if target_type is TargetType.LOT and action in (
            Action.RELEASE_LOT,
            Action.QUARANTINE_LOT,
        ):
            parameters = dict(parameters or {})
            parameters.setdefault(
                "observed_inventory_version",
                str(int((self.get_inventory(target_id) or {}).get("state_version", 1))),
            )

        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        ).isoformat()
        skeleton = CapabilityRecord(
            capability_id=capability_id,
            decision_record_id=decision_record_id,
            target_type=target_type,
            target_id=target_id,
            action=action,
            observed_state_version=observed_state_version,
            policy_version=POLICY_VERSION,
            expires_at=expires_at,
            nonce=uuid.uuid4().hex,
            issuer_proof="",
            issuer_identity=issuer.identity,
            parameters=freeze_parameters(parameters),
        )
        record = replace(skeleton, issuer_proof=issuer.sign(skeleton.binding()))
        if not verify_proof(record.binding(), record.issuer_proof):
            raise IssuerViolation(
                f"{issuer.identity!r} produced an invalid issuer proof; "
                "refusing to write a capability row"
            )

        try:
            self.ddb.put_item(
                TableName=self.table,
                Item={
                    "pk": {"S": f"CAP#{capability_id}"},
                    "sk": {"S": "META"},
                    "capability_id": {"S": capability_id},
                    "decision_record_id": {"S": decision_record_id},
                    "target_type": {"S": target_type.value},
                    "target_id": {"S": target_id},
                    "action": {"S": action.value},
                    "observed_state_version": {"N": str(observed_state_version)},
                    "policy_version": {"S": POLICY_VERSION},
                    "issued_at": {"S": utcnow()},
                    "expires_at": {"S": expires_at},
                    "nonce": {"S": record.nonce},
                    "issuer_identity": {"S": issuer.identity},
                    # F7: the signed, immutable action parameters travel WITH
                    # the row. Consumption reads the slot/readiness from here.
                    "parameters": {"S": json.dumps(dict(record.parameters), sort_keys=True)},
                    "issuer_proof": {"S": record.issuer_proof},
                    "used": {"BOOL": False},
                    # TTL attribute so consumed/expired rows self-clean.
                    "ttl": {"N": str(int(datetime.now(timezone.utc).timestamp()) + 86400)},
                },
                ConditionExpression="attribute_not_exists(pk)",
            )
        except IssuerViolation:
            raise
        except Exception as exc:  # noqa: BLE001
            raise VouchFailure(
                FailureCategory.PERSISTENCE_FAILURE, f"capability put failed: {exc}"
            ) from exc
        return record

    def get(self, capability_id: str) -> dict | None:
        response = self.ddb.get_item(
            TableName=self.table,
            Key={"pk": {"S": f"CAP#{capability_id}"}, "sk": {"S": "META"}},
        )
        return response.get("Item")

    @staticmethod
    def _record_from_row(row: dict) -> CapabilityRecord:
        """Rebuild the signed record exactly as issued, for verification."""
        raw_params = row.get("parameters", {}).get("S", "{}")
        try:
            parameters = json.loads(raw_params) if raw_params else {}
        except json.JSONDecodeError:
            parameters = {}
        return CapabilityRecord(
            capability_id=row["capability_id"]["S"],
            decision_record_id=row["decision_record_id"]["S"],
            target_type=TargetType(row["target_type"]["S"]),
            target_id=row["target_id"]["S"],
            action=Action(row["action"]["S"]),
            observed_state_version=int(row["observed_state_version"]["N"]),
            policy_version=row.get("policy_version", {}).get("S", ""),
            expires_at=row["expires_at"]["S"],
            nonce=row.get("nonce", {}).get("S", ""),
            issuer_proof=row.get("issuer_proof", {}).get("S", ""),
            issuer_identity=row.get("issuer_identity", {}).get("S", ""),
            parameters=freeze_parameters(parameters),
        )

    # -- consumption (P0-3, audit-2 F2/F6/F7) ------------------------------
    def consume(
        self,
        capability_id: str,
        corpus: Corpus | None = None,
        *,
        params: dict | None = None,
    ) -> dict:
        """Atomically authenticate, validate, consume, mutate and ledger.

        `corpus` is accepted for interface symmetry with the local store but is
        NOT the source of truth here — DynamoDB is. `params` is accepted for
        the same reason and is DISCARDED: every parameter that matters is read
        from the capability's signed binding (F7).
        """
        row = self.get(capability_id)
        if row is None:
            raise VouchFailure(
                FailureCategory.POLICY_REFUSAL,
                "no Policy-Engine-issued capability for this id",
            )

        # F2. Authenticate the row BEFORE trusting a single field on it. A
        # forged PutItem with syntactically perfect contents dies here.
        try:
            capability = self._record_from_row(row)
        except (KeyError, ValueError) as exc:
            raise VouchFailure(
                FailureCategory.POLICY_REFUSAL,
                f"capability row is malformed: {exc}",
            ) from exc
        if not verify_proof(capability.binding(), capability.issuer_proof):
            raise VouchFailure(
                FailureCategory.POLICY_REFUSAL,
                "capability failed issuer authentication; not issued by the Policy Engine",
            )

        action = capability.action
        target_type = capability.target_type
        target_id = capability.target_id
        record_id = capability.decision_record_id
        bound_version = capability.observed_state_version
        bound = capability.params
        now = datetime.now(timezone.utc).isoformat()

        if action not in MUTATIONS:
            raise VouchFailure(
                FailureCategory.POLICY_REFUSAL,
                f"no mutation is bound to {action.value}; refusing",
            )
        # F6: action/target-type compatibility, enforced independently.
        if action not in ACTION_TARGET_TYPES.get(target_type, frozenset()):
            raise VouchFailure(
                FailureCategory.POLICY_REFUSAL,
                f"{action.value} is not a {target_type.value} action",
            )

        plan = self._plan(capability, bound, now)

        try:
            self.ddb.transact_write_items(TransactItems=plan["items"])
        except Exception as exc:  # noqa: BLE001
            raise self._explain(
                exc, capability_id, target_id, bound_version, plan["labels"]
            ) from exc

        return {
            "sequence": plan["sequence"],
            "capability_id": capability_id,
            "decision_record_id": record_id,
            "issuer_identity": capability.issuer_identity,
            "action": action.value,
            "target_type": target_type.value,
            "target_id": target_id,
            "parameters": bound,
            "before_version": bound_version,
            "after_version": bound_version + 1,
            "before_state": plan["before_state"],
            "after_state": plan["after_state"],
            "result": plan["result"],
            "inventory_delta": plan["inventory_delta"],
            "inventory_before": plan["inventory_before"],
            "inventory_after": plan["inventory_after"],
            "at": now,
        }

    # -- transactional plans (audit-2 F6) ----------------------------------
    def _plan(self, capability: CapabilityRecord, bound: dict, now: str) -> dict:
        """Build the COMPLETE transaction for one authenticated capability.

        Derived only from the signed capability, never from caller input. Every
        authoritative item the action changes is in the plan, each with the
        condition that makes the change safe. Deny by default: an action with
        no plan raises rather than falling through to a partial write.
        """
        action = capability.action
        target_id = capability.target_id
        record_id = capability.decision_record_id
        bound_version = capability.observed_state_version
        new_version = bound_version + 1
        sequence = f"{record_id}#{capability.capability_id}"

        items: list[dict] = [self._consume_item(capability, now)]
        labels = ["capability"]
        before_state: dict = {}
        after_state: dict = {}
        inventory_delta = 0.0
        inventory_before: dict = {}
        inventory_after: dict = {}
        result = ""

        if capability.target_type is TargetType.LOT:
            status = _LOT_STATUS[action]
            legal = _LEGAL_SOURCE_STATES[action]
            source_fragment, source_values = _in_list(legal, "src")
            items.append(
                {
                    "Update": {
                        "TableName": self.table,
                        "Key": corpus_key("lot", target_id),
                        "UpdateExpression": "SET #s = :status, state_version = :new",
                        # F6: version binding AND legal source-state transition,
                        # both as conditions inside the same transaction.
                        "ConditionExpression": (
                            f"state_version = :bound AND #s IN {source_fragment}"
                        ),
                        "ExpressionAttributeNames": {"#s": "status"},
                        "ExpressionAttributeValues": {
                            ":status": {"S": status},
                            ":new": {"N": str(new_version)},
                            ":bound": {"N": str(bound_version)},
                            **source_values,
                        },
                    }
                }
            )
            labels.append("lot_state")
            before_state = {"kind": "lot", "state_version": bound_version}
            after_state = {"kind": "lot", "status": status, "state_version": new_version}
            result = f"lot {target_id} {status}"

            if action in (Action.RELEASE_LOT, Action.QUARANTINE_LOT):
                # F6: inventory is part of the SAME transaction. A released lot
                # whose inventory did not become usable is a partial mutation,
                # and a partial mutation is exactly what atomicity must exclude.
                usable = action is Action.RELEASE_LOT

                # The inventory row carries its OWN version, and the condition
                # is written against that rather than against the lot's.
                #
                # Conditioning inventory on the lot's bound version assumed the
                # two counters move in lockstep. They do not: any lot
                # transition that leaves inventory alone — PENDING_QA on an
                # abstention is the ordinary case — advances the lot and not
                # the inventory row, after which every later release of that
                # lot is refused as "inventory moved" when nothing moved at
                # all. That is Hero B.
                #
                # Replay protection is unchanged, and is in fact now exact: a
                # replayed consume still finds the inventory row at a version
                # its condition no longer matches, because THIS transaction
                # advanced it.
                inventory_row = self.get_inventory(target_id) or {}
                # The version this capability was AUTHORIZED against. Falls
                # back to the lot's bound version only for capabilities issued
                # before this field existed.
                inventory_version = int(
                    bound.get("observed_inventory_version", bound_version)
                )
                items.append(
                    {
                        "Update": {
                            "TableName": self.table,
                            "Key": corpus_key("inventory", target_id),
                            "UpdateExpression": (
                                "SET usable = :usable, state_version = :invnew"
                            ),
                            "ConditionExpression": (
                                "attribute_exists(sk) AND state_version = :invbound"
                            ),
                            "ExpressionAttributeValues": {
                                ":usable": {"BOOL": usable},
                                ":invnew": {"N": str(inventory_version + 1)},
                                ":invbound": {"N": str(inventory_version)},
                            },
                        }
                    }
                )
                labels.append("inventory")
                inventory_delta = float(bound.get("quantity", 0.0) or 0.0)
                if not usable:
                    inventory_delta = -inventory_delta
                after_state["inventory_usable"] = usable

                # Parity with the local backend: the record must show that the
                # inventory position was EVALUATED, so a zero-movement outcome
                # (quarantining a lot that was never usable) is evidenced
                # rather than indistinguishable from a step that never ran.
                was_usable = bool(inventory_row.get("usable", False))
                quantity = float(
                    inventory_row.get("quantity", bound.get("quantity", 0.0) or 0.0)
                )
                inventory_before = {"usable": was_usable, "quantity": quantity}
                inventory_after = {"usable": usable, "quantity": quantity}
                if was_usable == usable:
                    # Already in the target state: the transition moves nothing.
                    inventory_delta = 0.0

            elif action is Action.CREATE_QA_REVIEW:
                # F6: the QA action must actually create the QA record.
                review_id = f"QA-{record_id}"
                items.append(
                    {
                        "Put": {
                            "TableName": self.table,
                            "Item": {
                                **corpus_key("qa_review", review_id),
                                "kind": {"S": "qa_review"},
                                "document": {
                                    "S": json.dumps(
                                        {
                                            "review_id": review_id,
                                            "decision_record_id": record_id,
                                            "lot_id": target_id,
                                            "status": "OPEN",
                                            "created_at": now,
                                        },
                                        sort_keys=True,
                                    )
                                },
                            },
                            "ConditionExpression": "attribute_not_exists(sk)",
                        }
                    }
                )
                labels.append("qa_review")
                after_state["qa_review_id"] = review_id
                result = f"QA review {review_id} created"

        elif action is Action.RESEQUENCE_PRODUCTION_ORDER:
            # F7: the slot comes from the SIGNED binding, never from a caller.
            target_slot = bound.get("target_slot", "")
            from_slot = bound.get("from_slot", "")
            resource = bound.get("resource", "")
            if not target_slot:
                raise VouchFailure(
                    FailureCategory.POLICY_REFUSAL,
                    "resequence capability carries no bound target_slot",
                )
            order_condition = "state_version = :bound"
            order_values: dict = {
                ":slot": {"S": target_slot},
                ":new": {"N": str(new_version)},
                ":bound": {"N": str(bound_version)},
            }
            if from_slot:
                # F7: the slot the order moves FROM is bound too.
                order_condition += " AND planned_slot = :from"
                order_values[":from"] = {"S": from_slot}
            items.append(
                {
                    "Update": {
                        "TableName": self.table,
                        "Key": corpus_key("production_order", target_id),
                        "UpdateExpression": "SET planned_slot = :slot, state_version = :new",
                        "ConditionExpression": order_condition,
                        "ExpressionAttributeValues": order_values,
                    }
                }
            )
            labels.append("order_state")
            # F6: the slot is RESERVED atomically. Checking availability with a
            # read and then writing is the TOCTOU the whole design exists to
            # remove; an exclusive reservation item makes the check part of the
            # transaction itself.
            items.append(
                {
                    "Put": {
                        "TableName": self.table,
                        "Item": {
                            "pk": {"S": f"SLOT#{resource}#{target_slot}"},
                            "sk": {"S": "RESERVATION"},
                            "order_id": {"S": target_id},
                            "decision_record_id": {"S": record_id},
                            "reserved_at": {"S": now},
                        },
                        "ConditionExpression": (
                            "attribute_not_exists(pk) OR order_id = :order"
                        ),
                        "ExpressionAttributeValues": {":order": {"S": target_id}},
                    }
                }
            )
            labels.append("slot_reservation")
            if from_slot and resource:
                # Release the slot the order vacated, but only if this order
                # actually holds it.
                items.append(
                    {
                        "Delete": {
                            "TableName": self.table,
                            "Key": {
                                "pk": {"S": f"SLOT#{resource}#{from_slot}"},
                                "sk": {"S": "RESERVATION"},
                            },
                            "ConditionExpression": (
                                "attribute_not_exists(pk) OR order_id = :order"
                            ),
                            "ExpressionAttributeValues": {":order": {"S": target_id}},
                        }
                    }
                )
                labels.append("slot_release")
            before_state = {
                "kind": "production_order",
                "planned_slot": from_slot,
                "state_version": bound_version,
            }
            after_state = {
                "kind": "production_order",
                "planned_slot": target_slot,
                "state_version": new_version,
            }
            result = f"order {target_id} resequenced from {from_slot} to {target_slot}"

        else:
            # HOLD_PRODUCTION_ORDER / SET_ORDER_READINESS
            if action is Action.HOLD_PRODUCTION_ORDER:
                status = "BLOCKED"
                legal = _LEGAL_SOURCE_STATES[Action.HOLD_PRODUCTION_ORDER]
            else:
                status = bound.get("readiness", "")
                if status not in ORDER_TRANSITIONS:
                    raise VouchFailure(
                        FailureCategory.POLICY_REFUSAL,
                        f"{status!r} is not a readiness state",
                    )
                legal = frozenset(
                    source
                    for source, targets in ORDER_TRANSITIONS.items()
                    if status in targets
                )
            if not legal:
                raise VouchFailure(
                    FailureCategory.POLICY_REFUSAL,
                    f"no legal source state transitions to {status}",
                )
            source_fragment, source_values = _in_list(legal, "src")
            items.append(
                {
                    "Update": {
                        "TableName": self.table,
                        "Key": corpus_key("production_order", target_id),
                        "UpdateExpression": "SET #s = :status, state_version = :new",
                        "ConditionExpression": (
                            f"state_version = :bound AND #s IN {source_fragment}"
                        ),
                        "ExpressionAttributeNames": {"#s": "status"},
                        "ExpressionAttributeValues": {
                            ":status": {"S": status},
                            ":new": {"N": str(new_version)},
                            ":bound": {"N": str(bound_version)},
                            **source_values,
                        },
                    }
                }
            )
            labels.append("order_state")
            before_state = {"kind": "production_order", "state_version": bound_version}
            after_state = {
                "kind": "production_order",
                "status": status,
                "state_version": new_version,
            }
            result = f"order {target_id} -> {status}"

        # F6: the ledger carries the complete causal and factual record, and is
        # idempotent by capability so a replay cannot append twice.
        items.append(
            {
                "Put": {
                    "TableName": self.table,
                    "Item": {
                        "pk": {"S": f"LEDGER#{record_id}"},
                        "sk": {"S": f"SEQ#{sequence}"},
                        "capability_id": {"S": capability.capability_id},
                        "decision_record_id": {"S": record_id},
                        "issuer_identity": {"S": capability.issuer_identity},
                        "action": {"S": action.value},
                        "target_type": {"S": capability.target_type.value},
                        "target_id": {"S": target_id},
                        "parameters": {"S": json.dumps(bound, sort_keys=True)},
                        "before_version": {"N": str(bound_version)},
                        "after_version": {"N": str(new_version)},
                        "before_state": {"S": json.dumps(before_state, sort_keys=True)},
                        "after_state": {"S": json.dumps(after_state, sort_keys=True)},
                        "inventory_delta": {"N": str(inventory_delta)},
                        "result": {"S": result},
                        "at": {"S": now},
                    },
                    "ConditionExpression": "attribute_not_exists(pk)",
                }
            }
        )
        labels.append("ledger")

        return {
            "items": items,
            "labels": labels,
            "sequence": sequence,
            "before_state": before_state,
            "after_state": after_state,
            "inventory_delta": inventory_delta,
            "inventory_before": inventory_before,
            "inventory_after": inventory_after,
            "result": result,
        }

    def _consume_item(self, capability: CapabilityRecord, now: str) -> dict:
        """The capability-consumption item: exists, unused, unexpired, bound."""
        return {
            "Update": {
                "TableName": self.table,
                "Key": {
                    "pk": {"S": f"CAP#{capability.capability_id}"},
                    "sk": {"S": "META"},
                },
                "UpdateExpression": "SET used = :true, consumed_at = :now",
                "ConditionExpression": (
                    "attribute_exists(sk) AND used = :false "
                    "AND expires_at > :now "
                    "AND target_id = :target AND #a = :action "
                    "AND decision_record_id = :record "
                    "AND observed_state_version = :bound "
                    "AND issuer_proof = :proof"
                ),
                "ExpressionAttributeNames": {"#a": "action"},
                "ExpressionAttributeValues": {
                    ":true": {"BOOL": True},
                    ":false": {"BOOL": False},
                    ":now": {"S": now},
                    ":target": {"S": capability.target_id},
                    ":action": {"S": capability.action.value},
                    ":record": {"S": capability.decision_record_id},
                    ":bound": {"N": str(capability.observed_state_version)},
                    # The proof verified in-process is also asserted in the
                    # transaction, so a row swapped between read and write is
                    # caught by the conditional itself.
                    ":proof": {"S": capability.issuer_proof},
                },
            }
        }

    @staticmethod
    def _explain(
        exc: Exception,
        capability_id: str,
        target_id: str,
        bound_version: int,
        labels: list[str],
    ) -> VouchFailure:
        """Map per-item cancellation reasons back to a specific refusal.

        A bare "transaction cancelled" would tell an operator nothing about
        whether the capability was spent, expired, or the lot moved. Order
        matters (P1-3): when a capability was already consumed, the target
        version has usually ALSO moved, so several items fail their conditions.
        The capability check is the most specific cause and is reported first —
        otherwise a replay is mislabeled a state conflict.
        """
        reasons = getattr(exc, "response", {}).get("CancellationReasons", [])
        codes = [r.get("Code", "") for r in reasons]
        failed = [
            labels[i] if i < len(labels) else f"item{i}"
            for i, code in enumerate(codes)
            if code == "ConditionalCheckFailed"
        ]
        if not failed:
            return VouchFailure(
                FailureCategory.PERSISTENCE_FAILURE, f"transaction failed: {exc}"
            )

        if "capability" in failed:
            return VouchFailure(
                FailureCategory.POLICY_REFUSAL,
                f"capability {capability_id} is consumed, expired, or mis-bound",
            )
        if "ledger" in failed and len(failed) == 1:
            return VouchFailure(
                FailureCategory.POLICY_REFUSAL,
                f"ledger entry for {capability_id} already exists (replay)",
            )
        if "slot_reservation" in failed:
            return VouchFailure(
                FailureCategory.STATE_CONFLICT,
                "the target schedule slot is held by another order; refusing to resequence",
            )
        if "inventory" in failed:
            return VouchFailure(
                FailureCategory.STATE_CONFLICT,
                f"inventory for {target_id} moved since version {bound_version}; re-evaluate",
            )
        return VouchFailure(
            FailureCategory.STATE_CONFLICT,
            f"{target_id} is no longer at version {bound_version} or its source "
            f"state is not legal for this action; re-evaluate ({', '.join(failed)})",
        )

    # -- state helpers -----------------------------------------------------
    def put_state(
        self,
        kind: str,
        key: str,
        status: str,
        state_version: int = 1,
        *,
        planned_slot: str = "",
        quantity: float = 0.0,
        usable: bool = False,
    ) -> None:
        """Seed an entity's authoritative corpus item (and its inventory item).

        Test/provisioning helper. The runtime seeds through `DynamoCorpus.seed`;
        this exists so adapter-level tests can create a target without building
        a whole corpus.
        """
        from .corpus import InventoryRecord, Lot, ProductionOrder

        if kind == "lot":
            value = Lot(
                lot_id=key, supplier_id="", material_id="", po_reference="",
                quantity=quantity, status=status, state_version=state_version,
            )
        else:
            value = ProductionOrder(
                order_id=key, product="", quantity=0.0, requirements=(),
                resource="", planned_slot=planned_slot, status=status,
                state_version=state_version,
            )
        self.ddb.put_item(TableName=self.table, Item=corpus_item(kind, key, value))
        if kind == "lot":
            inventory = InventoryRecord(
                material_id="", lot_id=key, quantity=quantity, usable=usable
            )
            item = corpus_item("inventory", key, inventory)
            item["state_version"] = {"N": str(state_version)}
            self.ddb.put_item(TableName=self.table, Item=item)

    def get_state(self, kind: str, key: str) -> dict | None:
        item = self.ddb.get_item(
            TableName=self.table, Key=corpus_key(kind, key)
        ).get("Item")
        if item is None:
            return None
        return {
            "status": item.get("status", {}).get("S", ""),
            "planned_slot": item.get("planned_slot", {}).get("S", ""),
            "state_version": int(item.get("state_version", {}).get("N", "0")),
        }

    def get_inventory(self, lot_id: str) -> dict | None:
        item = self.ddb.get_item(
            TableName=self.table, Key=corpus_key("inventory", lot_id)
        ).get("Item")
        if item is None:
            return None
        document = json.loads(item.get("document", {}).get("S", "{}"))
        return {
            "quantity": float(document.get("quantity", 0.0)),
            "usable": item.get("usable", {}).get("BOOL", document.get("usable", False)),
            "state_version": int(item.get("state_version", {}).get("N", "0")),
        }

    def get_qa_review(self, decision_record_id: str) -> dict | None:
        item = self.ddb.get_item(
            TableName=self.table,
            Key=corpus_key("qa_review", f"QA-{decision_record_id}"),
        ).get("Item")
        if item is None:
            return None
        return json.loads(item["document"]["S"])

    def ledger_for(self, decision_record_id: str) -> list[dict]:
        """Every authority entry for one DecisionRecord, in order."""
        response = self.ddb.query(
            TableName=self.table,
            KeyConditionExpression="pk = :pk",
            ExpressionAttributeValues={":pk": {"S": f"LEDGER#{decision_record_id}"}},
        )
        return [
            {
                "capability_id": i["capability_id"]["S"],
                "action": i["action"]["S"],
                "target_id": i["target_id"]["S"],
                "before_version": int(i["before_version"]["N"]),
                "after_version": int(i["after_version"]["N"]),
                "before_state": json.loads(i.get("before_state", {}).get("S", "{}")),
                "after_state": json.loads(i.get("after_state", {}).get("S", "{}")),
                "inventory_delta": float(i.get("inventory_delta", {}).get("N", "0")),
                "parameters": json.loads(i.get("parameters", {}).get("S", "{}")),
                "at": i["at"]["S"],
            }
            for i in response.get("Items", [])
        ]


__all__ = [
    "BedrockGuardrailDetector",
    "corpus_key",
    "ClamAVScanner",
    "DynamoCapabilityStore",
    "S3EvidenceStore",
]
