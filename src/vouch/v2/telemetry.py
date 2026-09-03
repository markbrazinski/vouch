"""Sponsor depth — lifecycle events as OpenTelemetry spans.

This is EVIDENCE, not capability. Nothing here decides anything, and nothing
here is authoritative: the DecisionRecord and the append-only authority ledger
remain the sole audit record. A trace is a second, sampled, lossy copy, and
treating it as truth would create exactly the second source of truth the audit
rejected.

What it buys is the one thing the architecture could not previously SHOW: that
the Investigator and the Verifier are two independently executed model
invocations rather than one prompt run twice. That claim is the most contested
part of the design (D21), and until now it was provable only by reading Python.

Why this is a sink rather than instrumentation scattered through the pipeline:
`EventLog` already accepts `sinks=[...]`, the pattern is already load-bearing
and already tested, including the rule that a sink failure must never fail a
decision. So the observable surface is exactly the lifecycle vocabulary — no
new event type, no new payload key, and no emit-site change.

SECURITY — the hard constraint this module exists to enforce:

    Telemetry carries operational metadata. It never carries prompts, model
    reasoning, <thinking> blocks, chain-of-thought, raw supplier document
    content, credentials, or presigned URLs.

`lifecycle.LifecycleEvent` already raises on reasoning-bearing payload KEYS, so
events are safe by construction. That is necessary but not sufficient: a
payload VALUE could still carry document text or a signed URL. `_safe_payload`
below is the second half, and `tests/v2/test_telemetry.py` asserts both.
"""

from __future__ import annotations

from typing import Any

from .lifecycle import EventType, LifecycleEvent

#: Payload keys that may carry supplier document text, a credential, or a URL
#: that is itself an authorization. None of these belong in a trace backend.
#:
#: `storage_ref` is deliberately NOT here: `s3://bucket/evidence/LOT/ART-x` is
#: an object identifier that already appears in the audit record and confers no
#: access on its own. `view_url` IS here, because a presigned URL is a
#: bearer credential with a TTL — logging one puts an unauthenticated copy of
#: evidence somewhere it outlives the request.
_UNSAFE_KEYS = frozenset(
    {
        "document",
        "document_b64",
        "text",
        "extraction_text",
        "raw",
        "content",
        "view_url",
        "presigned_url",
        "url",
        "detail",  # guardrail detail can quote the offending document span
        "credentials",
        "secret",
        "token",
        "issuance_key",
        "issuer_proof",
    }
)

#: Substrings that mark a key as private reasoning. Mirrors the guard in
#: `lifecycle._FORBIDDEN_KEYS`; duplicated on purpose, because this module must
#: hold the line even if a future event type is added without one.
_REASONING_MARKERS = (
    "chain_of_thought",
    "reasoning",
    "rationale",
    "raw_prompt",
    "prompt_text",
    "thinking",
    "completion",
    "message",
)

#: Values longer than this are dropped rather than truncated. A truncated
#: document is still document content, and a span attribute is not the place to
#: discover that.
MAX_ATTRIBUTE_CHARS = 512

#: Which events open a span that other events nest inside. These are the three
#: durations anyone actually wants: the whole decision, and each agent.
_SPAN_STARTS = {
    EventType.INVESTIGATOR_STARTED: "vouch.investigator",
    EventType.VERIFIER_STARTED: "vouch.verifier",
}

_SPAN_ENDS = {
    EventType.APPLICABILITY_BRIEF_COMPLETED: "vouch.investigator",
    EventType.VERIFIER_BRIEF_COMPLETED: "vouch.verifier",
}


def is_safe_key(key: str) -> bool:
    """Whether one payload key may become a span attribute."""
    low = key.lower()
    if low in _UNSAFE_KEYS:
        return False
    return not any(marker in low for marker in _REASONING_MARKERS)


def _safe_payload(payload: dict) -> dict[str, Any]:
    """Operational metadata only.

    Deny by default on shape as well as name: only scalars survive. A nested
    dict or list is where document content hides, and no span attribute in this
    system needs one.
    """
    safe: dict[str, Any] = {}
    for key, value in payload.items():
        if not is_safe_key(key):
            continue
        if isinstance(value, bool) or isinstance(value, (int, float)):
            safe[key] = value
        elif isinstance(value, str):
            if len(value) <= MAX_ATTRIBUTE_CHARS:
                safe[key] = value
        # Everything else — dict, list, bytes, object — is dropped.
    return safe


#: Attribute names that carry prompt or completion TEXT on spans this code does
#: not create. Strands' own auto-instrumentation emits `invoke_agent` spans and
#: puts the full system prompt on them; the OTel GenAI conventions add message
#: content under `gen_ai.prompt` / `gen_ai.completion` when capture is enabled.
#:
#: This was found by LIVE qualification, not by reading: a run against real Nova
#: Pro exported an `invoke_agent verifier` span whose `system_prompt` attribute
#: contained "You are the Vouch Independent Reconstruction Verifier...". The
#: Python guard in `_safe_payload` could never have caught it, because that span
#: is not ours.
#:
#: `gen_ai.usage.*` is deliberately NOT redacted: those are token COUNTS, which
#: are exactly the operational metadata a trace is for.
#: `gen_ai.tool.json_schema` is included after inspecting what it actually
#: holds live: Vouch's structured-output schema carries INSTRUCTION text in its
#: field descriptions ("Resolve it yourself from the candidates... The revision
#: a supplier document names is a claim, not authority"). That is prompt
#: content by any honest reading, so it goes. `gen_ai.tool.name` stays — the
#: tool NAME is the evidence that real tool-calling happened.
_REDACT_EXACT = frozenset(
    {"system_prompt", "gen_ai.system_instructions", "gen_ai.tool.json_schema"}
)
_REDACT_PREFIXES = ("gen_ai.prompt", "gen_ai.completion", "gen_ai.content")


