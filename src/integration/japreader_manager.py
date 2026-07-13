"""Managed lifecycle and asynchronous delivery for local japReader."""

from __future__ import annotations

from dataclasses import dataclass, replace
import os
import queue
import secrets
import shlex
import socket
import subprocess
import threading
import time
import uuid
from typing import Callable, Mapping, Optional

from .clipboard import copy_text
from .japreader import (
    detect_japreader,
    detect_managed_japreader,
    focus_japreader,
    launch_japreader,
)
from .japreader_client import (
    JapReaderClient,
    JapReaderClientError,
    JapReaderHealth,
    JapReaderWindowState,
)
from ..utils.logger import log_debug, log_error, log_info, log_warning


INTEGRATION_DIRECT = "direct"
INTEGRATION_LEGACY = "legacy"
INTEGRATION_DISABLED = "disabled"
VALID_INTEGRATION_MODES = {
    INTEGRATION_DIRECT,
    INTEGRATION_LEGACY,
    INTEGRATION_DISABLED,
}

POST_CAPTURE_REVEAL = "reveal"
POST_CAPTURE_FOCUS = "focus"
POST_CAPTURE_HIDDEN = "hidden"
VALID_POST_CAPTURE_BEHAVIORS = {
    POST_CAPTURE_REVEAL,
    POST_CAPTURE_FOCUS,
    POST_CAPTURE_HIDDEN,
}


def normalize_post_capture_behavior(settings: Mapping[str, object]) -> str:
    """Resolve the new presentation setting while honoring legacy configs."""
    raw_behavior = settings.get("japreader_post_capture_behavior")
    if raw_behavior is not None:
        behavior = str(raw_behavior).strip().lower()
        return (
            behavior
            if behavior in VALID_POST_CAPTURE_BEHAVIORS
            else POST_CAPTURE_REVEAL
        )

    legacy_focus = settings.get("japreader_focus_after_ocr", False)
    if isinstance(legacy_focus, str):
        focus_enabled = legacy_focus.strip().lower() in {"1", "true", "yes", "on"}
    else:
        focus_enabled = bool(legacy_focus)
    return POST_CAPTURE_FOCUS if focus_enabled else POST_CAPTURE_HIDDEN


@dataclass(frozen=True)
class JapReaderStatus:
    state: str
    message: str
    connected: bool = False
    parser_ready: bool = False
    parser_mode: str = ""
    app_version: str = ""
    reader_visible: bool = False
    reader_focused: bool = False


@dataclass(frozen=True)
class JapReaderDelivery:
    capture_id: str
    ok: bool
    message: str
    parser: str = ""
    token_count: int = 0
    stale: bool = False
    used_clipboard_fallback: bool = False


@dataclass(frozen=True)
class _PendingText:
    text: str
    capture_id: str
    presentation: str


@dataclass(frozen=True)
class _WindowCommand:
    action: str
    activate: bool = False


