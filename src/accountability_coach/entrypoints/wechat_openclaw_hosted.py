"""Hosted multi-account OpenClaw web server."""

from __future__ import annotations

import argparse
import asyncio
import html
import os
import threading
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse

from accountability_coach import CentralCoordinator
from accountability_coach.dialogue import AccessControl, DialogueAgent
from accountability_coach.wechat.openclaw_client import OpenClawConfig
from accountability_coach.wechat.openclaw_multi import (
    HostedAccountStatus,
    OpenClawMultiAccountManager,
)


def make_handler(
    manager: OpenClawMultiAccountManager,
    loop: asyncio.AbstractEventLoop,
    *,
    web_token: str = "",
):
    class HostedOpenClawHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if not self._authorized():
                self._send_html(HTTPStatus.UNAUTHORIZED, self._wrap("需要访问口令", "<p>这个页面需要访问口令。</p>"))
                return
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_html(HTTPStatus.OK, self._index_page())
                return
            if parsed.path.startswith("/accounts/"):
                account_id = parsed.path.removeprefix("/accounts/").strip("/")
                if not account_id:
                    self._send_not_found()
                    return
                try:
                    status = manager.get_status(account_id)
                except KeyError:
                    self._send_not_found()
                    return
                self._send_html(HTTPStatus.OK, self._account_page(status))
                return
            if parsed.path == "/api/accounts":
                self._send_json(
                    HTTPStatus.OK,
                    {"accounts": [asdict(status) for status in manager.list_statuses()]},
                )
                return
            self._send_not_found()

        def do_POST(self) -> None:  # noqa: N802
            if not self._authorized():
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                return
            parsed = urlparse(self.path)
            if parsed.path == "/accounts":
                account = self._run(manager.create_account())
                self._redirect(self._with_token(f"/accounts/{account.account_id}"))
                return
            if parsed.path.startswith("/accounts/") and parsed.path.endswith("/login"):
                account_id = parsed.path.removeprefix("/accounts/").removesuffix("/login").strip("/")
                try:
                    self._run(manager.start_login(account_id))
                except KeyError:
                    self._send_not_found()
                    return
                self._redirect(self._with_token(f"/accounts/{account_id}"))
                return
            self._send_not_found()

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            return

        def _index_page(self) -> str:
            rows = []
            for status in manager.list_statuses():
                rows.append(
                    "<tr>"
                    f"<td><a href='{self._with_token('/accounts/' + status.account_id)}'>{html.escape(status.account_id)}</a></td>"
                    f"<td>{'已登录' if status.logged_in else html.escape(status.login_status)}</td>"
                    f"<td>{html.escape(status.ilink_account_id or '-')}</td>"
                    f"<td>{status.context_count}</td>"
                    f"<td>{html.escape(status.last_error or '')}</td>"
                    "</tr>"
                )
            table = (
                "<table><thead><tr><th>账号</th><th>状态</th><th>OpenClaw ID</th><th>会话数</th><th>错误</th></tr></thead>"
                f"<tbody>{''.join(rows) or '<tr><td colspan=\"5\">还没有账号</td></tr>'}</tbody></table>"
            )
            body = (
                f"<form method='post' action='{self._with_token('/accounts')}'>"
                "<button type='submit'>新建微信登录</button>"
                "</form>"
                "<p class='hint'>朋友打开这个页面，点“新建微信登录”，然后用自己的微信扫码。</p>"
                f"{table}"
            )
            return self._wrap("OpenClaw 多账号托管", body)

        def _account_page(self, status: HostedAccountStatus) -> str:
            qr = ""
            if not status.logged_in:
                if status.qrcode_img_content:
                    img = (
                        "https://api.qrserver.com/v1/create-qr-code/?size=260x260&data="
                        + quote(status.qrcode_img_content)
                    )
                    qr = (
                        f"<img class='qr' src='{img}' alt='微信登录二维码'>"
                        "<p>用要托管的微信扫码确认登录。这个页面会自动刷新。</p>"
                    )
                else:
                    qr = (
                        f"<form method='post' action='{self._with_token('/accounts/' + status.account_id + '/login')}'>"
                        "<button type='submit'>生成二维码</button>"
                        "</form>"
                    )
            body = (
                "<meta http-equiv='refresh' content='3'>"
                f"<p><a href='{self._with_token('/')}'>返回列表</a></p>"
                f"<h2>{html.escape(status.account_id)}</h2>"
                f"<p>状态：{'已登录' if status.logged_in else html.escape(status.login_status)}</p>"
                f"<p>OpenClaw ID：{html.escape(status.ilink_account_id or '-')}</p>"
                f"<p>已建立会话数：{status.context_count}</p>"
                f"{'<p class=\"error\">' + html.escape(status.last_error) + '</p>' if status.last_error else ''}"
                f"{qr}"
                "<p class='hint'>扫码成功后，让这个微信账号先收到一条消息，系统才能拿到发送所需的 context_token。</p>"
            )
            return self._wrap("微信账号登录", body)

        def _wrap(self, title: str, body: str) -> str:
            return (
                "<!doctype html><html><head><meta charset='utf-8'>"
                f"<title>{html.escape(title)}</title>"
                "<style>"
                "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:900px;margin:40px auto;padding:0 20px;line-height:1.5}"
                "button{font-size:16px;padding:8px 14px;border-radius:6px;border:1px solid #999;background:#fff;cursor:pointer}"
                "table{border-collapse:collapse;width:100%;margin-top:20px}td,th{border-bottom:1px solid #ddd;padding:8px;text-align:left}"
                ".qr{width:260px;height:260px;border:1px solid #ddd}.hint{color:#666}.error{color:#b00020}"
                "</style></head><body>"
                f"<h1>{html.escape(title)}</h1>{body}</body></html>"
            )

        def _authorized(self) -> bool:
            if not web_token:
                return True
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            return query.get("token", [""])[0] == web_token

        def _with_token(self, path: str) -> str:
            if not web_token:
                return path
            separator = "&" if "?" in path else "?"
            return path + separator + urlencode({"token": web_token})

        def _run(self, coro):
            future = asyncio.run_coroutine_threadsafe(coro, loop)
            return future.result(timeout=60)

        def _send_html(self, status: HTTPStatus, content: str) -> None:
            body = content.encode("utf-8")
            self.send_response(int(status))
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            import json

            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(int(status))
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _redirect(self, path: str) -> None:
            self.send_response(int(HTTPStatus.SEE_OTHER))
            self.send_header("Location", path)
            self.end_headers()

        def _send_not_found(self) -> None:
            self._send_html(HTTPStatus.NOT_FOUND, self._wrap("Not Found", "<p>没有这个页面。</p>"))

    return HostedOpenClawHandler


