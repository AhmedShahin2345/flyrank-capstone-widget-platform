"""Real-browser rendering test for the copy-and-paste widget bundle."""

import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

import httpx
import pytest

playwright = pytest.importorskip("playwright.sync_api")

ROOT = Path(__file__).resolve().parents[1]


def unused_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_health(api_base: str, process: subprocess.Popen[str]) -> None:
    for _ in range(50):
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout else ""
            raise RuntimeError(f"Uvicorn stopped before becoming healthy:\n{output}")
        try:
            with urlopen(f"{api_base}/health", timeout=0.2) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("Timed out waiting for the widget API")


@pytest.mark.skipif(
    os.getenv("RUN_BROWSER_TESTS") != "1",
    reason="Set RUN_BROWSER_TESTS=1 to run browser rendering tests",
)
def test_widget_renders_from_a_separate_origin(tmp_path: Path) -> None:
    api_port, site_port = unused_port(), unused_port()
    api_base = f"http://127.0.0.1:{api_port}"
    site_origin = f"http://127.0.0.1:{site_port}"
    environment = os.environ | {
        "DATABASE_URL": f"sqlite:///{tmp_path / 'browser-test.db'}",
        "REDIS_URL": "redis://127.0.0.1:1/0",
        "PUBLIC_BASE_URL": api_base,
    }
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    api_process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(api_port),
        ],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    server: ThreadingHTTPServer | None = None
    thread: threading.Thread | None = None
    try:
        wait_for_health(api_base, api_process)
        with httpx.Client(base_url=api_base) as client:
            token = client.post(
                "/api/auth/register",
                json={"email": "browser@example.com", "password": "correct-horse-99"},
            ).json()["access_token"]
            widget = client.post(
                "/api/widgets",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "name": "Browser rendering widget",
                    "widget_type": "signup",
                    "title": "Stay in touch",
                    "button_text": "Join the list",
                    "fields": [
                        {"name": "email", "label": "Email", "type": "email", "required": True}
                    ],
                    "allowed_origins": [site_origin],
                },
            ).json()

        class CustomerPage(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - required stdlib handler name
                body = (
                    "<!doctype html><main><script "
                    f'src="{api_base}/assets/widget.v1.js" data-widget-id="{widget["id"]}" defer>'
                    "</script></main>"
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_: object) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", site_port), CustomerPage)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        with playwright.sync_playwright() as runtime:
            local_chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
            browser = runtime.chromium.launch(
                executable_path=str(local_chrome) if local_chrome.exists() else None
            )
            page = browser.new_page()
            page.goto(site_origin, wait_until="networkidle")
            assert page.get_by_role("heading", name="Stay in touch").is_visible()
            assert page.get_by_label("Email").is_visible()
            assert page.get_by_role("button", name="Join the list").is_visible()
            browser.close()
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=2)
        api_process.terminate()
        api_process.wait(timeout=5)