class JapReaderManager:
    """Own one background worker and, when needed, one japReader process."""

    STARTUP_TIMEOUT_SEC = 15.0
    STARTUP_POLL_SEC = 0.25
    HEALTH_POLL_SEC = 3.0
    HEALTH_TIMEOUT_SEC = 6.5
    HEALTH_FAILURE_RESTART_THRESHOLD = 3
    WSL_RECOVERY_OVERHEAD_SEC = 65.0
    STOP_SENTINEL = object()

    def __init__(
        self,
        settings: Mapping[str, object],
        *,
        status_callback: Optional[Callable[[JapReaderStatus], None]] = None,
        delivery_callback: Optional[Callable[[JapReaderDelivery], None]] = None,
        client_factory: Callable[..., JapReaderClient] = JapReaderClient,
        popen_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
        copy_func: Callable[[str], bool] = copy_text,
    ) -> None:
        self._settings = dict(settings)
        self._status_callback = status_callback
        self._delivery_callback = delivery_callback
        self._client_factory = client_factory
        self._popen_factory = popen_factory
        self._copy_func = copy_func

        self._queue: queue.Queue[object] = queue.Queue(maxsize=1)
        self._control_queue: queue.Queue[_WindowCommand] = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._client: Optional[JapReaderClient] = None
        self._bridge_capabilities: Optional[frozenset[str]] = None
        self._process: Optional[subprocess.Popen] = None
        self._service_process: Optional[subprocess.Popen] = None
        self._owns_process = False
        self._session_port = 0
        self._session_token = ""
        self._state_lock = threading.Lock()
        self._status = JapReaderStatus("stopped", "japReader integration stopped")

    @property
    def mode(self) -> str:
        value = str(self._settings.get("japreader_integration_mode", INTEGRATION_DIRECT))
        return value if value in VALID_INTEGRATION_MODES else INTEGRATION_DIRECT

    def start(self) -> None:
        if self.mode == INTEGRATION_DISABLED:
            self._set_status(
                JapReaderStatus("disabled", "japReader integration disabled")
            )
            return
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._queue = queue.Queue(maxsize=1)
        self._control_queue = queue.Queue()
        self._thread = threading.Thread(
            target=self._worker_loop,
            name="japreader-bridge",
            daemon=True,
        )
        self._thread.start()

    def update_settings(self, settings: Mapping[str, object]) -> None:
        self.close()
        self._settings = dict(settings)
        self._client = None
        self._process = None
        self._service_process = None
        self._owns_process = False
        self._session_port = 0
        self._session_token = ""
        self.start()

    def submit_text(
        self,
        text: str,
        *,
        capture_id: Optional[str] = None,
        focus: Optional[bool] = None,
    ) -> bool:
        if self.mode == INTEGRATION_DISABLED:
            return False
        if not bool(self._settings.get("japreader_send_on_ocr", True)):
            return False

        normalized = text.strip() if isinstance(text, str) else ""
        if not normalized:
            return False

        self.start()
        pending = _PendingText(
            text=normalized,
            capture_id=capture_id or str(uuid.uuid4()),
            presentation=(
                normalize_post_capture_behavior(self._settings)
                if focus is None
                else (POST_CAPTURE_FOCUS if focus else POST_CAPTURE_HIDDEN)
            ),
        )
        try:
            self._queue.put_nowait(pending)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            self._queue.put_nowait(pending)
            log_debug("Replaced queued japReader delivery with latest OCR result")
        return True

    def show_reader(self, *, activate: bool = True) -> bool:
        return self._queue_window_command("show", activate=activate)

    def hide_reader(self) -> bool:
        return self._queue_window_command("hide", activate=False)

    def _queue_window_command(self, action: str, *, activate: bool) -> bool:
        if self.mode != INTEGRATION_DIRECT:
            return False
        self.start()
        if self._stop_event.is_set():
            return False
        self._control_queue.put(
            _WindowCommand(action=action, activate=bool(activate))
        )
        return True

    def get_status_snapshot(self) -> JapReaderStatus:
        with self._state_lock:
            return self._status

    def close(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            try:
                self._queue.put_nowait(self.STOP_SENTINEL)
            except queue.Full:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._queue.put_nowait(self.STOP_SENTINEL)
                except queue.Full:
                    pass
            thread.join(timeout=3.0)
        self._thread = None
        self._client = None
        self._bridge_capabilities = None

        if (
            self._owns_process
            and self._process is not None
            and self._process.poll() is None
        ):
            try:
                self._process.terminate()
                self._process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                self._process.kill()
            except Exception as exc:
                log_warning(f"Failed to stop managed japReader: {exc}")
        self._process = None
        self._owns_process = False
        self._stop_parser_service()
        self._set_status(JapReaderStatus("stopped", "japReader integration stopped"))

    def _worker_loop(self) -> None:
        try:
            next_health_check = time.monotonic() + self.HEALTH_POLL_SEC
            consecutive_health_failures = 0
            autolaunch = bool(self._settings.get("japreader_autolaunch", False))
            if self.mode == INTEGRATION_DIRECT:
                # Warm up the offline Ichiran backend (Postgres keepalive) as
                # early as possible so the first capture is not slow or cold.
                self._start_parser_service()
                if autolaunch:
                    self._ensure_connected()
            elif self.mode == INTEGRATION_LEGACY and autolaunch:
                self._launch_legacy()

            while not self._stop_event.is_set():
                try:
                    command = self._control_queue.get_nowait()
                except queue.Empty:
                    command = None
                if command is not None:
                    self._handle_window_command(command)
                    continue

                try:
                    item = self._queue.get(timeout=0.5)
                except queue.Empty:
                    if (
                        self.mode == INTEGRATION_DIRECT
                        and self._client is not None
                        and time.monotonic() >= next_health_check
                    ):
                        next_health_check = time.monotonic() + self.HEALTH_POLL_SEC
                        if (
                            self._service_process is None
                            or self._service_process.poll() is not None
                        ):
                            self._start_parser_service()
                        try:
                            self._apply_health(
                                self._client.health(
                                    timeout_sec=self.HEALTH_TIMEOUT_SEC
                                )
                            )
                            consecutive_health_failures = 0
                        except JapReaderClientError as exc:
                            log_debug(f"japReader health refresh failed: {exc}")
                            consecutive_health_failures += 1
                            process_exited = bool(
                                self._owns_process
                                and self._process is not None
                                and self._process.poll() is not None
                            )
                            restart_unhealthy = (
                                consecutive_health_failures
                                >= self.HEALTH_FAILURE_RESTART_THRESHOLD
                            )
                            if process_exited or restart_unhealthy:
                                should_reconnect = autolaunch or self._owns_process
                                self._client = None
                                self._bridge_capabilities = None
                                self._discard_owned_process()
                                consecutive_health_failures = 0
                            else:
                                should_reconnect = False
                            if should_reconnect and not self._stop_event.is_set():
                                try:
                                    self._ensure_connected()
                                except JapReaderClientError as restart_exc:
                                    self._set_status(
                                        JapReaderStatus("error", str(restart_exc))
                                    )
                    continue
                if item is self.STOP_SENTINEL:
                    return
                if isinstance(item, _PendingText):
                    self._deliver(item)
        except Exception as exc:
            log_error(f"japReader worker failed: {exc}")
            self._set_status(JapReaderStatus("error", str(exc)))

    def _deliver(self, pending: _PendingText) -> None:
        if self.mode == INTEGRATION_LEGACY:
            self._deliver_legacy(pending)
            return

        client: JapReaderClient | None = None
        try:
            client = self._ensure_connected()
            focus_via_ingest = (
                pending.presentation == POST_CAPTURE_FOCUS
                and self._supports_capability("focus")
            )
            result = client.ingest_text(
                pending.text,
                request_id=str(uuid.uuid4()),
                capture_id=pending.capture_id,
                focus=focus_via_ingest,
                timeout_sec=self._delivery_timeout_sec(),
            )
            if not result.stale:
                if focus_via_ingest:
                    self._apply_window_state(
                        JapReaderWindowState(visible=True, focused=True)
                    )
                elif (
                    pending.presentation == POST_CAPTURE_FOCUS
                    and self._supports_capability("window-control")
                ):
                    try:
                        window_state = client.set_reader_window(
                            "show",
                            activate=True,
                        )
                        self._apply_window_state(window_state)
                    except Exception as exc:
                        log_warning(
                            "japReader parsed the capture but could not focus its "
                            f"window: {exc}"
                        )
                elif (
                    pending.presentation == POST_CAPTURE_REVEAL
                    and self._supports_capability("window-control")
                ):
                    try:
                        window_state = client.set_reader_window(
                            "show",
                            activate=False,
                        )
                        self._apply_window_state(window_state)
                    except Exception as exc:
                        log_warning(
                            "japReader parsed the capture but could not reveal its "
                            f"window: {exc}"
                        )
            message = (
                "Older japReader result discarded"
                if result.stale
                else f"Parsed in japReader with {result.parser}"
            )
            self._emit_delivery(
                JapReaderDelivery(
                    capture_id=pending.capture_id,
                    ok=True,
                    message=message,
                    parser=result.parser,
                    token_count=result.token_count,
                    stale=result.stale,
                )
            )
        except JapReaderClientError as exc:
            log_warning(f"Direct japReader delivery failed ({exc.code}): {exc}")
            fallback_enabled = self._clipboard_fallback_enabled()
            live_owned_bridge = bool(
                fallback_enabled
                and client is not None
                and self._owns_process
                and self._process is not None
                and self._process.poll() is None
            )
            if live_owned_bridge:
                # Keep the clipboard observer alive for this fallback. The next
                # health check or delivery will reconnect it if the bridge failed.
                self._client = client
            else:
                self._client = None
                self._bridge_capabilities = None
                self._discard_owned_process()
            if fallback_enabled:
                self._deliver_clipboard_fallback(pending, str(exc))
                return
            self._set_status(JapReaderStatus("error", str(exc)))
            self._emit_delivery(
                JapReaderDelivery(
                    capture_id=pending.capture_id,
                    ok=False,
                    message=str(exc),
                )
            )

    def _deliver_legacy(self, pending: _PendingText) -> None:
        if self._copy_func(pending.text):
            if pending.presentation == POST_CAPTURE_FOCUS:
                focus_japreader()
            self._emit_delivery(
                JapReaderDelivery(
                    capture_id=pending.capture_id,
                    ok=True,
                    message="Sent to japReader through clipboard compatibility mode",
                    used_clipboard_fallback=True,
                )
            )
        else:
            self._emit_delivery(
                JapReaderDelivery(
                    capture_id=pending.capture_id,
                    ok=False,
                    message="Could not copy OCR text for legacy japReader delivery",
                )
            )

    def _deliver_clipboard_fallback(
        self, pending: _PendingText, direct_error: str
    ) -> None:
        copied = self._copy_func(pending.text)
        if copied and pending.presentation == POST_CAPTURE_FOCUS:
            focus_japreader()
        message = (
            f"Direct japReader unavailable; used clipboard fallback ({direct_error})"
            if copied
            else f"Direct japReader unavailable and clipboard fallback failed ({direct_error})"
        )
        self._set_status(
            JapReaderStatus(
                "fallback" if copied else "error",
                message,
                connected=False,
            )
        )
        self._emit_delivery(
            JapReaderDelivery(
                capture_id=pending.capture_id,
                ok=copied,
                message=message,
                used_clipboard_fallback=copied,
            )
        )

    def _ensure_connected(self) -> JapReaderClient:
        if self._client is not None:
            try:
                health = self._client.health()
                self._apply_health(health)
                return self._client
            except JapReaderClientError:
                self._client = None
                self._bridge_capabilities = None
                self._discard_owned_process()

        executable = detect_managed_japreader(
            str(self._settings.get("japreader_path", ""))
        )
        if not executable:
            raise JapReaderClientError(
                "Local japReader executable was not found",
                code="EXECUTABLE_NOT_FOUND",
                retryable=False,
            )

        self._set_status(JapReaderStatus("starting", "Starting local japReader"))
        self._start_parser_service()
        self._session_port = self._reserve_loopback_port()
        self._session_token = secrets.token_urlsafe(32)
        command = [
            executable,
            f"bridge-port={self._session_port}",
            f"bridge-token={self._session_token}",
            "parser-mode=offline",
        ]
        ichiran_command = str(
            self._settings.get("japreader_ichiran_command", "")
        ).strip()
        if ichiran_command:
            command.append(f"ichiran-command={ichiran_command}")
        command.append(
            f"ichiran-timeout-ms={int(self._parse_timeout_sec() * 1000)}"
        )
        popen_kwargs: dict[str, object] = {
            "cwd": os.path.dirname(executable),
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        child_env = os.environ.copy()
        child_env.pop("ELECTRON_RUN_AS_NODE", None)
        if ichiran_command:
            child_env["JAPREADER_ICHIRAN_COMMAND"] = ichiran_command
        popen_kwargs["env"] = child_env
        creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        if creation_flags:
            popen_kwargs["creationflags"] = creation_flags

        try:
            self._process = self._popen_factory(command, **popen_kwargs)
        except Exception as exc:
            raise JapReaderClientError(
                f"Unable to launch local japReader: {exc}",
                code="LAUNCH_FAILED",
                retryable=True,
            ) from exc
        self._owns_process = True

        client = self._client_factory(
            self._session_port,
            self._session_token,
            timeout_sec=2.0,
        )
        deadline = time.monotonic() + self.STARTUP_TIMEOUT_SEC
        last_error = "Bridge did not become ready"
        while time.monotonic() < deadline and not self._stop_event.is_set():
            if self._process.poll() is not None:
                last_error = f"japReader exited with code {self._process.returncode}"
                break
            try:
                health = client.health(timeout_sec=1.0)
                self._client = client
                self._apply_health(health)
                return client
            except JapReaderClientError as exc:
                last_error = str(exc)
                time.sleep(self.STARTUP_POLL_SEC)

        self._discard_owned_process()
        raise JapReaderClientError(
            f"japReader bridge startup timed out: {last_error}",
            code="STARTUP_TIMEOUT",
            retryable=True,
        )

    def _apply_health(self, health: JapReaderHealth) -> None:
        self._bridge_capabilities = frozenset(health.capabilities)
        if health.parser_ready:
            status = JapReaderStatus(
                "connected",
                "Local japReader and offline Ichiran are ready",
                connected=True,
                parser_ready=True,
                parser_mode=health.parser_mode,
                app_version=health.app_version,
                reader_visible=health.reader_visible,
                reader_focused=health.reader_focused,
            )
        else:
            status = JapReaderStatus(
                "parser_unavailable",
                health.parser_message or "Offline Ichiran is unavailable",
                connected=True,
                parser_ready=False,
                parser_mode=health.parser_mode,
                app_version=health.app_version,
                reader_visible=health.reader_visible,
                reader_focused=health.reader_focused,
            )
        self._set_status(status)

    def _handle_window_command(self, command: _WindowCommand) -> None:
        try:
            client = self._ensure_connected()
            if self._supports_capability("window-control"):
                window_state = client.set_reader_window(
                    command.action,
                    activate=command.activate,
                )
            elif (
                command.action == "show"
                and command.activate
                and self._supports_capability("focus")
            ):
                focused = client.focus_reader()
                if not focused:
                    raise JapReaderClientError(
                        "japReader did not focus its reader window",
                        code="WINDOW_FOCUS_FAILED",
                        retryable=True,
                    )
                window_state = JapReaderWindowState(visible=True, focused=True)
            else:
                raise JapReaderClientError(
                    "This japReader bridge does not support the requested "
                    "window control",
                    code="WINDOW_CONTROL_UNSUPPORTED",
                    retryable=False,
                )
            self._apply_window_state(window_state)
        except JapReaderClientError as exc:
            message = f"Could not {command.action} japReader: {exc}"
            log_warning(message)
            self._set_status(
                replace(
                    self.get_status_snapshot(),
                    state="error",
                    message=message,
                )
            )

    def _apply_window_state(self, window_state: JapReaderWindowState) -> None:
        current = self.get_status_snapshot()
        self._set_status(
            replace(
                current,
                reader_visible=window_state.visible,
                reader_focused=window_state.focused,
            )
        )

    def _supports_capability(self, capability: str) -> bool:
        capabilities = self._bridge_capabilities
        return capabilities is None or capability in capabilities

    def _launch_legacy(self) -> None:
        path = detect_japreader(str(self._settings.get("japreader_path", "")))
        if path and launch_japreader(path):
            self._set_status(JapReaderStatus("legacy", "Legacy japReader launched"))
        else:
            self._set_status(
                JapReaderStatus("error", "Legacy japReader executable was not found")
            )

    def _clipboard_fallback_enabled(self) -> bool:
        return bool(self._settings.get("japreader_clipboard_fallback", True))

    def _parse_timeout_sec(self) -> float:
        value = self._settings.get("japreader_parse_timeout_sec", 12.0)
        try:
            return min(60.0, max(2.0, float(value)))
        except (TypeError, ValueError):
            return 12.0

    def _delivery_timeout_sec(self) -> float:
        return min(
            130.0,
            self._parse_timeout_sec() + self.WSL_RECOVERY_OVERHEAD_SEC,
        )

    def _set_status(self, status: JapReaderStatus) -> None:
        with self._state_lock:
            self._status = status
        if self._status_callback is not None:
            try:
                self._status_callback(status)
            except Exception as exc:
                log_debug(f"japReader status callback failed: {exc}")
        if status.state not in {"stopped", "disabled"}:
            log_info(f"japReader status: {status.state} - {status.message}")

    def _emit_delivery(self, delivery: JapReaderDelivery) -> None:
        if self._delivery_callback is None:
            return
        try:
            self._delivery_callback(delivery)
        except Exception as exc:
            log_debug(f"japReader delivery callback failed: {exc}")

    def _discard_owned_process(self) -> None:
        process = self._process
        if not self._owns_process or process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.kill()
        except Exception as exc:
            log_debug(f"Failed to discard unhealthy japReader process: {exc}")
        finally:
            self._process = None
            self._owns_process = False
            self._bridge_capabilities = None

    def _start_parser_service(self) -> bool:
        if self._service_process is not None and self._service_process.poll() is None:
            return True
        command_line = str(
            self._settings.get("japreader_ichiran_service_command", "")
        ).strip()
        if not command_line:
            return False
        try:
            command = shlex.split(command_line, posix=False)
            if not command:
                return False
            child_env = os.environ.copy()
            child_env.pop("ELECTRON_RUN_AS_NODE", None)
            popen_kwargs: dict[str, object] = {
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "env": child_env,
            }
            creation_flags = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
            if creation_flags:
                popen_kwargs["creationflags"] = creation_flags
            self._service_process = self._popen_factory(command, **popen_kwargs)
            log_info("Started offline Ichiran service (PostgreSQL keepalive)")
            return True
        except Exception as exc:
            log_warning(f"Unable to start Ichiran service command: {exc}")
            self._service_process = None
            # Surface the failure so Settings > Integrations shows it, unless we
            # already have a live japReader connection reporting real health.
            if not self.get_status_snapshot().connected:
                self._set_status(
                    JapReaderStatus(
                        "parser_unavailable",
                        f"Could not start offline Ichiran service: {exc}",
                        connected=False,
                    )
                )
            return False

    def _stop_parser_service(self) -> None:
        process = self._service_process
        self._service_process = None
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.kill()
        except Exception as exc:
            log_debug(f"Failed to stop Ichiran service process: {exc}")

    @staticmethod
    def _reserve_loopback_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])
