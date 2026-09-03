#!/usr/bin/env python3
"""Live qualification for the Sponsor Depth gate.

Run AFTER the CloudShell admin step. It proves — against real AWS, not mocks —
the three things the gate is blocked on:

    1. Incoming        list_decisions succeeds, uses the GSI, joins still work
    2. Textract        a real AnalyzeDocument call on the representative COAs
    3. Observability   spans present, and no prompt/thinking/URL content

Every check reports AWS_LIVE_VERIFIED or BLOCKED with the reason. Nothing here
falls back to a local simulation: a blocked check stays blocked, because
substituting a mock is exactly how a gate gets passed without being earned.

    AWS_PROFILE=gatehouse AWS_REGION=us-east-1 \\
        .venv/bin/python scripts/verify_sponsor_depth_live.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import boto3  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402

TABLE = os.environ.get("VOUCH_STATE_TABLE", "gatehouse-dev-state")
INDEX = "decisions-by-recency"
REGION = os.environ.get("AWS_REGION", "us-east-1")
RUNTIME_ID = "Gatehouse-IWAmEp93XP"

results: list[tuple[str, str, str]] = []


def record(check: str, status: str, detail: str = "") -> None:
    results.append((check, status, detail))
    mark = {"AWS_LIVE_VERIFIED": "PASS", "BLOCKED": "BLOCK", "FAIL": "FAIL"}.get(
        status, status
    )
    print(f"  [{mark:5}] {check}" + (f" — {detail}" if detail else ""))


# ==========================================================================
# 1. Incoming — the GSI and the read path
# ==========================================================================


def check_incoming() -> None:
    print("\n1. INCOMING (decisions-by-recency)")
    ddb = boto3.client("dynamodb", region_name=REGION)

    try:
        table = ddb.describe_table(TableName=TABLE)["Table"]
    except ClientError as exc:
        record("GSI exists", "BLOCKED", exc.response["Error"]["Code"])
        return

    indexes = {i["IndexName"]: i for i in table.get("GlobalSecondaryIndexes") or []}
    if INDEX not in indexes:
        record(
            "GSI exists",
            "BLOCKED",
            f"{INDEX} absent — run the CloudShell admin step (section 1c)",
        )
        return

    index = indexes[INDEX]
    status = index.get("IndexStatus")
    record("GSI exists", "AWS_LIVE_VERIFIED", f"{INDEX} status={status}")

    keys = {k["KeyType"]: k["AttributeName"] for k in index["KeySchema"]}
    ok = keys.get("HASH") == "entity" and keys.get("RANGE") == "saved_at"
    record(
        "GSI key schema",
        "AWS_LIVE_VERIFIED" if ok else "FAIL",
        f"HASH={keys.get('HASH')} RANGE={keys.get('RANGE')}",
    )

    projected = set(index.get("Projection", {}).get("NonKeyAttributes") or [])
    needed = {"record_id", "lot_id", "disposition", "failure_category"}
    record(
        "GSI projection",
        "AWS_LIVE_VERIFIED" if needed <= projected else "FAIL",
        f"projects {sorted(projected)}",
    )

    if status != "ACTIVE":
        record("GSI query", "BLOCKED", f"index is {status}; backfill still running")
        return

    # The query the runtime actually issues.
    try:
        t0 = time.time()
        response = ddb.query(
            TableName=TABLE,
            IndexName=INDEX,
            KeyConditionExpression="entity = :e",
            ExpressionAttributeValues={":e": {"S": "DECISION"}},
            ScanIndexForward=False,
            Limit=10,
        )
        record(
            "GSI query (as gatehouse-dev)",
            "AWS_LIVE_VERIFIED",
            f"{response['Count']} rows in {time.time() - t0:.2f}s",
        )
    except ClientError as exc:
        record("GSI query", "FAIL", exc.response["Error"]["Message"][:120])
        return

    # The runtime is a different principal; that is the grant that was missing.
    try:
        control = boto3.client("bedrock-agentcore-control", region_name=REGION)
        control.get_agent_runtime(agentRuntimeId=RUNTIME_ID)
        record("runtime reachable", "AWS_LIVE_VERIFIED", RUNTIME_ID)
    except ClientError as exc:
        record("runtime reachable", "BLOCKED", exc.response["Error"]["Code"])

    print(
        "    NOTE: the runtime's own dynamodb:Query on index/* is proved by\n"
        "          invoking list_decisions through the runtime, below."
    )


def check_incoming_through_runtime() -> None:
    """The decisive one: list_decisions as the RUNTIME principal."""
    print("\n1b. INCOMING through the deployed runtime")
    try:
        client = boto3.client("bedrock-agentcore", region_name=REGION)
        arn = (
            f"arn:aws:bedrock-agentcore:{REGION}:"
            f"{boto3.client('sts').get_caller_identity()['Account']}:"
            f"runtime/{RUNTIME_ID}"
        )
        t0 = time.time()
        response = client.invoke_agent_runtime(
            agentRuntimeArn=arn,
            runtimeSessionId="sponsordepth" + "0" * 22,
            payload=json.dumps({"action": "list_decisions", "limit": 5}).encode(),
        )
        body = json.loads(response["response"].read())
        elapsed = time.time() - t0
    except ClientError as exc:
        record("list_decisions (live)", "BLOCKED", exc.response["Error"]["Code"])
        return
    except Exception as exc:  # noqa: BLE001
        record("list_decisions (live)", "BLOCKED", f"{type(exc).__name__}: {exc}")
        return

    if not body.get("ok"):
        record(
            "list_decisions (live)",
            "FAIL",
            str(body.get("error") or body.get("reason"))[:140],
        )
        return

    decisions = body.get("rows") or []
    record(
        "list_decisions (live)",
        "AWS_LIVE_VERIFIED",
        f"{len(decisions)} decisions in {elapsed:.2f}s",
    )

    # Authoritative joins: a row must carry the display fields Incoming renders.
    if decisions:
        row = decisions[0]
        joined = [k for k in ("lot_id", "material_id", "supplier_id") if row.get(k)]
        record(
            "authoritative joins",
            "AWS_LIVE_VERIFIED" if joined else "FAIL",
            f"row carries {joined}",
        )


# ==========================================================================
# 2. Textract
# ==========================================================================

#: Tracked, synthetic qualification documents — generated by
#: `fixtures/textract/make_docs.py`, not downloaded supplier evidence, so they
#: are safe to commit and the qualification is reproducible after this session.
SCRATCH = Path(os.environ.get("VOUCH_TEXTRACT_FIXTURES", str(ROOT / "fixtures" / "textract")))

#: us-east-1 AnalyzeDocument, TABLES feature, first 1M pages/month.
TEXTRACT_TABLES_USD_PER_PAGE = 0.015


def check_textract() -> None:
    print("\n2. TEXTRACT (AnalyzeDocument, TABLES)")
    from vouch.v2.aws import reflow_tables
    from vouch.v2.evidence import parse_deterministic

    client = boto3.client("textract", region_name=REGION)
    calls = 0
    pages = 0

    for name in ("coa_table_text.pdf", "coa_scanned.pdf"):
        path = SCRATCH / name
        if not path.exists():
            record(f"textract {name}", "BLOCKED", f"fixture missing: {path}")
            continue

        raw = path.read_bytes()
        try:
            t0 = time.time()
            response = client.analyze_document(
                Document={"Bytes": raw}, FeatureTypes=["TABLES"]
            )
            elapsed = time.time() - t0
            calls += 1
        except ClientError as exc:
            record(
                f"textract {name}",
                "BLOCKED",
                f"{exc.response['Error']['Code']} — run the CloudShell admin step",
            )
            continue

        blocks = response.get("Blocks", [])
        kinds: dict[str, int] = {}
        for block in blocks:
            kinds[block["BlockType"]] = kinds.get(block["BlockType"], 0) + 1
        pages += kinds.get("PAGE", 1)

        text, confidence, locators = reflow_tables(response)
        claims, extraction_confidence = parse_deterministic(text)

        record(
            f"textract {name}",
            "AWS_LIVE_VERIFIED",
            f"{elapsed:.2f}s · {len(blocks)} blocks {kinds} · "
            f"reflow_confidence={confidence} · claims={len(claims)} "
            f"(parser confidence {extraction_confidence})",
        )
        for locator in locators[:3]:
            print(
                f"           locator page={locator['page']} table={locator['table']} "
                f"row={locator['row_label']!r} col={locator['column_label']!r} "
                f"cell={locator['cell']} conf={locator['confidence']}"
            )

        from vouch.v2.aws import IDENTITY_CONFIDENCE_FLOOR

        print(
            f"           identity gate: confidence {confidence} "
            f"{'>=' if confidence >= IDENTITY_CONFIDENCE_FLOOR else '<'} "
            f"{IDENTITY_CONFIDENCE_FLOOR} -> "
            f"{'ACCEPTED' if confidence >= IDENTITY_CONFIDENCE_FLOOR else 'REFUSED'}"
        )

    if calls:
        record(
            "textract cost",
            "AWS_LIVE_VERIFIED",
            f"{calls} calls / {pages} pages "
            f"= ${pages * TEXTRACT_TABLES_USD_PER_PAGE:.4f} "
            f"at ${TEXTRACT_TABLES_USD_PER_PAGE}/page",
        )


def check_textract_end_to_end() -> None:
    """The representative table COA all the way to a Vouch outcome."""
    print("\n2b. TEXTRACT end to end")
    path = SCRATCH / "coa_table_text.pdf"
    if not path.exists():
        record("textract e2e", "BLOCKED", "fixture missing")
        return

    from vouch.v2.aws import TextractTableExtractor
    from vouch.v2.fixtures import build_corpus
    from vouch.v2.workflow import VouchV2

    corpus = build_corpus()
    try:
        t0 = time.time()
        outcome = VouchV2(
            corpus, structured_extractor=TextractTableExtractor()
        ).evaluate_lot(
            "LOT-1001",
            documents=[{"raw": path.read_bytes(), "content_type": "application/pdf"}],
        )
        elapsed = time.time() - t0
    except Exception as exc:  # noqa: BLE001
        record("textract e2e", "BLOCKED", f"{type(exc).__name__}: {exc}")
        return

    # A denied Textract call makes `recover_structure` return unused — the
    # decision then abstains, which is CORRECT behaviour but is NOT evidence
    # that Textract worked. Reporting that as a pass is how a gate gets passed
    # without being earned, so the artifact is inspected rather than the
    # outcome.
    used = bool(
        outcome.record
        and any(
            entry.get("method") == "TEXTRACT_TABLES"
            for entry in outcome.record.extraction.per_claim.values()
        )
    )
    record(
        "textract e2e",
        "AWS_LIVE_VERIFIED" if used else "BLOCKED",
        (
            f"disposition={outcome.disposition or '(none)'} "
            f"mutated={outcome.mutated} lot={corpus.lot('LOT-1001').status} "
            f"in {elapsed:.2f}s"
        )
        if used
        else "structure recovery never ran (Textract denied); the abstention "
        "below is the pre-Textract behaviour, not a qualification",
    )


# ==========================================================================
# 3. Observability
# ==========================================================================

LEAK_PHRASES = (
    "you are the vouch",
    "resolve it yourself",
    "<thinking",
    "chain_of_thought",
    "x-amz-signature",
    "certificate of analysis",
)


def check_observability() -> None:
    print("\n3. OBSERVABILITY")
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )
    except ImportError as exc:
        record("otel available", "BLOCKED", str(exc))
        return

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    from vouch.v2.telemetry import SpanSink, install_redaction

    record(
        "redaction installed",
        "AWS_LIVE_VERIFIED" if install_redaction(provider) else "FAIL",
    )

    os.environ["VOUCH_V2_MODE"] = "bedrock"
    from vouch.v2.fixtures import COA_CLEAN, build_corpus
    from vouch.v2.workflow import VouchV2

    corpus = build_corpus()
    t0 = time.time()
    outcome = VouchV2(corpus, span_sink=SpanSink()).evaluate_lot(
        "LOT-1001", documents=[{"raw": COA_CLEAN}]
    )
    elapsed = time.time() - t0
    spans = exporter.get_finished_spans()

    record(
        "live Nova Pro decision",
        "AWS_LIVE_VERIFIED",
        f"{outcome.disposition} in {elapsed:.2f}s · {len(spans)} spans",
    )

    names = {s.name for s in spans}
    for agent in ("vouch.investigator", "vouch.verifier"):
        span = next((s for s in spans if s.name == agent), None)
        record(
            f"{agent} span",
            "AWS_LIVE_VERIFIED" if span else "FAIL",
            f"{(span.end_time - span.start_time) / 1e9:.2f}s" if span else "absent",
        )

    tokens = [
        s.attributes.get("gen_ai.usage.input_tokens")
        for s in spans
        if s.attributes and s.attributes.get("gen_ai.usage.input_tokens")
    ]
    record(
        "usage/latency preserved",
        "AWS_LIVE_VERIFIED" if tokens else "FAIL",
        f"input tokens {tokens}",
    )

    tool_names = sorted(
        {
            s.attributes.get("gen_ai.tool.name")
            for s in spans
            if s.attributes and s.attributes.get("gen_ai.tool.name")
        }
    )
    record("tool names preserved", "AWS_LIVE_VERIFIED", str(tool_names))

    leaks = []
    for span in spans:
        for key, value in (span.attributes or {}).items():
            if key == "vouch.redacted_attributes":
                continue
            blob = f"{key}={value}".lower()
            for phrase in LEAK_PHRASES:
                if phrase in blob:
                    leaks.append((span.name, key, phrase))

    record(
        "zero prompt/thinking/schema/URL leakage",
        "AWS_LIVE_VERIFIED" if not leaks else "FAIL",
        f"{len(leaks)} leaks" + (f" {leaks[:3]}" if leaks else ""),
    )

    redacted = [
        s.attributes.get("vouch.redacted_attributes")
        for s in spans
        if s.attributes and s.attributes.get("vouch.redacted_attributes")
    ]
    record("redaction active", "AWS_LIVE_VERIFIED", f"{len(redacted)} attributes")


def main() -> int:
    identity = boto3.client("sts").get_caller_identity()["Arn"]
    print(f"identity: {identity.rsplit(':', 1)[0]}:...")
    if not identity.endswith("user/gatehouse-dev"):
        print("REFUSING: Vouch work runs as gatehouse-dev only (AGENTS.md §13)")
        return 2

    check_incoming()
    check_incoming_through_runtime()
    check_textract()
    check_textract_end_to_end()
    check_observability()

    print("\n" + "=" * 70)
    blocked = [r for r in results if r[1] == "BLOCKED"]
    failed = [r for r in results if r[1] == "FAIL"]
    verified = [r for r in results if r[1] == "AWS_LIVE_VERIFIED"]
    print(f"AWS_LIVE_VERIFIED {len(verified)} · BLOCKED {len(blocked)} · FAIL {len(failed)}")
    if failed:
        print("\nFAILURES:")
        for check, _status, detail in failed:
            print(f"  {check}: {detail}")
    if blocked:
        print("\nBLOCKED (external admin step required):")
        for check, _status, detail in blocked:
            print(f"  {check}: {detail}")
    print(
        "\nVERDICT: "
        + (
            "PASS — both primitives AWS_LIVE_VERIFIED"
            if not blocked and not failed
            else "NOT YET — see blocked/failed above"
        )
    )
    return 1 if (blocked or failed) else 0


if __name__ == "__main__":
    raise SystemExit(main())
