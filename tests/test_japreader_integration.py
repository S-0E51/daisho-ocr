#!/usr/bin/env python3
"""Contract and worker tests for direct local japReader integration."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import subprocess
import threading
import time
import sys

from _bootstrap import bootstrap


bootstrap()

from src.integration.japreader_client import (  # noqa: E402
    JapReaderClient,
    JapReaderClientError,
    JapReaderHealth,
    JapReaderIngestResult,
    JapReaderWindowState,
)
from src.integration.japreader_manager import (  # noqa: E402
    POST_CAPTURE_FOCUS,
    POST_CAPTURE_HIDDEN,
    POST_CAPTURE_REVEAL,
    JapReaderManager,
    normalize_post_capture_behavior,
)


TOKEN = "python-test-token-123456789"


class BridgeHandler(BaseHTTPRequestHandler):
    received_text = ""
    received_windows = []
    reader_visible = False
    reader_focused = False

    def do_GET(self) -> None:
        if not self._authorized():
            return
        if self.path != "/v1/health":
            self._json(404, {"ok": False})
            return
        self._json(
            200,
            {
                "ok": True,
                "protocolVersion": 1,
                "appVersion": "test",
                "parserMode": "offline",
                "parserReady": True,
                "parserMessage": "ready",
                "readerVisible": type(self).reader_visible,
                "readerFocused": type(self).reader_focused,
                "capabilities": [
                    "ingest",
                    "focus",
                    "offline-ichiran",
                    "window-control",
                ],
            },
        )

    def do_POST(self) -> None:
        if not self._authorized():
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        if self.path == "/v1/ingest":
            type(self).received_text = payload["text"]
            self._json(
                200,
                {
                    "ok": True,
                    "requestId": payload["requestId"],
                    "captureId": payload["captureId"],
                    "parser": "ichiran",
                    "tokenCount": 3,
                    "stale": False,
                },
            )
            return
        if self.path == "/v1/window/focus":
            self._json(200, {"ok": True, "focused": True})
            return
        if self.path == "/v1/window":
            type(self).received_windows.append(payload)
            type(self).reader_visible = payload["action"] == "show"
            type(self).reader_focused = bool(
                type(self).reader_visible and payload.get("activate", False)
            )
            self._json(
                200,
                {
                    "ok": True,
                    "readerVisible": type(self).reader_visible,
                    "readerFocused": type(self).reader_focused,
                },
            )
            return
        self._json(404, {"ok": False})

    def _authorized(self) -> bool:
        if self.headers.get("Authorization") == f"Bearer {TOKEN}":
            return True
        self._json(
            401,
            {
                "ok": False,
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "bad token",
                    "retryable": False,
                },
            },
        )
        return False

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return


class RunningBridge:
    def __enter__(self) -> int:
        BridgeHandler.received_text = ""
        BridgeHandler.received_windows = []
        BridgeHandler.reader_visible = False
        BridgeHandler.reader_focused = False
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), BridgeHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return int(self.server.server_address[1])

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2.0)


def wait_for(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("Timed out waiting for asynchronous japReader result")


def test_client_contract() -> None:
    with RunningBridge() as port:
        client = JapReaderClient(port, TOKEN)
        health = client.health()
        if not health.parser_ready or health.protocol_version != 1:
            raise AssertionError(f"Unexpected health payload: {health!r}")

        result = client.ingest_text(
            "日本語の文章",
            request_id="request-1",
            capture_id="capture-1",
            focus=True,
        )
        if result.parser != "ichiran" or result.token_count != 3:
            raise AssertionError(f"Unexpected ingest result: {result!r}")
        if BridgeHandler.received_text != "日本語の文章":
            raise AssertionError("Unicode OCR text changed during bridge transport")
        if not client.focus_reader():
            raise AssertionError("Focus endpoint did not report success")

        shown = client.set_reader_window("show", activate=False)
        if not shown.visible or shown.focused:
            raise AssertionError(f"Unexpected inactive reveal state: {shown!r}")
        hidden = client.set_reader_window("hide")
        if hidden.visible or hidden.focused:
            raise AssertionError(f"Unexpected hidden state: {hidden!r}")
        if BridgeHandler.received_windows != [
            {"action": "show", "activate": False},
            {"action": "hide", "activate": False},
        ]:
            raise AssertionError(
                f"Unexpected window payloads: {BridgeHandler.received_windows!r}"
            )

        try:
            JapReaderClient(port, "wrong-token-123456789").health()
        except JapReaderClientError as exc:
            if exc.code != "UNAUTHORIZED":
                raise AssertionError(f"Unexpected auth error: {exc.code}") from exc
        else:
            raise AssertionError("Invalid bridge token was accepted")


def test_post_capture_behavior_normalization() -> None:
    cases = [
        ({"japreader_post_capture_behavior": "reveal"}, POST_CAPTURE_REVEAL),
        ({"japreader_post_capture_behavior": "focus"}, POST_CAPTURE_FOCUS),
        ({"japreader_post_capture_behavior": "hidden"}, POST_CAPTURE_HIDDEN),
        ({"japreader_post_capture_behavior": "invalid"}, POST_CAPTURE_REVEAL),
        ({"japreader_focus_after_ocr": True}, POST_CAPTURE_FOCUS),
        ({"japreader_focus_after_ocr": False}, POST_CAPTURE_HIDDEN),
    ]
    for settings, expected in cases:
        actual = normalize_post_capture_behavior(settings)
        if actual != expected:
            raise AssertionError(
                f"Expected {expected!r} for {settings!r}, got {actual!r}"
            )


def test_manager_post_capture_behaviors() -> None:
    expected_calls = {
        POST_CAPTURE_REVEAL: [("ingest", False), ("window", "show", False)],
        POST_CAPTURE_FOCUS: [("ingest", True)],
        POST_CAPTURE_HIDDEN: [("ingest", False)],
    }

    for behavior, expected in expected_calls.items():
        calls = []
        deliveries = []

        class FakeClient:
            def ingest_text(self, text: str, **kwargs):
                calls.append(("ingest", kwargs["focus"]))
                return JapReaderIngestResult(
                    request_id=kwargs["request_id"],
                    capture_id=kwargs["capture_id"],
                    parser="ichiran",
                    token_count=1,
                    stale=False,
                    fallback=False,
                )

            def set_reader_window(self, action: str, *, activate: bool = False):
                calls.append(("window", action, activate))
                return JapReaderWindowState(visible=True, focused=activate)

        fake_client = FakeClient()
        manager = JapReaderManager(
            {
                "japreader_integration_mode": "direct",
                "japreader_send_on_ocr": True,
                "japreader_clipboard_fallback": False,
                "japreader_post_capture_behavior": behavior,
            },
            delivery_callback=deliveries.append,
        )
        manager._ensure_connected = lambda: fake_client
        manager.start()
        focused_status = None
        try:
            manager.submit_text("behavior text", capture_id=behavior)
            wait_for(lambda: len(deliveries) == 1)
            focused_status = manager.get_status_snapshot()
        finally:
            manager.close()

        if calls != expected:
            raise AssertionError(f"Unexpected {behavior} calls: {calls!r}")
        if not deliveries[0].ok:
            raise AssertionError(f"{behavior} delivery unexpectedly failed")
        if behavior == POST_CAPTURE_FOCUS:
            status = focused_status
            if not status.reader_visible or not status.reader_focused:
                raise AssertionError(
                    f"Focused delivery did not update window status: {status!r}"
                )


def test_manager_reveal_is_best_effort() -> None:
    for stale, fail_window, expected_window_calls in [
        (True, False, 0),
        (False, True, 1),
    ]:
        deliveries = []
        copied = []
        window_calls = []

        class FakeClient:
            def ingest_text(self, text: str, **kwargs):
                return JapReaderIngestResult(
                    request_id=kwargs["request_id"],
                    capture_id=kwargs["capture_id"],
                    parser="ichiran",
                    token_count=1,
                    stale=stale,
                    fallback=False,
                )

            def set_reader_window(self, action: str, *, activate: bool = False):
                window_calls.append((action, activate))
                if fail_window:
                    raise JapReaderClientError(
                        "window unavailable",
                        code="WINDOW_UNAVAILABLE",
                        retryable=True,
                    )
                return JapReaderWindowState(visible=True, focused=False)

        fake_client = FakeClient()
        manager = JapReaderManager(
            {
                "japreader_integration_mode": "direct",
                "japreader_send_on_ocr": True,
                "japreader_clipboard_fallback": True,
                "japreader_post_capture_behavior": POST_CAPTURE_REVEAL,
            },
            delivery_callback=deliveries.append,
            copy_func=lambda text: copied.append(text) is None,
        )
        manager._ensure_connected = lambda: fake_client
        manager.start()
        try:
            manager.submit_text("reveal text", capture_id=f"reveal-{stale}")
            wait_for(lambda: len(deliveries) == 1)
        finally:
            manager.close()

        if len(window_calls) != expected_window_calls:
            raise AssertionError(f"Unexpected reveal attempts: {window_calls!r}")
        if not deliveries[0].ok or copied:
            raise AssertionError(
                "A stale or failed reveal changed the successful parse outcome"
            )


def test_manager_explicit_window_controls() -> None:
    calls = []

    class FakeClient:
        def set_reader_window(self, action: str, *, activate: bool = False):
            calls.append((action, activate))
            visible = action == "show"
            return JapReaderWindowState(
                visible=visible,
                focused=visible and activate,
            )

    fake_client = FakeClient()
    manager = JapReaderManager({"japreader_integration_mode": "direct"})
    manager._ensure_connected = lambda: fake_client
    manager.start()
    try:
        if not manager.show_reader(activate=True) or not manager.hide_reader():
            raise AssertionError("Managed window commands were rejected")
        wait_for(lambda: len(calls) == 2)
    finally:
        manager.close()

    if calls != [("show", True), ("hide", False)]:
        raise AssertionError(f"Window commands were lost or reordered: {calls!r}")

    hide_only_calls = []

    class HideOnlyClient:
        def set_reader_window(self, action: str, *, activate: bool = False):
            hide_only_calls.append((action, activate))
            return JapReaderWindowState(visible=False, focused=False)

    manager = JapReaderManager({"japreader_integration_mode": "direct"})
    manager._ensure_connected = lambda: HideOnlyClient()
    manager.start()
    try:
        manager.hide_reader()
        wait_for(lambda: len(hide_only_calls) == 1)
    finally:
        manager.close()
    if hide_only_calls != [("hide", False)]:
        raise AssertionError(
            f"Stale hidden status suppressed explicit hide: {hide_only_calls!r}"
        )

    manager._apply_health(
        JapReaderHealth(
            app_version="test",
            parser_mode="offline",
            parser_ready=True,
            parser_message="ready",
            capabilities=("window-control",),
            reader_visible=True,
            reader_focused=True,
        )
    )
    status = manager.get_status_snapshot()
    if not status.reader_visible or not status.reader_focused:
        raise AssertionError(f"Health visibility was not propagated: {status!r}")


def test_manager_capability_fallbacks() -> None:
    calls = []
    deliveries = []

    class LegacyWindowClient:
        def ingest_text(self, text: str, **kwargs):
            calls.append(("ingest", kwargs["focus"]))
            return JapReaderIngestResult(
                request_id=kwargs["request_id"],
                capture_id=kwargs["capture_id"],
                parser="ichiran",
                token_count=1,
                stale=False,
                fallback=False,
            )

        def focus_reader(self):
            calls.append(("focus",))
            return True

        def set_reader_window(self, action: str, *, activate: bool = False):
            calls.append(("window", action, activate))
            raise AssertionError("window-control endpoint should not be used")

    manager = JapReaderManager(
        {
            "japreader_integration_mode": "direct",
            "japreader_send_on_ocr": True,
            "japreader_clipboard_fallback": False,
            "japreader_post_capture_behavior": POST_CAPTURE_REVEAL,
        },
        delivery_callback=deliveries.append,
    )
    manager._ensure_connected = lambda: LegacyWindowClient()
    manager._apply_health(
        JapReaderHealth(
            app_version="legacy",
            parser_mode="offline",
            parser_ready=True,
            parser_message="ready",
            capabilities=("ingest", "focus"),
        )
    )
    manager.start()
    focused_status = None
    try:
        manager.submit_text("legacy capabilities", capture_id="legacy-capabilities")
        wait_for(lambda: len(deliveries) == 1)
        manager.show_reader(activate=True)
        wait_for(lambda: manager.get_status_snapshot().reader_focused)
        focused_status = manager.get_status_snapshot()
    finally:
        manager.close()

    if calls != [("ingest", False), ("focus",)]:
        raise AssertionError(f"Capability fallback was not respected: {calls!r}")
    if not focused_status.reader_visible or not focused_status.reader_focused:
        raise AssertionError(
            f"Focus fallback did not update window status: {focused_status!r}"
        )
    status = manager.get_status_snapshot()
    if status.reader_visible or status.reader_focused:
        raise AssertionError("Closing the manager did not clear reader window state")


def test_owned_process_always_stops() -> None:
    class FakeOwnedProcess:
        def __init__(self):
            self.terminated = False
            self.waited = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            self.waited = True
            return 0

    process = FakeOwnedProcess()
    manager = JapReaderManager(
        {
            "japreader_integration_mode": "direct",
            "japreader_stop_on_exit": False,
        }
    )
    manager._process = process
    manager._owns_process = True
    manager.close()

    if not process.terminated or not process.waited:
        raise AssertionError(
            "A managed japReader process survived manager shutdown"
        )


def test_manager_latest_queue_and_delivery() -> None:
    deliveries = []
    window_calls = []
    first_started = threading.Event()
    release_first = threading.Event()

    class FakeClient:
        def ingest_text(self, text: str, **kwargs):
            if text == "first":
                first_started.set()
                release_first.wait(timeout=2.0)
            return JapReaderIngestResult(
                request_id=kwargs["request_id"],
                capture_id=kwargs["capture_id"],
                parser="ichiran",
                token_count=1,
                stale=False,
                fallback=False,
            )

        def set_reader_window(self, action: str, *, activate: bool = False):
            window_calls.append((action, activate))
            return JapReaderWindowState(
                visible=action == "show",
                focused=action == "show" and activate,
            )

    manager = JapReaderManager(
        {
            "japreader_integration_mode": "direct",
            "japreader_send_on_ocr": True,
            "japreader_clipboard_fallback": False,
            "japreader_post_capture_behavior": POST_CAPTURE_HIDDEN,
        },
        delivery_callback=deliveries.append,
    )
    manager._ensure_connected = lambda: FakeClient()
    manager.start()
    try:
        manager.submit_text("first", capture_id="first")
        wait_for(first_started.is_set)
        manager.show_reader(activate=True)
        manager.hide_reader()
        manager.submit_text("second", capture_id="second")
        manager.submit_text("third", capture_id="third")
        release_first.set()
        wait_for(lambda: len(deliveries) == 2)
    finally:
        manager.close()

    capture_ids = [delivery.capture_id for delivery in deliveries]
    if capture_ids != ["first", "third"]:
        raise AssertionError(f"Expected latest queued capture to win, got {capture_ids}")
    if window_calls != [("show", True), ("hide", False)]:
        raise AssertionError(
            f"Window controls were displaced by the OCR queue: {window_calls!r}"
        )


def test_manager_clipboard_fallback() -> None:
    copied = []
    deliveries = []

    class OwnedProcess:
        def __init__(self):
            self.terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

    class FailingClient:
        def ingest_text(self, *args, **kwargs):
            raise JapReaderClientError(
                "bridge down",
                code="BRIDGE_UNAVAILABLE",
                retryable=True,
            )

    manager = JapReaderManager(
        {
            "japreader_integration_mode": "direct",
            "japreader_send_on_ocr": True,
            "japreader_clipboard_fallback": True,
            "japreader_post_capture_behavior": POST_CAPTURE_HIDDEN,
        },
        delivery_callback=deliveries.append,
        copy_func=lambda text: copied.append(text) is None,
    )
    manager._ensure_connected = lambda: FailingClient()
    process = OwnedProcess()
    manager._process = process
    manager._owns_process = True
    manager.start()
    try:
        manager.submit_text("fallback text", capture_id="fallback")
        wait_for(lambda: len(deliveries) == 1)
        if process.terminated:
            raise AssertionError(
                "Clipboard fallback terminated its live japReader observer"
            )
    finally:
        manager.close()

    if copied != ["fallback text"]:
        raise AssertionError(f"Clipboard fallback did not receive text: {copied!r}")
    if not deliveries[0].used_clipboard_fallback:
        raise AssertionError("Fallback delivery was not identified")
    if not process.terminated:
        raise AssertionError("Manager shutdown left an owned japReader process alive")


def test_parser_service_launch_hides_windows_console() -> None:
    launches = []

    class FakeProcess:
        def poll(self):
            return None

    def fake_popen(command, **kwargs):
        launches.append((command, kwargs))
        return FakeProcess()

    manager = JapReaderManager(
        {
            "japreader_ichiran_service_command": "wsl.exe -d Ubuntu -- true",
        },
        popen_factory=fake_popen,
    )
    manager._start_parser_service()

    if len(launches) != 1:
        raise AssertionError(f"Expected one service launch, got {len(launches)}")
    creation_flags = launches[0][1].get("creationflags", 0)
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if no_window and not creation_flags & no_window:
        raise AssertionError("Parser service launch did not hide its Windows console")


def test_managed_launch_exports_ichiran_command_env() -> None:
    launches = []

    class FakeProcess:
        returncode = None

        def poll(self):
            return None

        def terminate(self):
            return None

        def wait(self, timeout=None):
            return 0

        def kill(self):
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            return None

        def health(self, timeout_sec=2.0):
            return JapReaderHealth(
                app_version="test",
                parser_mode="offline",
                parser_ready=True,
                parser_message="ready",
                capabilities=(
                    "ingest",
                    "focus",
                    "offline-ichiran",
                    "window-control",
                ),
                reader_visible=False,
                reader_focused=False,
            )

    def fake_popen(command, **kwargs):
        launches.append((command, kwargs))
        return FakeProcess()

    ichiran_command = "wsl.exe -d Ubuntu -- /usr/local/bin/ichiran-cli-wsl"
    manager = JapReaderManager(
        {
            "japreader_integration_mode": "direct",
            "japreader_ichiran_command": ichiran_command,
            "japreader_parse_timeout_sec": 30.0,
        },
        client_factory=FakeClient,
        popen_factory=fake_popen,
    )
    try:
        manager._ensure_connected()
    finally:
        manager.close()

    if len(launches) != 1:
        raise AssertionError(f"Expected one managed japReader launch, got {len(launches)}")
    command, kwargs = launches[0]
    if f"ichiran-command={ichiran_command}" not in command:
        raise AssertionError(f"Launch args did not include Ichiran command: {command!r}")
    env = kwargs.get("env", {})
    if env.get("JAPREADER_ICHIRAN_COMMAND") != ichiran_command:
        raise AssertionError("Managed launch did not export JAPREADER_ICHIRAN_COMMAND")


def test_delivery_timeout_covers_wsl_recovery() -> None:
    manager = JapReaderManager(
        {
            "japreader_integration_mode": "direct",
            "japreader_parse_timeout_sec": 30.0,
        }
    )
    if manager._delivery_timeout_sec() != 95.0:
        raise AssertionError(
            "Bridge delivery deadline does not cover WSL recovery and retry"
        )


def test_manager_restarts_an_owned_bridge_after_health_loss() -> None:
    launches = []

    class ExitedProcess:
        returncode = 0

        def poll(self):
            return 0

    class FailingClient:
        def health(self, timeout_sec=2.0):
            raise JapReaderClientError(
                "bridge exited",
                code="BRIDGE_UNAVAILABLE",
                retryable=True,
            )

    class HealthyClient:
        def health(self, timeout_sec=2.0):
            return JapReaderHealth(
                app_version="test",
                parser_mode="offline",
                parser_ready=True,
                parser_message="ready",
                capabilities=("ingest", "offline-ichiran"),
                reader_visible=False,
                reader_focused=False,
            )

    manager = JapReaderManager(
        {
            "japreader_integration_mode": "direct",
            "japreader_autolaunch": True,
        }
    )
    manager.HEALTH_POLL_SEC = 0.01

    def ensure_connected():
        launches.append(len(launches) + 1)
        manager._client = FailingClient() if len(launches) == 1 else HealthyClient()
        manager._process = ExitedProcess()
        manager._owns_process = True
        return manager._client

    manager._ensure_connected = ensure_connected
    manager.start()
    try:
        wait_for(lambda: len(launches) >= 2, timeout=3.0)
    finally:
        manager.close()

    if len(launches) < 2:
        raise AssertionError("Owned japReader was not restarted after health loss")


def test_transient_health_failure_does_not_restart_a_live_bridge() -> None:
    launches = []
    health_timeouts = []

    class LiveProcess:
        def __init__(self):
            self.terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

    class FlakyClient:
        def __init__(self):
            self.calls = 0

        def health(self, timeout_sec=2.0):
            self.calls += 1
            health_timeouts.append(timeout_sec)
            if self.calls == 1:
                raise JapReaderClientError(
                    "slow health response",
                    code="BRIDGE_TIMEOUT",
                    retryable=True,
                )
            return JapReaderHealth(
                app_version="test",
                parser_mode="offline",
                parser_ready=True,
                parser_message="ready",
                capabilities=("ingest", "offline-ichiran"),
                reader_visible=False,
                reader_focused=False,
            )

    process = LiveProcess()
    client = FlakyClient()
    manager = JapReaderManager(
        {
            "japreader_integration_mode": "direct",
            "japreader_autolaunch": True,
        }
    )
    manager.HEALTH_POLL_SEC = 0.01

    def ensure_connected():
        launches.append(1)
        manager._client = client
        manager._process = process
        manager._owns_process = True
        return client

    manager._ensure_connected = ensure_connected
    manager.start()
    try:
        wait_for(lambda: client.calls >= 2, timeout=3.0)
        if len(launches) != 1 or process.terminated:
            raise AssertionError(
                "A single transient health failure restarted the live bridge"
            )
        if health_timeouts[0] != manager.HEALTH_TIMEOUT_SEC:
            raise AssertionError("Periodic health did not use its extended timeout")
    finally:
        manager.close()


def main() -> int:
    print("=" * 70)
    print("japReader Integration Test")
    print("=" * 70)
    test_client_contract()
    test_post_capture_behavior_normalization()
    test_manager_post_capture_behaviors()
    test_manager_reveal_is_best_effort()
    test_manager_explicit_window_controls()
    test_manager_capability_fallbacks()
    test_owned_process_always_stops()
    test_manager_latest_queue_and_delivery()
    test_manager_clipboard_fallback()
    test_parser_service_launch_hides_windows_console()
    test_managed_launch_exports_ichiran_command_env()
    test_delivery_timeout_covers_wsl_recovery()
    test_manager_restarts_an_owned_bridge_after_health_loss()
    test_transient_health_failure_does_not_restart_a_live_bridge()
    print("[OK] japReader client and manager behavior passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
