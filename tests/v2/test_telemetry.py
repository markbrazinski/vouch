"""Sponsor depth — observability, and the content boundary it must not cross.

The audit found raw `<thinking>` blocks already being written to the runtime's
CloudWatch log group by Strands' default logging. That is pre-existing and not
itself a contract violation — the AUDIT RECORD is still the typed output — but
AgentCore Observability's default value proposition is prompt and trace
capture, so wiring it up naively would duplicate reasoning tokens into a second
durable store while the product claims not to retain them.

These tests are the regression assertion for that. They prove:

  * no prompt, reasoning, thinking or completion text can become a span;
  * no supplier document content or presigned URL can become a span;
  * telemetry failure can never fail a decision;
  * the Investigator and the Verifier produce DISTINCT spans, which is the
    entire judge-facing point of the exercise.
"""

from __future__ import annotations

import pytest

from vouch.v2.fixtures import COA_CLEAN, build_corpus
from vouch.v2.lifecycle import EventLog, EventType, LifecycleEvent
from vouch.v2.telemetry import MAX_ATTRIBUTE_CHARS, SpanSink, is_safe_key
from vouch.v2.workflow import VouchV2


# ==========================================================================
# a tracer that records instead of exporting
# ==========================================================================


class FakeSpan:
    def __init__(self, name: str, attributes: dict) -> None:
        self.name = name
        self.attributes = dict(attributes or {})
        self.ended = False

    def set_attribute(self, key, value) -> None:
        self.attributes[key] = value

    def end(self) -> None:
        self.ended = True


class FakeTracer:
    def __init__(self) -> None:
        self.spans: list[FakeSpan] = []

    def start_span(self, name, attributes=None) -> FakeSpan:
        span = FakeSpan(name, attributes or {})
        self.spans.append(span)
        return span


@pytest.fixture
def traced():
    tracer = FakeTracer()
    corpus = build_corpus()
    vouch = VouchV2(corpus, span_sink=SpanSink(tracer=tracer))
    return tracer, corpus, vouch


# ==========================================================================
# 1. the content boundary — this is the security requirement
# ==========================================================================


FORBIDDEN_KEYS = [
    "prompt_text",
    "raw_prompt",
    "chain_of_thought",
    "reasoning",
    "rationale",
    "thinking",
    "model_thinking",
    "completion",
    "assistant_message",
]


@pytest.mark.parametrize("key", FORBIDDEN_KEYS)
def test_reasoning_keys_are_never_safe(key):
    assert is_safe_key(key) is False


CONTENT_KEYS = [
    "document",
    "document_b64",
    "text",
    "extraction_text",
    "raw",
    "content",
    "view_url",
    "presigned_url",
    "url",
    "detail",
    "credentials",
    "secret",
    "token",
    "issuance_key",
    "issuer_proof",
]


@pytest.mark.parametrize("key", CONTENT_KEYS)
def test_document_content_and_credentials_are_never_safe(key):
    assert is_safe_key(key) is False


def test_operational_metadata_is_safe():
    """The boundary must not be so blunt that it captures nothing useful."""
    for key in (
        "model_id",
        "temperature",
        "elapsed_ms",
        "claim_count",
        "confidence",
        "disposition",
        "gate_decision",
        "outcome",
        "tool",
        "agent",
        "before_version",
        "after_version",
        "storage_ref",
    ):
        assert is_safe_key(key) is True, f"{key} should be capturable"


def test_a_reasoning_bearing_event_cannot_even_be_constructed():
    """The first line of defence is upstream, in the event type itself."""
    with pytest.raises(ValueError):
        LifecycleEvent(EventType.INVESTIGATOR_STARTED, "DR-1", {"rationale": "because"})


def test_long_values_are_dropped_not_truncated():
    """A truncated document is still document content."""
    tracer = FakeTracer()
    sink = SpanSink(tracer=tracer)
    sink(
        LifecycleEvent(
            EventType.EVIDENCE_EXTRACTED,
            "DR-1",
            {"note": "x" * (MAX_ATTRIBUTE_CHARS + 1), "claim_count": 2},
        )
    )
    attributes = tracer.spans[0].attributes
    assert "note" not in attributes
    assert attributes["claim_count"] == 2


