"""Run a WeChat Official Account webhook server."""

from __future__ import annotations

import argparse
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from accountability_coach import CentralCoordinator
from accountability_coach.dialogue import DialogueAgent
from accountability_coach.wechat.official_account import (
    WeChatOfficialAccountHandler,
    verify_wechat_signature,
)


def make_handler(token: str, coach_handler: WeChatOfficialAccountHandler):
    class WeChatWebhook(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            query = parse_qs(urlparse(self.path).query)
            signature = query.get("signature", [""])[0]
            timestamp = query.get("timestamp", [""])[0]
            nonce = query.get("nonce", [""])[0]
            echostr = query.get("echostr", [""])[0]
            if verify_wechat_signature(token, signature, timestamp, nonce):
                self._send_text(200, echostr)
            else:
                self._send_text(403, "invalid signature")

        def do_POST(self) -> None:  # noqa: N802
            query = parse_qs(urlparse(self.path).query)
            signature = query.get("signature", [""])[0]
            timestamp = query.get("timestamp", [""])[0]
            nonce = query.get("nonce", [""])[0]
            if not verify_wechat_signature(token, signature, timestamp, nonce):
                self._send_text(403, "invalid signature")
                return
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length)
            reply = coach_handler.handle_xml(body)
            self.send_response(200)
            self.send_header("Content-Type", "application/xml; charset=utf-8")
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            return

        def _send_text(self, status: int, body: str) -> None:
            raw = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    return WeChatWebhook


def main() -> int:
    parser = argparse.ArgumentParser(prog="accountability-coach-wechat")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument("--memory-dir", default=".accountability_coach_memory")
    parser.add_argument("--token", default=os.getenv("WECHAT_TOKEN", ""))
    args = parser.parse_args()

    if not args.token:
        raise SystemExit("WECHAT_TOKEN or --token is required")

    coordinator = CentralCoordinator(memory_dir=Path(args.memory_dir))
    dialogue = DialogueAgent(coordinator)
    coach_handler = WeChatOfficialAccountHandler(coordinator, dialogue)
    server = HTTPServer((args.host, args.port), make_handler(args.token, coach_handler))
    print(f"WeChat webhook listening on http://{args.host}:{args.port}/wechat")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
