#!/usr/bin/env python3
"""
Smoke tests for keeping capture disabled while the overlay is hidden.
"""

from __future__ import annotations

import sys

from _bootstrap import bootstrap


bootstrap()


class FakeOverlay:
    def __init__(self, visible: bool, hotkey_enabled: bool = True) -> None:
        self._visible = visible
        self.hotkey_enabled = hotkey_enabled
        self.capture_count = 0

    def isVisible(self) -> bool:
        return self._visible

    def capture_region(self) -> None:
        self.capture_count += 1


class FakeStatusBar:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def showMessage(self, message: str) -> None:
        self.messages.append(message)


class FakeButton:
    def __init__(self) -> None:
        self.enabled: bool | None = None

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled


def make_window(overlay: FakeOverlay | None):
    from src.ui.main_window import MainWindow

    window = MainWindow.__new__(MainWindow)
    window._is_shutting_down = False
    window._overlay = overlay
    window._statusbar = FakeStatusBar()
    window._show_overlay_btn = FakeButton()
    window._hide_overlay_btn = FakeButton()
    window._capture_btn = FakeButton()
    window.show_overlay_count = 0

    def show_overlay() -> None:
        window.show_overlay_count += 1

    window._show_overlay = show_overlay
    return window


def assert_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def main() -> int:
    try:
        from src.ui.main_window import MainWindow  # noqa: F401
    except ModuleNotFoundError as exc:
        if exc.name == "PyQt6":
            print("[SKIP] PyQt6 is unavailable")
            return 0
        raise

    hidden_hotkey_window = make_window(None)
    hidden_hotkey_window._do_capture_from_hotkey()
    assert_equal(hidden_hotkey_window.show_overlay_count, 0, "hidden hotkey should not show overlay")
    assert_equal(
        hidden_hotkey_window._statusbar.messages[-1],
        "Capture is disabled while the overlay is hidden.",
        "hidden hotkey status",
    )

    hidden_overlay = FakeOverlay(visible=False)
    hidden_manual_window = make_window(hidden_overlay)
    hidden_manual_window._manual_capture()
    assert_equal(hidden_manual_window.show_overlay_count, 0, "hidden manual capture should not show overlay")
    assert_equal(hidden_overlay.capture_count, 0, "hidden manual capture should not capture")

    visible_overlay = FakeOverlay(visible=True)
    visible_hotkey_window = make_window(visible_overlay)
    visible_hotkey_window._do_capture_from_hotkey()
    assert_equal(visible_overlay.capture_count, 1, "visible hotkey should capture")

    visible_manual_window = make_window(visible_overlay)
    visible_manual_window._manual_capture()
    assert_equal(visible_overlay.capture_count, 2, "visible manual capture should capture")

    paused_overlay = FakeOverlay(visible=True, hotkey_enabled=False)
    paused_window = make_window(paused_overlay)
    paused_window._do_capture_from_hotkey()
    assert_equal(paused_overlay.capture_count, 0, "paused hotkey should not capture")
    assert_equal(
        paused_window._statusbar.messages[-1],
        "Capture is paused. Click the overlay toggle to resume.",
        "paused hotkey status",
    )

    paused_manual_window = make_window(paused_overlay)
    paused_manual_window._manual_capture()
    assert_equal(paused_overlay.capture_count, 0, "paused manual capture should not capture")
    assert_equal(
        paused_manual_window._statusbar.messages[-1],
        "Capture is paused. Click the overlay toggle to resume.",
        "paused manual capture status",
    )

    controls_window = make_window(FakeOverlay(visible=True, hotkey_enabled=False))
    controls_window._update_capture_controls(overlay_visible=True)
    assert_equal(controls_window._show_overlay_btn.enabled, False, "visible overlay show button")
    assert_equal(controls_window._hide_overlay_btn.enabled, True, "visible overlay hide button")
    assert_equal(controls_window._capture_btn.enabled, False, "paused overlay capture button")

    print("[OK] Capture remains disabled while overlay is hidden")
    return 0


if __name__ == "__main__":
    sys.exit(main())