def test_nested_structures_are_dropped():
    """Document content hides in dicts and lists; no span attribute needs one."""
    tracer = FakeTracer()
    sink = SpanSink(tracer=tracer)
    sink(
        LifecycleEvent(
            EventType.EVIDENCE_SECURITY_COMPLETED,
            "DR-1",
            {
                "claimed_identity": {"claimed_lot": "LOT-1001"},
                "binding_mismatches": ["a", "b"],
                "result": "RECEIVED",
            },
        )
    )
    attributes = tracer.spans[0].attributes
    assert "claimed_identity" not in attributes
    assert "binding_mismatches" not in attributes
    assert attributes["result"] == "RECEIVED"


def test_no_span_from_a_real_decision_carries_document_text(traced):
    """End to end: run a real decision and inspect every attribute emitted."""
    tracer, _corpus, vouch = traced
    vouch.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])

    assert tracer.spans, "no spans were emitted, so nothing was proven"

    document = COA_CLEAN.decode()
    fragments = ["tensile_strength: 512", "Certificate of Analysis", "Ignore all"]
    for span in tracer.spans:
        for key, value in span.attributes.items():
            assert is_safe_key(key), f"unsafe key {key!r} reached a span"
            if isinstance(value, str):
                assert value not in document or len(value) < 40, (
                    f"{key!r} carried document content: {value!r}"
                )
                for fragment in fragments:
                    assert fragment not in value, f"{key!r} leaked {fragment!r}"


def test_presigned_urls_never_reach_a_span():
    tracer = FakeTracer()
    sink = SpanSink(tracer=tracer)
    signed = "https://bucket.s3.amazonaws.com/evidence/x?X-Amz-Signature=deadbeef"
    sink(LifecycleEvent(EventType.EVIDENCE_RECEIVED, "DR-1", {"view_url": signed}))
    for span in tracer.spans:
        assert "X-Amz-Signature" not in str(span.attributes)


# ==========================================================================
# 2. what the traces are FOR — Investigator vs Verifier
# ==========================================================================


def test_investigator_and_verifier_are_distinguishable_spans(traced):
    """The judge-facing claim: two independent invocations, not one.

    This is the property the whole observability admit exists to make visible.
    """
    tracer, _corpus, vouch = traced
    vouch.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])

    names = [s.name for s in tracer.spans]
    assert "vouch.investigator" in names
    assert "vouch.verifier" in names

    investigator = next(s for s in tracer.spans if s.name == "vouch.investigator")
    verifier = next(s for s in tracer.spans if s.name == "vouch.verifier")
    assert investigator is not verifier
    assert investigator.ended and verifier.ended


def test_agent_spans_carry_model_identity_but_not_the_prompt(traced):
    tracer, _corpus, vouch = traced
    vouch.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])

    investigator = next(s for s in tracer.spans if s.name == "vouch.investigator")
    assert "model_id" in investigator.attributes
    assert "temperature" in investigator.attributes

    # `prompt_version` is deliberately allowed: "investigator-v2.2" is a
    # version identifier, and knowing WHICH prompt ran is exactly the kind of
    # operational metadata a trace is for. What must never appear is prompt
    # TEXT, so the assertion is about content, not about the substring.
    assert investigator.attributes["prompt_version"] == "investigator-v2.2"
    assert "prompt_text" not in investigator.attributes
    assert "raw_prompt" not in investigator.attributes
    for value in investigator.attributes.values():
        if isinstance(value, str):
            assert "You are" not in value, "a system prompt reached a span"


def test_every_span_is_attributable_to_a_decision(traced):
    tracer, _corpus, vouch = traced
    outcome = vouch.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    for span in tracer.spans:
        assert span.attributes["vouch.decision_record_id"] == outcome.decision_record_id


def test_spans_are_closed(traced):
    tracer, _corpus, vouch = traced
    vouch.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    assert all(s.ended for s in tracer.spans), "an unclosed span never exports"


# ==========================================================================
# 3. telemetry must never be able to break authority
# ==========================================================================


def test_a_failing_tracer_does_not_fail_the_decision():
    class ExplodingTracer:
        def start_span(self, name, attributes=None):
            raise RuntimeError("collector unreachable")

    corpus = build_corpus()
    vouch = VouchV2(corpus, span_sink=SpanSink(tracer=ExplodingTracer()))
    outcome = vouch.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])

    assert outcome.disposition == "RELEASE"
    assert outcome.mutated is True
    assert corpus.lot("LOT-1001").status == "RELEASED"


