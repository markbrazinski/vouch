"""The issuance trust boundary (audit-2 F1, F2, F7).

The audit finding was not "the method was named with an underscore". It was
that **any code holding the capability store could obtain issuance authority**:

    store = CapabilityStore()
    issuer = store._mint_issuer("arbitrary-caller")   # <- authority, for free
    store.issue(issuer, ..., action=RELEASE_LOT, ...)

The object that VALIDATED authority also VENDED it. That is not a boundary.

## The correction

Signing authority lives here, in a module that owns a private key and exposes
**no** function that returns a signer to a caller. The three exported surfaces
are asymmetric on purpose:

    sign(...)     -> module-private. Not exported. Not reachable by name from
                     outside; the only reference to it is captured inside the
                     `IssuanceAuthority` handed to the Policy Engine.
    verify(...)   -> public. Anyone may CHECK a proof. Checking is not authority.
    authority()   -> raises unless the caller is the Policy Engine class object
                     itself, established by identity of a class defined in this
                     package and checked against a one-shot claim.

`CapabilityStore` and `DynamoCapabilityStore` import `verify` and NOTHING else.
Neither holds a key, neither can construct a proof, and `store.issue()` demands
an `IssuanceAuthority` whose signing closure the store cannot reproduce. So a
caller holding only the store has no path to a signature, which is what the
finding required.

## Why not "check the caller's name"

Because a name is a string and strings are free. `issuer_identity` is recorded
in the ledger as *provenance*, and it is covered by the signature so it cannot
be edited after the fact — but it is never the thing that grants authority. The
signature is. A row claiming `issuer_identity="vouch.policy-engine"` without a
valid proof over that exact value is refused.

## What binds

The proof covers EVERY field that determines what the mutation does, including
action-specific parameters (F7): a resequence capability signs its target slot,
so a caller cannot pick a different slot at consume time. Consumption reads the
parameters out of the signed binding and ignores anything the caller supplies.

## Production key material

Locally the key is process-random (`secrets.token_bytes`), so a restart
invalidates outstanding capabilities — correct, since they are 5-minute
grants. In production the key is resolved through `_load_key()` from KMS or
Secrets Manager under an IAM policy that the agent/tool execution identity
cannot read; see docs/architecture/v2/CAPABILITY_SECURITY.md for the exact
trust boundary and its current verification status.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

#: The signing key. Module-private, created once per process. Nothing exports
#: it, nothing returns it, and no public function closes over it except the
#: single `IssuanceAuthority` minted for the Policy Engine.
_KEY_LOCK = threading.Lock()
_KEY: bytes | None = None

#: One-shot claim. `PolicyEngine` claims the issuance role at import time of
#: `authority.py`; a second claim by anything else is refused. This is the
#: local model of "one IAM principal may write CAP# rows".
_CLAIMED_BY: type | None = None

PROOF_VERSION = "vouch-issuance-1"


def _load_key() -> bytes:
    """Resolve signing key material.

    Order: an explicitly injected key (tests/production key management), then a
    fresh process-random key. The environment variable is NOT a general escape
    hatch — it exists so a production deployment can source the key from KMS or
    Secrets Manager under an IAM policy the agent execution identity cannot
    read, and set it into the Policy Engine's process only.
    """
    supplied = os.environ.get("VOUCH_ISSUANCE_KEY") or os.environ.get(
        "GATEHOUSE_ISSUANCE_KEY"
    )
    if supplied:
        return hashlib.sha256(supplied.encode()).digest()
    return secrets.token_bytes(32)


def _key() -> bytes:
    global _KEY
    if _KEY is None:
        with _KEY_LOCK:
            if _KEY is None:
                _KEY = _load_key()
    return _KEY


def canonical_binding(binding: dict[str, Any]) -> str:
    """Deterministic serialization of everything a capability authorizes.

    Sorted keys and no whitespace, so the same binding always produces the same
    bytes on any machine and in any Python version. A field added to a binding
    changes the proof, which is the point: an unsigned field would be a field a
    caller could change.
    """
    return json.dumps(binding, sort_keys=True, separators=(",", ":"), default=str)


def _sign(binding: dict[str, Any]) -> str:
    """Module-private. The ONLY producer of a valid proof."""
    return hmac.new(
        _key(), canonical_binding(binding).encode(), hashlib.sha256
    ).hexdigest()


def verify(binding: dict[str, Any], proof: str) -> bool:
    """Public. Checking a proof is not authority, so anyone may do it.

    The store uses this and holds nothing else: it can reject a forgery but
    cannot manufacture an acceptance.
    """
    if not proof or not isinstance(proof, str):
        return False
    return hmac.compare_digest(proof, _sign(binding))


class IssuanceViolation(PermissionError):
    """Something that is not the Policy Engine tried to obtain or use
    issuance authority."""


@dataclass(frozen=True)
class IssuanceAuthority:
    """A capability to CREATE capabilities. Held only by the Policy Engine.

    It carries a signing callable rather than key bytes, so even a holder
    cannot extract the key to sign something out of band later, and the
    dataclass never repr's or serializes it.

    Copying this object is not an attack: obtaining one in the first place is
    the guarded step, and `authority()` yields exactly one per process.
    """

    identity: str
    _sign: Callable[[dict[str, Any]], str] = field(repr=False, compare=False)

    def sign(self, binding: dict[str, Any]) -> str:
        return self._sign(binding)


def authority(claimant: type, identity: str) -> IssuanceAuthority:
    """Grant issuance authority. Refuses everything but the Policy Engine.

    `claimant` must be the `PolicyEngine` class object defined in this package —
    an identity comparison against a class, not a string a caller can assert.
    The first successful claim latches; a second distinct claimant is refused,
    so a subclass or a look-alike defined elsewhere cannot acquire authority
    after the fact.
    """
    global _CLAIMED_BY

    expected_module = f"{__package__}.authority"
    if not isinstance(claimant, type):
        raise IssuanceViolation(
            "issuance authority requires the Policy Engine class, not an instance"
        )
    if claimant.__module__ != expected_module or claimant.__qualname__ != "PolicyEngine":
        raise IssuanceViolation(
            f"{claimant.__module__}.{claimant.__qualname__} is not the Policy Engine; "
            "only the deterministic Policy Engine may create authority"
        )

    with _KEY_LOCK:
        if _CLAIMED_BY is not None and _CLAIMED_BY is not claimant:
            raise IssuanceViolation(
                "issuance authority has already been claimed by "
                f"{_CLAIMED_BY.__qualname__}"
            )
        _CLAIMED_BY = claimant

    return IssuanceAuthority(identity=identity, _sign=_sign)


__all__ = [
    "PROOF_VERSION",
    "IssuanceAuthority",
    "IssuanceViolation",
    "authority",
    "canonical_binding",
    "verify",
]
