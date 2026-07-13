"""Typed client for the local japReader loopback bridge."""

from __future__ import annotations

from dataclasses import dataclass
import json
import socket
from typing import Any, Optional
from urllib import error, request


PROTOCOL_VERSION = 1


class JapReaderClientError(RuntimeError):
    """Normalized bridge transport or application error."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "BRIDGE_ERROR",
        retryable: bool = False,
        status_code: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code


@dataclass(frozen=True)
class JapReaderHealth:
    app_version: str
    parser_mode: str
    parser_ready: bool
    parser_message: str
    capabilities: tuple[str, ...]
    protocol_version: int = PROTOCOL_VERSION
    reader_visible: bool = False
    reader_focused: bool = False


@dataclass(frozen=True)
class JapReaderIngestResult:
    request_id: str
    capture_id: str
    parser: str
    token_count: int
    stale: bool
    fallback: bool


@dataclass(frozen=True)
class JapReaderWindowState:
    visible: bool
    focused: bool


class JapReaderClient:
    """Small JSON-over-HTTP client bound to one managed japReader session."""

    def __init__(
        self,
        port: int,
        token: str,
        *,
        host: str = "127.0.0.1",
        timeout_sec: float = 3.0,
    ) -> None:
        self._base_url = f"http://{host}:{int(port)}"
        self._token = token
        self._timeout_sec = max(0.2, float(timeout_sec))

    def health(self, timeout_sec: float = 2.0) -> JapReaderHealth:
        payload = self._request("GET", "/v1/health", timeout_sec=timeout_sec)
        protocol_version = int(payload.get("protocolVersion", 0))
        if protocol_version != PROTOCOL_VERSION:
            raise JapReaderClientError(
                f"Unsupported japReader bridge protocol {protocol_version}",
                code="PROTOCOL_MISMATCH",
                retryable=False,
            )
        return JapReaderHealth(
            app_version=str(payload.get("appVersion", "")),
            parser_mode=str(payload.get("parserMode", "")),
            parser_ready=bool(payload.get("parserReady", False)),
            parser_message=str(payload.get("parserMessage", "")),
            capabilities=tuple(
                str(value) for value in payload.get("capabilities", [])
            ),
            protocol_version=protocol_version,
            reader_visible=bool(payload.get("readerVisible", False)),
            reader_focused=bool(payload.get("readerFocused", False)),
        )

    def ingest_text(
        self,
        text: str,
        *,
        request_id: str,
        capture_id: str,
        focus: bool,
        timeout_sec: float = 12.0,
    ) -> JapReaderIngestResult:
        payload = self._request(
            "POST",
            "/v1/ingest",
            {
                "requestId": request_id,
                "captureId": capture_id,
                "text": text,
                "source": "ocr",
                "focus": bool(focus),
                "parserMode": "offline",
            },
            timeout_sec=timeout_sec,
        )
        return JapReaderIngestResult(
            request_id=str(payload.get("requestId", request_id)),
            capture_id=str(payload.get("captureId", capture_id)),
            parser=str(payload.get("parser", "")),
            token_count=max(0, int(payload.get("tokenCount", 0))),
            stale=bool(payload.get("stale", False)),
            fallback=bool(payload.get("fallback", False)),
        )

    def focus_reader(self, timeout_sec: float = 2.0) -> bool:
        payload = self._request(
            "POST",
            "/v1/window/focus",
            {},
            timeout_sec=timeout_sec,
        )
        return bool(payload.get("focused", False))

    def set_reader_window(
        self,
        action: str,
        *,
        activate: bool = False,
        timeout_sec: float = 2.0,
    ) -> JapReaderWindowState:
        normalized_action = str(action).strip().lower()
        if normalized_action not in {"show", "hide"}:
            raise JapReaderClientError(
                f"Unsupported japReader window action: {action}",
                code="INVALID_WINDOW_ACTION",
                retryable=False,
            )
        payload = self._request(
            "POST",
            "/v1/window",
            {
                "action": normalized_action,
                "activate": bool(activate),
            },
            timeout_sec=timeout_sec,
        )
        return JapReaderWindowState(
            visible=bool(payload.get("readerVisible", False)),
            focused=bool(payload.get("readerFocused", False)),
        )

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[dict[str, Any]] = None,
        *,
        timeout_sec: Optional[float] = None,
    ) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"

        req = request.Request(
            f"{self._base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        timeout = self._timeout_sec if timeout_sec is None else max(0.2, timeout_sec)

        try:
            with request.urlopen(req, timeout=timeout) as response:
                raw = response.read()
        except error.HTTPError as exc:
            raw = exc.read()
            decoded = self._decode_response(raw)
            error_payload = decoded.get("error", {})
            raise JapReaderClientError(
                str(error_payload.get("message", exc.reason)),
                code=str(error_payload.get("code", "HTTP_ERROR")),
                retryable=bool(error_payload.get("retryable", False)),
                status_code=exc.code,
            ) from exc
        except (error.URLError, socket.timeout, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise JapReaderClientError(
                f"Unable to reach japReader bridge: {reason}",
                code="BRIDGE_UNAVAILABLE",
                retryable=True,
            ) from exc

        decoded = self._decode_response(raw)
        if not decoded.get("ok", False):
            error_payload = decoded.get("error", {})
            raise JapReaderClientError(
                str(error_payload.get("message", "japReader request failed")),
                code=str(error_payload.get("code", "BRIDGE_ERROR")),
                retryable=bool(error_payload.get("retryable", False)),
            )
        return decoded

    @staticmethod
    def _decode_response(raw: bytes) -> dict[str, Any]:
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise JapReaderClientError(
                "japReader returned invalid JSON",
                code="INVALID_RESPONSE",
                retryable=True,
            ) from exc
        if not isinstance(decoded, dict):
            raise JapReaderClientError(
                "japReader returned a non-object response",
                code="INVALID_RESPONSE",
                retryable=True,
            )
        return decoded