def test_absent_opentelemetry_is_not_an_error():
    """The default composition has no tracer and must behave exactly as before."""
    sink = SpanSink(tracer=False)
    sink(LifecycleEvent(EventType.EVIDENCE_RECEIVED, "DR-1", {"artifact_id": "ART-1"}))


def test_the_sink_adds_no_event_and_changes_no_payload():
    """Observability changes WHERE events are mirrored, never WHAT is emitted."""
    corpus = build_corpus()
    plain = VouchV2(build_corpus()).evaluate_lot(
        "LOT-1001", documents=[{"raw": COA_CLEAN}]
    )
    traced = VouchV2(corpus, span_sink=SpanSink(tracer=FakeTracer())).evaluate_lot(
        "LOT-1001", documents=[{"raw": COA_CLEAN}]
    )

    assert [e["event"] for e in plain.events] == [e["event"] for e in traced.events]
    assert plain.disposition == traced.disposition


def test_an_interrupted_decision_leaves_no_open_span():
    tracer = FakeTracer()
    sink = SpanSink(tracer=tracer)
    sink(
        LifecycleEvent(
            EventType.INVESTIGATOR_STARTED, "DR-1", {"model_id": "nova", "temperature": 0.0}
        )
    )
    sink.close()
    assert all(s.ended for s in tracer.spans)


# ==========================================================================
# 4. the log-side half of the same boundary
# ==========================================================================


def test_lifecycle_events_never_carry_thinking_blocks():
    """The `<thinking>` text the audit found in CloudWatch must never become an
    EVENT, which is what the durable record and any trace are built from."""
    for key in ("thinking", "model_thinking", "assistant_thinking"):
        assert is_safe_key(key) is False


# ==========================================================================
# 5. the deploy configuration itself
# ==========================================================================


def test_the_deploy_disables_prompt_and_completion_capture():
    """A configuration assertion, because this boundary is set by env var.

    The Python guard in `telemetry.py` protects the spans THIS code emits. It
    cannot protect the spans the OTel GenAI instrumentation emits on its own —
    only configuration can, and configuration is easy to lose in a refactor.
    """
    from pathlib import Path

    deploy = (
        Path(__file__).resolve().parents[2] / "scripts" / "deploy_runtime.py"
    ).read_text()

    for switch in (
        '"OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "false"',
        '"OTEL_GENAI_CAPTURE_MESSAGE_CONTENT": "false"',
    ):
        assert switch in deploy, (
            f"{switch} is missing: the deployed runtime would capture prompts "
            "and completions into a trace backend"
        )


def test_the_deploy_enables_agentcore_observability():
    from pathlib import Path

    deploy = (
        Path(__file__).resolve().parents[2] / "scripts" / "deploy_runtime.py"
    ).read_text()
    assert '"AGENT_OBSERVABILITY_ENABLED": "true"' in deploy
    assert '"OTEL_SERVICE_NAME": "vouch-v2"' in deploy


# ==========================================================================
# 6. spans this code does NOT create
# ==========================================================================
#
# The reason this section exists is a live finding. A run against real Nova Pro
# exported an `invoke_agent verifier` span carrying the FULL system prompt in a
# `system_prompt` attribute — emitted by Strands' own auto-instrumentation, not
# by anything here. `_safe_payload` could never have caught it, and neither
# could the OTEL_*_CAPTURE_MESSAGE_CONTENT switches, because a library that
# writes its own attribute does not consult them.


from vouch.v2.telemetry import (  # noqa: E402
    RedactingSpanProcessor,
    install_redaction,
    should_redact,
)


@pytest.mark.parametrize(
    "key",
    [
        "system_prompt",
        "gen_ai.system_instructions",
        "gen_ai.prompt",
        "gen_ai.prompt.0.content",
        "gen_ai.completion",
        "gen_ai.completion.0.content",
        "gen_ai.content.prompt",
        # Carries instruction text inside Vouch's own schema descriptions.
        "gen_ai.tool.json_schema",
    ],
)
def test_prompt_bearing_span_attributes_are_redacted(key):
    assert should_redact(key) is True


@pytest.mark.parametrize(
    "key",
    [
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
        "gen_ai.usage.completion_tokens",
        "gen_ai.usage.cache_read_input_tokens",
        "gen_ai.tool.name",
        "gen_ai.request.model",
        "model_id",
        "temperature",
    ],
)
def test_operational_span_attributes_survive_redaction(key):
    """Token counts and tool NAMES are the evidence, not the risk.

    Redacting these would leave a trace that proves nothing — the tool names
    are exactly what shows a genuine agentic loop ran.
    """
    assert should_redact(key) is False


