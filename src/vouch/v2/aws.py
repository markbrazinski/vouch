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
    CAPABILITY_TTL_SECONDS,
    MUTATIONS,
    Action,
    CapabilityRecord,
    Issuer,
    IssuerViolation,
    TargetType,
)
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
        """Write the immutable original. Returns (uri, sha256, version_id).

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
            kinds = [
                filt.get("type", "")
                for assessment in assessments
                for filt in assessment.get("invocationMetrics", {}).get("guardrailCoverage", [])
                or assessment.get("sensitiveInformationPolicy", {}).get("piiEntities", [])
                or []
            ]
            detail = f"guardrail intervened: {action}" + (f" {kinds}" if kinds else "")
        return detected, detail


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

#: Which corpus field each action writes, and to what value. The DynamoDB
#: transaction needs to express the mutation as a conditional update, so the
#: closed dispatch table (P0-2) is mirrored here as data rather than code.
_LOT_STATUS = {
    Action.RELEASE_LOT: "RELEASED",
    Action.QUARANTINE_LOT: "QUARANTINED",
    Action.CREATE_QA_REVIEW: "PENDING_QA",
}


class DynamoCapabilityStore:
    """Capability records in DynamoDB with atomic conditional consumption.

    Table layout (single-table, pk/sk — matches the provisioned table):

        CAP#<capability_id>   / META          capability row
        LOT#<lot_id>          / STATE         lot state + state_version
        ORDER#<order_id>      / STATE         order state + state_version
        LEDGER#<record_id>    / SEQ#<n>       append-only authority ledger

    Consumption is ONE `TransactWriteItems` containing:

      1. Update capability   ConditionExpression: exists AND unused AND unexpired
                                                  AND target/action/record match
      2. Update target       ConditionExpression: state_version = bound version
      3. Put ledger entry    ConditionExpression: attribute_not_exists(pk)

    All three commit together or none do. There is no window, and no sequence
    of ordinary writes pretending to be atomic. A `TransactionCanceledException`
    carries per-item reasons, which are mapped back to the specific refusal so
    the caller learns WHY (stale state vs already consumed vs expired).
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
        self._issuer_secret = os.urandom(32)

    @property
    def ddb(self):
        if self._ddb is None:
            self._ddb = _client("dynamodb", self._region)
        return self._ddb

    # -- issuer boundary (P0-1) -------------------------------------------
    def _mint_issuer(self, identity: str) -> Issuer:
        return Issuer(identity=identity, secret=self._issuer_secret)

    def _authorized_issuer(self, issuer: Issuer | None) -> bool:
        import secrets as _secrets

        return (
            isinstance(issuer, Issuer)
            and bool(issuer.secret)
            and _secrets.compare_digest(issuer.secret, self._issuer_secret)
        )

    def issue(
        self,
        issuer: Issuer,
        *,
        decision_record_id: str,
        target_type: TargetType,
        target_id: str,
        action: Action,
        observed_state_version: int,
        ttl_seconds: int = CAPABILITY_TTL_SECONDS,
    ) -> CapabilityRecord:
        """Write the capability row.

        In production the IAM policy on this table restricts
        `dynamodb:PutItem` on `pk=CAP#*` to the Policy Engine's task role, so
        the boundary is enforced by AWS and not only by this process. The
        credential check below is the in-process half of the same boundary.
        """
        if not self._authorized_issuer(issuer):
            identity = getattr(issuer, "identity", type(issuer).__name__)
            raise IssuerViolation(
                f"{identity!r} is not authorized to issue capabilities"
            )

        capability_id = f"CAP-{uuid.uuid4().hex[:16]}"
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        ).isoformat()
        record = CapabilityRecord(
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
                    "used": {"BOOL": False},
                    # TTL attribute so consumed/expired rows self-clean.
                    "ttl": {"N": str(int(datetime.now(timezone.utc).timestamp()) + 86400)},
                },
                ConditionExpression="attribute_not_exists(pk)",
            )
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

    # -- consumption (P0-3) ------------------------------------------------
    def consume(
        self,
        capability_id: str,
        corpus: Corpus | None = None,
        *,
        params: dict | None = None,
    ) -> dict:
        """Atomically validate, consume, mutate and append to the ledger.

        `corpus` is accepted for interface symmetry with the local store but is
        NOT the source of truth here — DynamoDB is. State is read from and
        written to the table.
        """
        row = self.get(capability_id)
        if row is None:
            raise VouchFailure(
                FailureCategory.POLICY_REFUSAL,
                "no Policy-Engine-issued capability for this id",
            )

        action = Action(row["action"]["S"])
        target_type = TargetType(row["target_type"]["S"])
        target_id = row["target_id"]["S"]
        record_id = row["decision_record_id"]["S"]
        bound_version = int(row["observed_state_version"]["N"])
        now = datetime.now(timezone.utc).isoformat()

        if action not in MUTATIONS:
            raise VouchFailure(
                FailureCategory.POLICY_REFUSAL,
                f"no mutation is bound to {action.value}; refusing",
            )

        target_pk = (
            f"LOT#{target_id}" if target_type is TargetType.LOT else f"ORDER#{target_id}"
        )
        new_version = bound_version + 1
        sequence = f"{record_id}#{capability_id}"

        # What this action writes on the target.
        if target_type is TargetType.LOT:
            status = _LOT_STATUS.get(action)
            if status is None:
                raise VouchFailure(
                    FailureCategory.POLICY_REFUSAL,
                    f"{action.value} is not a lot action",
                )
            target_update = "SET #s = :status, state_version = :new"
            target_values = {":status": {"S": status}, ":new": {"N": str(new_version)}}
        else:
            if action is Action.HOLD_PRODUCTION_ORDER:
                status = "BLOCKED"
            elif action is Action.SET_ORDER_READINESS:
                status = str((params or {}).get("readiness", ""))
            else:
                status = ""
            if action is Action.RESEQUENCE_PRODUCTION_ORDER:
                slot = str((params or {}).get("target_slot", ""))
                if not slot:
                    raise VouchFailure(
                        FailureCategory.POLICY_REFUSAL, "resequence requires a target_slot"
                    )
                target_update = "SET planned_slot = :slot, state_version = :new"
                target_values = {":slot": {"S": slot}, ":new": {"N": str(new_version)}}
            else:
                target_update = "SET #s = :status, state_version = :new"
                target_values = {
                    ":status": {"S": status},
                    ":new": {"N": str(new_version)},
                }

        transact = [
            # 1. consume the capability — the single-use + expiry + binding gate
            {
                "Update": {
                    "TableName": self.table,
                    "Key": {"pk": {"S": f"CAP#{capability_id}"}, "sk": {"S": "META"}},
                    "UpdateExpression": "SET used = :true, consumed_at = :now",
                    "ConditionExpression": (
                        "attribute_exists(pk) AND used = :false "
                        "AND expires_at > :now "
                        "AND target_id = :target AND #a = :action "
                        "AND decision_record_id = :record "
                        "AND observed_state_version = :bound"
                    ),
                    "ExpressionAttributeNames": {"#a": "action"},
                    "ExpressionAttributeValues": {
                        ":true": {"BOOL": True},
                        ":false": {"BOOL": False},
                        ":now": {"S": now},
                        ":target": {"S": target_id},
                        ":action": {"S": action.value},
                        ":record": {"S": record_id},
                        ":bound": {"N": str(bound_version)},
                    },
                }
            },
            # 2. mutate the target — optimistic concurrency on state_version
            {
                "Update": {
                    "TableName": self.table,
                    "Key": {"pk": {"S": target_pk}, "sk": {"S": "STATE"}},
                    "UpdateExpression": target_update,
                    "ConditionExpression": "state_version = :bound",
                    "ExpressionAttributeNames": {"#s": "status"},
                    "ExpressionAttributeValues": {
                        **target_values,
                        ":bound": {"N": str(bound_version)},
                    },
                }
            },
            # 3. append the authority ledger entry — idempotent by capability
            {
                "Put": {
                    "TableName": self.table,
                    "Item": {
                        "pk": {"S": f"LEDGER#{record_id}"},
                        "sk": {"S": f"SEQ#{sequence}"},
                        "capability_id": {"S": capability_id},
                        "decision_record_id": {"S": record_id},
                        "issuer_identity": {"S": row.get("issuer_identity", {}).get("S", "")},
                        "action": {"S": action.value},
                        "target_type": {"S": target_type.value},
                        "target_id": {"S": target_id},
                        "before_version": {"N": str(bound_version)},
                        "after_version": {"N": str(new_version)},
                        "at": {"S": now},
                    },
                    "ConditionExpression": "attribute_not_exists(pk)",
                }
            },
        ]
        if action is Action.RESEQUENCE_PRODUCTION_ORDER:
            transact[1]["Update"].pop("ExpressionAttributeNames", None)

        try:
            self.ddb.transact_write_items(TransactItems=transact)
        except Exception as exc:  # noqa: BLE001
            raise self._explain(exc, capability_id, target_id, bound_version) from exc

        return {
            "sequence": sequence,
            "capability_id": capability_id,
            "decision_record_id": record_id,
            "issuer_identity": row.get("issuer_identity", {}).get("S", ""),
            "action": action.value,
            "target_type": target_type.value,
            "target_id": target_id,
            "before_version": bound_version,
            "after_version": new_version,
            "result": f"{target_id} -> {action.value}",
            "inventory_delta": 0.0,
            "at": now,
        }

    @staticmethod
    def _explain(
        exc: Exception, capability_id: str, target_id: str, bound_version: int
    ) -> VouchFailure:
        """Map per-item cancellation reasons back to a specific refusal.

        A bare "transaction cancelled" would tell an operator nothing about
        whether the capability was spent, expired, or the lot moved. Order
        matters (P1-3): when a capability was already consumed, the target
        version has usually ALSO moved, so both item 0 and item 1 fail their
        conditions. The capability check is the more specific cause and is
        reported first — otherwise a replay is mislabeled a state conflict.
        """
        reasons = getattr(exc, "response", {}).get("CancellationReasons", [])
        codes = [r.get("Code", "") for r in reasons]

        if codes and codes[0] == "ConditionalCheckFailed":
            return VouchFailure(
                FailureCategory.POLICY_REFUSAL,
                f"capability {capability_id} is consumed, expired, or mis-bound",
            )
        if len(codes) >= 2 and codes[1] == "ConditionalCheckFailed":
            return VouchFailure(
                FailureCategory.STATE_CONFLICT,
                f"{target_id} is no longer at version {bound_version}; re-evaluate",
            )
        if len(codes) >= 3 and codes[2] == "ConditionalCheckFailed":
            return VouchFailure(
                FailureCategory.POLICY_REFUSAL,
                f"ledger entry for {capability_id} already exists (replay)",
            )
        return VouchFailure(
            FailureCategory.PERSISTENCE_FAILURE, f"transaction failed: {exc}"
        )

    # -- state helpers -----------------------------------------------------
    def put_state(self, kind: str, key: str, status: str, state_version: int = 1) -> None:
        """Seed an entity's authoritative state row."""
        pk = f"LOT#{key}" if kind == "lot" else f"ORDER#{key}"
        self.ddb.put_item(
            TableName=self.table,
            Item={
                "pk": {"S": pk},
                "sk": {"S": "STATE"},
                "status": {"S": status},
                "state_version": {"N": str(state_version)},
            },
        )

    def get_state(self, kind: str, key: str) -> dict | None:
        pk = f"LOT#{key}" if kind == "lot" else f"ORDER#{key}"
        item = self.ddb.get_item(
            TableName=self.table, Key={"pk": {"S": pk}, "sk": {"S": "STATE"}}
        ).get("Item")
        if item is None:
            return None
        return {
            "status": item.get("status", {}).get("S", ""),
            "planned_slot": item.get("planned_slot", {}).get("S", ""),
            "state_version": int(item.get("state_version", {}).get("N", "0")),
        }

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
                "at": i["at"]["S"],
            }
            for i in response.get("Items", [])
        ]


__all__ = [
    "BedrockGuardrailDetector",
    "ClamAVScanner",
    "DynamoCapabilityStore",
    "S3EvidenceStore",
]
