#!/usr/bin/env python3
"""
Smoke tests for tap-vs-hold behavior on the overlay-to-mouse hotkey.
"""

from __future__ import annotations

import sys

from _bootstrap import bootstrap


bootstrap()


class FakeTimer:
    def __init__(self) -> None:
        self.active = False
        self.started_with_ms: int | None = None

    def start(self, delay_ms: int) -> None:
        self.active = True
        self.started_with_ms = delay_ms

    def stop(self) -> None:
        self.active = False

    def isActive(self) -> bool:
        return self.active

    def fire(self, callback) -> None:
        self.active = False
        callback()


class FakeOverlay:
    def __init__(self, visible: bool = True, hotkey_enabled: bool = True) -> None:
        self._visible = visible
        self.hotkey_enabled = hotkey_enabled
        self.capture_in_progress = False
        self.show_count = 0
        self.hide_count = 0
        self.center_count = 0
        self.focus_count = 0
        self.cancel_restore_count = 0

    def isVisible(self) -> bool:
        return self._visible

    def show(self) -> None:
        self._visible = True
        self.show_count += 1

    def hide(self) -> None:
        self._visible = False
        self.hide_count += 1

    def raise_(self) -> None:
        pass

    def activateWindow(self) -> None:
        pass

    def center_on_global_point(self, _point) -> bool:
        self.center_count += 1
        return True

    def focus_for_input(self) -> None:
        self.focus_count += 1

    def cancel_pending_capture_restore(self) -> None:
        self.cancel_restore_count += 1


class FakeStatusBar:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def showMessage(self, message: str) -> None:
        self.messages.append(message)


def make_window(overlay: FakeOverlay | None):
    from src.ui.main_window import MainWindow

    window = MainWindow.__new__(MainWindow)
    window._is_shutting_down = False
    window._overlay = overlay
    window._statusbar = FakeStatusBar()
    window._overlay_to_mouse_hold_timer = FakeTimer()
    window._overlay_to_mouse_hold_triggered = False
    window._settings = {
        "allow_move_overlay_to_mouse_when_hidden": True,
        "allow_move_overlay_to_mouse_when_locked": False,
    }
    window.capture_controls_visible: bool | None = None
    window.move_count = 0

    def update_capture_controls(overlay_visible: bool) -> None:
        window.capture_controls_visible = overlay_visible

    def move_overlay_to_mouse() -> None:
        window.move_count += 1

    window._update_capture_controls = update_capture_controls
    window._move_overlay_to_mouse_from_hotkey = move_overlay_to_mouse
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

    tap_window = make_window(FakeOverlay())
    tap_window._begin_overlay_to_mouse_hold()
    assert_equal(
        tap_window._overlay_to_mouse_hold_timer.started_with_ms,
        tap_window.OVERLAY_TO_MOUSE_HOLD_THRESHOLD_MS,
        "hold threshold",
    )
    tap_window._finish_overlay_to_mouse_hold()
    assert_equal(tap_window.move_count, 1, "tap should move overlay")

    hold_overlay = FakeOverlay(visible=True, hotkey_enabled=True)
    hold_window = make_window(hold_overlay)
    hold_window._begin_overlay_to_mouse_hold()
    hold_window._overlay_to_mouse_hold_timer.fire(hold_window._on_overlay_to_mouse_hold_timeout)
    assert_equal(hold_overlay.hotkey_enabled, False, "hold should pause capture")
    assert_equal(hold_overlay.isVisible(), False, "hold should hide overlay")
    assert_equal(hold_window.capture_controls_visible, False, "hold should update capture controls")
    assert_equal(
        hold_window._statusbar.messages[-1],
        "Overlay hidden and capture paused.",
        "hold status",
    )

    hold_window._finish_overlay_to_mouse_hold()
    assert_equal(hold_window.move_count, 0, "release after hold should not move overlay")

    visible_overlay = FakeOverlay(visible=True, hotkey_enabled=True)
    visible_window = make_window(visible_overlay)
    visible_window._move_overlay_to_mouse_from_hotkey = (
        MainWindow._move_overlay_to_mouse_from_hotkey.__get__(visible_window, MainWindow)
    )
    visible_window._move_overlay_to_mouse_from_hotkey()
    assert_equal(visible_overlay.center_count, 1, "visible overlay should be centered")
    assert_equal(visible_overlay.focus_count, 1, "visible overlay should be focused")

    paused_visible_overlay = FakeOverlay(visible=True, hotkey_enabled=False)
    paused_visible_window = make_window(paused_visible_overlay)
    paused_visible_window._move_overlay_to_mouse_from_hotkey = (
        MainWindow._move_overlay_to_mouse_from_hotkey.__get__(paused_visible_window, MainWindow)
    )
    paused_visible_window._move_overlay_to_mouse_from_hotkey()
    assert_equal(paused_visible_overlay.center_count, 0, "paused visible overlay should not move")
    assert_equal(paused_visible_overlay.focus_count, 1, "paused visible overlay should still be focused")

    hidden_locked_overlay = FakeOverlay(visible=False, hotkey_enabled=False)
    locked_window = make_window(hidden_locked_overlay)
    locked_window._move_overlay_to_mouse_from_hotkey = (
        MainWindow._move_overlay_to_mouse_from_hotkey.__get__(locked_window, MainWindow)
    )
    locked_window._move_overlay_to_mouse_from_hotkey()
    assert_equal(hidden_locked_overlay.hotkey_enabled, True, "hidden paused overlay should re-enable capture")
    assert_equal(hidden_locked_overlay.show_count, 1, "hidden paused overlay should be shown")
    assert_equal(hidden_locked_overlay.center_count, 1, "hidden paused overlay should be centered")
    assert_equal(hidden_locked_overlay.focus_count, 1, "hidden paused overlay should be focused")

    default_recovery_overlay = FakeOverlay(visible=False, hotkey_enabled=False)
    default_recovery_window = make_window(default_recovery_overlay)
    default_recovery_window._settings["allow_move_overlay_to_mouse_when_hidden"] = False
    default_recovery_window._move_overlay_to_mouse_from_hotkey = (
        MainWindow._move_overlay_to_mouse_from_hotkey.__get__(default_recovery_window, MainWindow)
    )
    default_recovery_window._move_overlay_to_mouse_from_hotkey()
    assert_equal(
        default_recovery_overlay.hotkey_enabled,
        True,
        "hidden paused overlay should recover with hidden move disabled",
    )
    assert_equal(
        default_recovery_overlay.show_count,
        1,
        "hidden paused overlay should show with hidden move disabled",
    )
    assert_equal(
        default_recovery_overlay.focus_count,
        1,
        "hidden paused overlay should focus with hidden move disabled",
    )

    print("[OK] Overlay-to-mouse tap and hold behavior passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
