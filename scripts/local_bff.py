#!/usr/bin/env python3
"""Local stand-in for the BFF, for frontend development only.

The real BFF (`bff/handler.py`) is Lambda-shaped and cannot be deployed:
`gatehouse-dev` holds neither `lambda:*` nor `apigateway:*`. This serves the
SAME routes over localhost so the React app can be built and exercised against
the real deployed AgentCore runtime in the meantime.

It is deliberately NOT a second implementation. It imports `bff.handler` and
calls its `handler(event, context)` with an API-Gateway-shaped event, so the
allowlist, the identifier validation and the payload rebuilding that carry the
security properties are the ones that will ship. If this file and the Lambda
ever disagree, this file is wrong.

    AWS_PROFILE=gatehouse AWS_REGION=us-east-1 \
        .venv/bin/python scripts/local_bff.py

Then `npm run dev` in frontend/ — vite proxies /api to :8787.

NOT for production. It signs with the developer's own credentials, which is
exactly what the real BFF exists to avoid doing in a browser.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "bff"))

PORT = int(os.environ.get("VOUCH_BFF_PORT", "8787"))

os.environ.setdefault("VOUCH_ALLOWED_ORIGIN", "http://localhost:5173")
if not os.environ.get("VOUCH_RUNTIME_ARN"):
    import boto3

    account = boto3.client("sts").get_caller_identity()["Account"]
    region = os.environ.get("AWS_REGION", "us-east-1")
    os.environ["VOUCH_RUNTIME_ARN"] = (
        f"arn:aws:bedrock-agentcore:{region}:{account}:runtime/Gatehouse-IWAmEp93XP"
    )

import handler as bff  # noqa: E402  — the REAL handler, not a copy

bff.RUNTIME_ARN = os.environ["VOUCH_RUNTIME_ARN"]
bff.ALLOWED_ORIGIN = os.environ["VOUCH_ALLOWED_ORIGIN"]


def _start_background_locally(payload: dict) -> None:
    """Run the worker in a thread instead of a second Lambda invocation.

    The deployed BFF starts background work with `InvocationType="Event"`
    against ITSELF, which needs `AWS_LAMBDA_FUNCTION_NAME` and a deployed
    function. Neither exists here — `gatehouse-dev` holds no `lambda:*` — so
    `evaluate_lot` would 502 locally with "the decision service could not be
    started", and no amount of polling would ever produce a decision.

    This is NOT a second implementation of the worker. It calls the SAME
    `bff.handler` with the SAME worker-shaped event the Lambda would receive, so
    the validated payload, the runtime invocation and the failure contract are
    the ones that ship. Only the transport differs: a thread here, an async
    Lambda invocation in production.

    Local development only. The deployed handler never imports this file.
    """
    threading.Thread(
        target=bff.handler,
        args=({bff.WORKER_MARKER: True, "payload": payload},),
        daemon=True,
    ).start()


bff.start_background = _start_background_locally


class Proxy(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _serve(self, method: str) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length).decode() if length else ""

        event = {
            "requestContext": {"http": {"method": method}},
            "rawPath": parsed.path,
            "queryStringParameters": {
                k: v[0] for k, v in parse_qs(parsed.query).items()
            },
            "headers": {"origin": self.headers.get("origin", "")},
            "body": body,
            "isBase64Encoded": False,
        }

        try:
            result = bff.handler(event)
        except Exception as exc:  # noqa: BLE001
            # Mirror the Lambda's own contract: a transport failure is a
            # TECHNICAL_FAILURE and carries no disposition.
            result = {
                "statusCode": 502,
                "headers": {"content-type": "application/json"},
                "body": json.dumps(
                    {
                        "ok": False,
                        "failure_class": "TECHNICAL_FAILURE",
                        "error": f"{type(exc).__name__}",
                    }
                ),
            }

        payload = (result.get("body") or "").encode()
        self.send_response(result.get("statusCode", 200))
        for key, value in (result.get("headers") or {}).items():
            self.send_header(key, value)
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        self._serve("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._serve("POST")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._serve("OPTIONS")

    def log_message(self, fmt: str, *args) -> None:
        # One line per request, and never the response body: a `get_source`
        # response carries a presigned URL, which is a bearer credential.
        sys.stderr.write(f"  bff {fmt % args}\n")


def main() -> int:
    print(f"local BFF on http://127.0.0.1:{PORT}  ->  {bff.RUNTIME_ARN.rsplit('/', 1)[-1]}")
    print("   routes: /api/evaluate /api/evidence /api/today /api/decisions[/{id}[/events|/sources]]")
    ThreadingHTTPServer(("127.0.0.1", PORT), Proxy).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
