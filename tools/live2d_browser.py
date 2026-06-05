from __future__ import annotations

import argparse
import contextlib
import functools
import http.server
import os
import shutil
import socket
import socketserver
import threading
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from playwright.sync_api import Browser, Page, sync_playwright


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VIEWER_PATH = "/assets/assetbundles/actor2d/live2d_test.html"
DEFAULT_SCREENSHOT_PATH = Path("assets/assetbundles/actor2d/live2d_test.png")


@dataclass
class ServerInfo:
    root: Path
    host: str
    port: int

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"


class QuietRequestHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


class ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def _parse_viewport(value: str) -> tuple[int, int]:
    width, separator, height = value.lower().partition("x")
    if not separator:
        raise argparse.ArgumentTypeError("Viewport must use WIDTHxHEIGHT format")
    try:
        parsed_width = int(width)
        parsed_height = int(height)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Viewport width and height must be integers") from error
    if parsed_width <= 0 or parsed_height <= 0:
        raise argparse.ArgumentTypeError("Viewport width and height must be positive")
    return parsed_width, parsed_height


def _find_free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


@contextlib.contextmanager
def _static_server(root: Path, host: str, port: int) -> Iterator[ServerInfo]:
    actual_port = port if port else _find_free_port(host)
    handler = functools.partial(QuietRequestHandler, directory=str(root))
    server = ThreadingTCPServer((host, actual_port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        yield ServerInfo(root=root, host=host, port=actual_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _chrome_executable() -> str | None:
    candidates = (
        os.environ.get("CHROME_BIN"),
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
    )
    return next((candidate for candidate in candidates if candidate), None)


def _launch_browser(headed: bool) -> Browser:
    playwright = sync_playwright().start()
    executable_path = _chrome_executable()
    if executable_path is None:
        browser = playwright.chromium.launch(headless=not headed)
    else:
        browser = playwright.chromium.launch(
            executable_path=executable_path,
            headless=not headed,
        )
    setattr(browser, "_playwright", playwright)
    return browser


def _close_browser(browser: Browser) -> None:
    playwright = getattr(browser, "_playwright")
    browser.close()
    playwright.stop()


def _select_matching_option(page: Page, selector: str, requested: str, label: str) -> str:
    options = page.locator(f"{selector} option").evaluate_all(
        """(nodes) => nodes.map((node) => ({
            value: node.value,
            label: node.label || node.textContent || "",
            text: node.textContent || ""
        }))"""
    )
    if not options:
        raise RuntimeError(f"No options are available for {label}")

    requested_folded = requested.casefold()
    exact_match = next(
        (
            option
            for option in options
            if option["value"] == requested
            or option["label"] == requested
            or option["text"] == requested
        ),
        None,
    )
    substring_match = next(
        (
            option
            for option in options
            if requested_folded in option["value"].casefold()
            or requested_folded in option["label"].casefold()
            or requested_folded in option["text"].casefold()
        ),
        None,
    )
    match = exact_match or substring_match
    if match is None:
        available = ", ".join(option["label"] or option["value"] for option in options[:12])
        raise RuntimeError(f"Could not find {label} option {requested!r}. Available: {available}")

    page.select_option(selector, value=match["value"])
    return str(match["label"] or match["value"])


def _set_scale(page: Page, scale: float) -> None:
    page.locator("#scaleInput").evaluate(
        """(node, value) => {
            node.value = String(value);
            node.dispatchEvent(new Event("input", { bubbles: true }));
        }""",
        scale,
    )


def _wait_until_loaded(page: Page, timeout_ms: int) -> None:
    page.wait_for_function(
        """() => {
            const status = document.querySelector("#status");
            return status && status.textContent.startsWith("Loaded ");
        }""",
        timeout=timeout_ms,
    )


def _take_live2d_screenshot(
    page: Page,
    output: Path,
    model: str | None,
    phase: str | None,
    scale: float | None,
    hide_ui: bool,
    full_page: bool,
    timeout_ms: int,
    settle_ms: int,
) -> None:
    page.wait_for_selector("#modelSelect option", state="attached", timeout=timeout_ms)
    _wait_until_loaded(page, timeout_ms)

    if model:
        selected_model = _select_matching_option(page, "#modelSelect", model, "model")
        _wait_until_loaded(page, timeout_ms)
        print(f"Selected model: {selected_model}")

    if phase:
        selected_phase = _select_matching_option(page, "#phaseSelect", phase, "phase")
        print(f"Selected phase: {selected_phase}")

    if scale is not None:
        _set_scale(page, scale)
        print(f"Set scale: {scale}")

    if hide_ui:
        page.add_style_tag(content="#controls, #status { display: none !important; }")

    page.wait_for_timeout(settle_ms)
    output.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(output), full_page=full_page)


def _viewer_url(base_url: str, viewer_path: str) -> str:
    return f"{base_url.rstrip('/')}/{viewer_path.lstrip('/')}"


def _with_query_param(url: str, name: str, value: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query.append((name, value))
    return urllib.parse.urlunsplit(
        parsed._replace(query=urllib.parse.urlencode(query)),
    )


def _run(args: argparse.Namespace) -> None:
    width, height = args.viewport
    server_context: contextlib.AbstractContextManager[ServerInfo | None]
    if args.url:
        server_context = contextlib.nullcontext(None)
    else:
        server_context = _static_server(args.root, args.host, args.port)

    with server_context as server:
        url = args.url or _viewer_url(server.url, args.viewer_path)
        if args.mouse_tracking:
            url = _with_query_param(url, "mouseTracking", "1")
        if args.render_resolution:
            url = _with_query_param(url, "renderResolution", args.render_resolution)
        print(f"Opening {url}")

        browser = _launch_browser(args.headed)
        try:
            context = browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=args.device_scale_factor,
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=args.timeout)

            _take_live2d_screenshot(
                page=page,
                output=args.output,
                model=args.model,
                phase=args.phase,
                scale=args.scale,
                hide_ui=args.hide_ui,
                full_page=args.full_page,
                timeout_ms=args.timeout,
                settle_ms=args.settle,
            )
            print(f"Wrote screenshot: {args.output}")

            if args.headed and args.pause:
                print("Browser is paused. Press Ctrl+C here to stop it.")
                while True:
                    time.sleep(1)
        finally:
            _close_browser(browser)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Drive the Live2D browser test page and capture screenshots.",
    )
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="Static server root")
    parser.add_argument("--host", default="127.0.0.1", help="Static server host")
    parser.add_argument("--port", type=int, default=0, help="Static server port, or 0 for any free port")
    parser.add_argument("--url", help="Use an already-running viewer URL instead of starting a server")
    parser.add_argument("--viewer-path", default=DEFAULT_VIEWER_PATH, help="Viewer HTML path under the static root")
    parser.add_argument("--output", type=Path, default=DEFAULT_SCREENSHOT_PATH, help="Screenshot output path")
    parser.add_argument("--model", help="Model option value, exact label, or label/path substring")
    parser.add_argument("--phase", help="Phase option value, exact label, or label substring, for example '3+' or 'idle_2'")
    parser.add_argument("--scale", type=float, help="Viewer scale slider value")
    parser.add_argument("--render-resolution", help="Viewer render resolution: device, 1, 1.5, 2, 3, or 4")
    parser.add_argument("--mouse-tracking", action="store_true", help="Enable Live2D mouse focus tracking")
    parser.add_argument("--viewport", type=_parse_viewport, default=(1920, 1080), help="Viewport size, e.g. 1920x1080")
    parser.add_argument("--device-scale-factor", type=float, default=1, help="Browser device scale factor")
    parser.add_argument("--timeout", type=int, default=60000, help="Navigation and selector timeout in milliseconds")
    parser.add_argument("--settle", type=int, default=1000, help="Milliseconds to wait before screenshot")
    parser.add_argument("--hide-ui", action="store_true", help="Hide viewer controls and status before taking the screenshot")
    parser.add_argument("--full-page", action="store_true", help="Capture the full page instead of only the viewport")
    parser.add_argument("--headed", action="store_true", help="Show the browser window")
    parser.add_argument("--pause", action="store_true", help="Keep a headed browser open after taking the screenshot")
    args = parser.parse_args()

    _run(args)


if __name__ == "__main__":
    main()
