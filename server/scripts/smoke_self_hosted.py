"""Smoke-test the self-hosted API and seed Abhash's test memory.

This script intentionally uses only the Python standard library so it can run
inside the API image, on a VPS, or from a local checkout after `docker compose up`.
"""

from __future__ import annotations

import argparse
import csv
import http.server
import json
import os
import socketserver
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any


DEFAULT_USER_ID = "user"
DEFAULT_USER_NAME = "Abhash Chakraborty"


@dataclass
class WebhookCapture:
    payloads: list[dict[str, Any]] = field(default_factory=list)


class _WebhookHandler(http.server.BaseHTTPRequestHandler):
    capture: WebhookCapture

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            payload = {"raw": raw.decode("utf-8", errors="replace")}
        self.capture.payloads.append({"path": self.path, "payload": payload, "headers": dict(self.headers)})
        self.send_response(204)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


def start_webhook_server(port: int) -> WebhookCapture:
    capture = WebhookCapture()

    class Handler(_WebhookHandler):
        pass

    Handler.capture = capture
    server = socketserver.TCPServer(("0.0.0.0", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return capture


class ApiClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def request(self, method: str, path: str, body: Any | None = None, expected: tuple[int, ...] = (200,)) -> Any:
        data = None
        headers = {"X-API-Key": self.api_key}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                raw = response.read()
                if response.status not in expected:
                    raise RuntimeError(f"{method} {path} returned {response.status}: {raw[:500]!r}")
                content_type = response.headers.get("Content-Type", "")
                if "application/json" in content_type:
                    return json.loads(raw.decode("utf-8"))
                return raw.decode("utf-8")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {path} returned {exc.code}: {raw[:500]}") from exc


def _query(path: str, params: dict[str, Any]) -> str:
    return f"{path}?{urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})}"


def _ensure_category(client: ApiClient) -> str:
    name = "Smoke Test"
    categories = client.request("GET", "/categories")
    for category in categories:
        if category["name"] == name:
            return category["id"]
    category = client.request(
        "POST",
        "/categories",
        {
            "name": name,
            "description": "Temporary category used by the self-hosted smoke test.",
            "color": "#0ea5e9",
            "auto_add": False,
        },
    )
    return category["id"]


def run_smoke(args: argparse.Namespace) -> None:
    api_key = args.api_key or os.environ.get("ADMIN_API_KEY")
    if not api_key:
        raise SystemExit("Set ADMIN_API_KEY or pass --api-key.")

    capture = None
    if args.start_webhook_server:
        capture = start_webhook_server(args.webhook_port)

    client = ApiClient(args.api_url, api_key)

    client.request("GET", "/auth/setup-status")
    client.request("GET", "/configure/providers")
    client.request("GET", "/webhooks/events")

    category_id = _ensure_category(client)
    add_response = client.request(
        "POST",
        "/memories",
        {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"My name is {args.user_name}. Store this under the user entity. "
                        "I am testing memories, exports, webhooks, requests, categories, entities, and graph APIs."
                    ),
                }
            ],
            "user_id": args.user_id,
            "agent_id": "smoke-agent",
            "run_id": f"smoke-{int(time.time())}",
            "metadata": {"name": args.user_name, "smoke_test": True},
            "infer": args.infer,
        },
    )
    memories = add_response.get("results") or []
    if not memories:
        raise RuntimeError(f"Memory add returned no results: {add_response}")
    memory_id = memories[0]["id"]

    client.request("POST", f"/categories/memories/{memory_id}/assign", {"category_id": category_id})
    client.request("GET", _query("/memories", {"user_id": args.user_id}))
    client.request("POST", "/search", {"query": args.user_name, "filters": {"user_id": args.user_id}, "top_k": 3})
    client.request("GET", "/entities")
    client.request("GET", _query("/graph", {"user_id": args.user_id}))
    client.request("GET", "/requests")

    exported = client.request("GET", _query("/export", {"format": "json", "user_id": args.user_id, "limit": 10}))
    if exported.get("total", 0) < 1 or not exported.get("memories"):
        raise RuntimeError(f"JSON export did not include the seeded memory: {exported}")
    csv_export = client.request("GET", _query("/export", {"format": "csv", "user_id": args.user_id, "limit": 10}))
    rows = list(csv.DictReader(csv_export.splitlines()))
    if not rows:
        raise RuntimeError("CSV export returned no rows.")

    webhook = client.request(
        "POST",
        "/webhooks",
        {
            "name": "Smoke webhook",
            "url": args.webhook_url,
            "events": ["memory.created", "memory.updated", "memory.deleted", "search.performed", "webhook.test"],
        },
    )
    try:
        client.request("POST", f"/webhooks/{webhook['id']}/test")
        time.sleep(args.webhook_wait)
        deliveries = client.request("GET", f"/webhooks/{webhook['id']}/deliveries")
        if not deliveries:
            raise RuntimeError("Webhook test did not create a delivery.")
        if capture is not None and not capture.payloads:
            raise RuntimeError("Local webhook server did not receive the test delivery.")
    finally:
        client.request("DELETE", f"/webhooks/{webhook['id']}")

    print(
        json.dumps(
            {
                "ok": True,
                "memory_id": memory_id,
                "user_entity": args.user_id,
                "user_name": args.user_name,
                "exported_rows": len(rows),
            },
            indent=2,
        )
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default=os.environ.get("API_URL", "http://localhost:8888"))
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    parser.add_argument("--user-name", default=DEFAULT_USER_NAME)
    parser.add_argument("--infer", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--webhook-port", type=int, default=8766)
    parser.add_argument("--webhook-wait", type=float, default=1.0)
    parser.add_argument("--start-webhook-server", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--webhook-url",
        default=os.environ.get("SMOKE_WEBHOOK_URL", "http://host.docker.internal:8766/hook"),
    )
    return parser.parse_args()


if __name__ == "__main__":
    run_smoke(parse_args())