def main() -> int:
    parser = argparse.ArgumentParser(prog="accountability-coach-wechat-openclaw-hosted")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--memory-dir", default=".accountability_coach_memory")
    parser.add_argument("--base-url", default="https://ilinkai.weixin.qq.com")
    parser.add_argument("--bot-type", default="3")
    parser.add_argument("--qr-poll-interval", type=int, default=1)
    parser.add_argument("--long-poll-timeout-ms", type=int, default=35_000)
    parser.add_argument("--api-timeout-ms", type=int, default=15_000)
    parser.add_argument("--push-poll-seconds", type=int, default=5)
    parser.add_argument("--invite-code", action="append", default=[], help="Invite code for downstream coach chats")
    parser.add_argument("--allowed-user", action="append", default=[], help="Namespaced coach user id allowed without invite")
    parser.add_argument("--require-invite", action="store_true")
    parser.add_argument("--web-token", default=os.getenv("ACCOUNTABILITY_COACH_WEB_ACCESS_TOKEN", ""))
    args = parser.parse_args()

    config = OpenClawConfig(
        base_url=args.base_url,
        bot_type=args.bot_type,
        qr_poll_interval_seconds=args.qr_poll_interval,
        long_poll_timeout_ms=args.long_poll_timeout_ms,
        api_timeout_ms=args.api_timeout_ms,
        push_poll_seconds=args.push_poll_seconds,
    )
    memory_dir = Path(args.memory_dir)
    coordinator = CentralCoordinator(memory_dir=memory_dir)
    access_control = AccessControl.from_env(
        invite_codes=args.invite_code,
        allowed_users=args.allowed_user,
        require_invite=args.require_invite,
    )
    dialogue = DialogueAgent(coordinator, access_control=access_control)
    manager = OpenClawMultiAccountManager(
        coordinator=coordinator,
        dialogue=dialogue,
        config=config,
        accounts_dir=memory_dir / "wechat_openclaw_accounts",
    )

    loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
    loop_thread.start()
    asyncio.run_coroutine_threadsafe(manager.load_existing(), loop).result(timeout=60)

    server = ThreadingHTTPServer((args.host, args.port), make_handler(manager, loop, web_token=args.web_token))
    url = f"http://{args.host}:{args.port}/"
    if args.web_token:
        url += "?" + urlencode({"token": args.web_token})
    print(f"Serving hosted OpenClaw multi-account console on {url}")
    if not args.web_token:
        print("Warning: no web access token is configured. Do not expose this port publicly.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        asyncio.run_coroutine_threadsafe(manager.stop_all(), loop).result(timeout=60)
        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