def should_redact(key: str) -> bool:
    """Whether a span attribute from ANY instrumentation must be dropped."""
    low = key.lower()
    if low in _REDACT_EXACT:
        return True
    if low.startswith(_REDACT_PREFIXES):
        return True
    if low.startswith("gen_ai.usage"):
        return False
    return not is_safe_key(low.rsplit(".", 1)[-1])


class RedactingSpanProcessor:
    """Strips prompt/completion text from every span before it is exported.

    Configuration alone cannot carry this requirement. The GenAI capture
    switches govern the instrumentation that reads them; a library that puts a
    system prompt on its own span attribute ignores them entirely, which is
    exactly what live qualification found Strands doing.

    So the boundary is enforced structurally, at the last point before export,
    for spans this code did not create and does not control.
    """

    def __init__(self, inner) -> None:
        self._inner = inner

    def __getattr__(self, name):
        """Delegate everything not overridden here.

        The SDK calls private hooks on processors (`_on_ending`), and a wrapper
        that implements only the public interface silently breaks export — which
        is how this was found: spans dropped to zero.
        """
        return getattr(self._inner, name)

    def on_start(self, span, parent_context=None) -> None:
        on_start = getattr(self._inner, "on_start", None)
        if on_start:
            on_start(span, parent_context)

    def _on_ending(self, span) -> None:
        """Redact here: the SDK calls this while the span is still mutable."""
        self._redact(span)
        inner = getattr(self._inner, "_on_ending", None)
        if inner:
            inner(span)

    def _redact(self, span) -> None:
        attributes = dict(getattr(span, "attributes", {}) or {})
        removed = [k for k in attributes if should_redact(k)]
        if removed:
            for key in removed:
                attributes.pop(key, None)
            attributes["vouch.redacted_attributes"] = ",".join(sorted(removed))
            try:
                # BoundedAttributes is a read-only mapping; replacing the whole
                # dict is the supported way to rewrite it before export.
                span._attributes = attributes
            except Exception:  # noqa: BLE001 — never fail an export
                pass

    def on_end(self, span) -> None:
        # Belt and braces: `_on_ending` is where a still-mutable span is
        # offered, but redact again in case an SDK version skips that hook.
        self._redact(span)
        self._inner.on_end(span)

    def shutdown(self) -> None:
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return self._inner.force_flush(timeout_millis)


def install_redaction(provider=None) -> bool:
    """Wrap every span processor on `provider` so nothing exports prompt text.

    Returns whether redaction was installed. Safe to call when OTel is absent.
    """
    try:
        if provider is None:
            from opentelemetry import trace

            provider = trace.get_tracer_provider()
        active = getattr(provider, "_active_span_processor", None)
        processors = getattr(active, "_span_processors", None)
        if not processors:
            return False
        wrapped = tuple(
            p if isinstance(p, RedactingSpanProcessor) else RedactingSpanProcessor(p)
            for p in processors
        )
        active._span_processors = wrapped
        return True
    except Exception:  # noqa: BLE001 — telemetry never fails a decision
        return False


class SpanSink:
    """An `EventLog` sink that mirrors lifecycle events onto OTel spans.

    Best-effort by construction, matching the durable sink's own contract:
    observability must never be able to break authority, so every failure path
    here swallows rather than raises.
    """

    def __init__(self, tracer=None) -> None:
        self._tracer = tracer
        self._open: dict[str, Any] = {}

    @property
    def tracer(self):
        if self._tracer is None:
            try:
                from opentelemetry import trace

                self._tracer = trace.get_tracer("vouch.v2")
            except Exception:  # noqa: BLE001 — no OTel is not a decision failure
                self._tracer = False
        return self._tracer

    def __call__(self, event: LifecycleEvent) -> None:
        tracer = self.tracer
        if not tracer:
            return
        try:
            self._record(tracer, event)
        except Exception:  # noqa: BLE001 — telemetry never fails a decision
            pass

    def _record(self, tracer, event: LifecycleEvent) -> None:
        attributes = _safe_payload(event.payload)
        attributes["vouch.decision_record_id"] = event.decision_record_id
        attributes["vouch.event"] = event.event_type.value

        name = _SPAN_STARTS.get(event.event_type)
        if name:
            span = tracer.start_span(name, attributes=attributes)
            self._open[name] = span
            return

        ending = _SPAN_ENDS.get(event.event_type)
        if ending:
            span = self._open.pop(ending, None)
            if span is not None:
                for key, value in attributes.items():
                    span.set_attribute(key, value)
                span.end()
                return

        # Everything else is a point-in-time fact. A zero-duration span keeps
        # the whole lifecycle visible in one trace without inventing a duration
        # the pipeline never measured.
        span = tracer.start_span(f"vouch.{event.event_type.value.lower()}",
                                 attributes=attributes)
        span.end()

    def close(self) -> None:
        """End any span left open by a decision that failed mid-flight."""
        while self._open:
            _name, span = self._open.popitem()
            try:
                span.end()
            except Exception:  # noqa: BLE001
                pass


__all__ = [
    "MAX_ATTRIBUTE_CHARS",
    "RedactingSpanProcessor",
    "SpanSink",
    "install_redaction",
    "is_safe_key",
    "should_redact",
]