class _RecordingProcessor:
    def __init__(self):
        self.ended = []

    def on_start(self, span, parent_context=None):
        pass

    def on_end(self, span):
        self.ended.append(span)

    def shutdown(self):
        pass

    def force_flush(self, timeout_millis=30_000):
        return True


class _MutableSpan:
    def __init__(self, attributes):
        self._attributes = dict(attributes)

    @property
    def attributes(self):
        return self._attributes


def test_the_processor_strips_the_prompt_and_keeps_the_metrics():
    inner = _RecordingProcessor()
    processor = RedactingSpanProcessor(inner)
    span = _MutableSpan(
        {
            "system_prompt": "You are the Vouch Independent Reconstruction Verifier.",
            "gen_ai.usage.input_tokens": 17537,
            "gen_ai.tool.name": "list_candidate_specs",
        }
    )
    processor.on_end(span)

    assert "system_prompt" not in span.attributes
    assert span.attributes["gen_ai.usage.input_tokens"] == 17537
    assert span.attributes["gen_ai.tool.name"] == "list_candidate_specs"
    # Redaction is recorded rather than silent: an auditor can see that
    # something was removed, without seeing what it was.
    assert span.attributes["vouch.redacted_attributes"] == "system_prompt"
    assert inner.ended == [span]


def test_redaction_does_not_break_export():
    """The regression that cost a debugging cycle.

    The first version of the wrapper implemented only the public processor
    interface. The SDK calls a private `_on_ending` hook, so every span silently
    stopped exporting — spans dropped from 67 to 0 with no error anywhere.
    """
    pytest.importorskip("opentelemetry.sdk.trace")
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    assert install_redaction(provider) is True

    tracer = provider.get_tracer("test")
    span = tracer.start_span(
        "demo",
        attributes={"system_prompt": "You are secret", "gen_ai.usage.input_tokens": 12},
    )
    span.end()

    finished = exporter.get_finished_spans()
    assert len(finished) == 1, "redaction must not stop spans from exporting"
    assert "system_prompt" not in finished[0].attributes
    assert finished[0].attributes["gen_ai.usage.input_tokens"] == 12


def test_install_redaction_is_idempotent():
    pytest.importorskip("opentelemetry.sdk.trace")
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(InMemorySpanExporter()))
    install_redaction(provider)
    install_redaction(provider)

    processors = provider._active_span_processor._span_processors
    assert all(isinstance(p, RedactingSpanProcessor) for p in processors)
    assert not isinstance(processors[0]._inner, RedactingSpanProcessor)


def test_install_redaction_is_safe_without_otel():
    class Bare:
        pass

    assert install_redaction(Bare()) is False


# ==========================================================================
# 7. the LOG half of the content boundary
# ==========================================================================
#
# Spans were only half the problem. Strands defaults to PrintingCallbackHandler,
# which streams the model's <thinking> blocks to stdout — and in the deployed
# runtime stdout IS a durable CloudWatch log group. 86 such lines were counted
# in the live log group AFTER the span redaction landed, so the span fix alone
# did not close the requirement.


def test_agents_are_constructed_with_no_printing_callback():
    """`callback_handler=None` selects Strands' null handler.

    Asserted on the source rather than by capturing stdout, because the failure
    is a DEFAULT: someone adding a third Agent construction would silently
    reintroduce printing, and only a check that every construction opts out can
    catch that.
    """
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2] / "src" / "vouch" / "v2" / "agents.py"
    ).read_text()

    constructions = source.count("agent = Agent(")
    opted_out = source.count("callback_handler=None")
    assert constructions > 0, "no Agent constructions found; this test is vacuous"
    assert opted_out == constructions, (
        f"{constructions} Agent constructions but only {opted_out} set "
        "callback_handler=None — a default-printing agent would stream model "
        "reasoning into CloudWatch"
    )


def test_the_confined_extractor_does_not_print_supplier_content():
    """The extractor is the ONE model that sees raw supplier bytes.

    Printing its stream would copy untrusted document content verbatim into a
    durable log, which is strictly worse than leaking a prompt.
    """
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2] / "src" / "vouch" / "v2" / "agents.py"
    ).read_text()

    extractor = source[source.index('name="confined_extractor"') :][:400]
    assert "callback_handler=None" in extractor
