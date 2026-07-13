#!/usr/bin/env python3
"""Lightweight UI and settings tests for the managed japReader companion."""

from __future__ import annotations

import json
import os
import sys
import tempfile

from _bootstrap import bootstrap


bootstrap()


class FakeControl:
    def __init__(self) -> None:
        self.text = ""
        self.enabled = None

    def setText(self, text: str) -> None:
        self.text = text

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)


class FakeStatusBar:
    def __init__(self) -> None:
        self.messages = []

    def showMessage(self, message: str) -> None:
        self.messages.append(message)


class FakeTray:
    def __init__(self) -> None:
        self.japreader_updates = []

    def update_japreader_status(
        self,
        label: str,
        *,
        can_show: bool,
        can_hide: bool,
    ) -> None:
        self.japreader_updates.append((label, can_show, can_hide))


class FakeManager:
    def __init__(self) -> None:
        self.show_calls = []
        self.hide_calls = 0

    def show_reader(self, *, activate: bool = True) -> bool:
        self.show_calls.append(activate)
        return True

    def hide_reader(self) -> bool:
        self.hide_calls += 1
        return True


class FakeOCRManager:
    def set_paddle_profile(self, profile: object) -> object:
        return profile

    def set_engine(self, engine: object) -> None:
        return None


def assert_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def make_window(MainWindow):
    window = MainWindow.__new__(MainWindow)
    window._is_shutting_down = False
    window._settings = {"japreader_integration_mode": "direct"}
    window._japreader_chip = FakeControl()
    window._japreader_toggle_btn = FakeControl()
    window._tray = FakeTray()
    window._statusbar = FakeStatusBar()
    window._japreader_manager = FakeManager()
    return window


def test_status_and_toggle(MainWindow, JapReaderStatus) -> None:
    window = make_window(MainWindow)
    hidden = JapReaderStatus(
        "connected",
        "ready",
        connected=True,
        parser_ready=True,
        reader_visible=False,
    )
    window._on_japreader_status_changed(hidden)
    assert_equal(window._japreader_chip.text, "japReader: Hidden", "hidden chip")
    assert_equal(window._japreader_toggle_btn.text, "Show japReader", "hidden action")
    assert_equal(window._tray.japreader_updates[-1], ("Hidden", True, False), "hidden tray")

    visible = JapReaderStatus(
        "connected",
        "ready",
        connected=True,
        parser_ready=True,
        reader_visible=True,
    )
    window._on_japreader_status_changed(visible)
    assert_equal(window._japreader_chip.text, "japReader: Ready", "visible chip")
    assert_equal(window._japreader_toggle_btn.text, "Hide japReader", "visible action")
    assert_equal(window._tray.japreader_updates[-1], ("Ready", False, True), "visible tray")

    window._toggle_japreader()
    assert_equal(window._japreader_manager.hide_calls, 1, "visible toggle")
    window._on_japreader_status_changed(hidden)
    window._toggle_japreader()
    assert_equal(window._japreader_manager.show_calls, [True], "hidden toggle")

    window._settings["japreader_integration_mode"] = "disabled"
    window._on_japreader_status_changed(
        JapReaderStatus("disabled", "disabled", reader_visible=False)
    )
    assert_equal(window._japreader_chip.text, "japReader: Disabled", "disabled chip")
    assert_equal(window._japreader_toggle_btn.enabled, False, "disabled action")
    assert_equal(
        window._tray.japreader_updates[-1],
        ("Disabled", False, False),
        "disabled tray",
    )


def test_tray_actions(TrayManager) -> None:
    tray = TrayManager.__new__(TrayManager)
    tray._japreader_status_action = FakeControl()
    tray._show_japreader_action = FakeControl()
    tray._hide_japreader_action = FakeControl()
    tray.update_japreader_status("Hidden", can_show=True, can_hide=False)
    assert_equal(tray._japreader_status_action.text, "Status: Hidden", "tray label")
    assert_equal(tray._show_japreader_action.enabled, True, "tray show")
    assert_equal(tray._hide_japreader_action.enabled, False, "tray hide")


def load_settings(MainWindow, main_window_module, payload: dict) -> dict:
    with tempfile.TemporaryDirectory() as temp_dir:
        settings_path = os.path.join(temp_dir, "ocr_settings.json")
        with open(settings_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

        window = MainWindow.__new__(MainWindow)
        window._settings = window._get_default_settings()
        window._ocr_manager = FakeOCRManager()
        previous_base_dir = main_window_module.BASE_DIR
        main_window_module.BASE_DIR = temp_dir
        try:
            window._load_settings()
        finally:
            main_window_module.BASE_DIR = previous_base_dir
        return window._settings


def test_settings_migration(MainWindow, main_window_module) -> None:
    cases = [
        ({}, "reveal"),
        ({"japreader_focus_after_ocr": True}, "focus"),
        ({"japreader_focus_after_ocr": False}, "hidden"),
        ({"japreader_post_capture_behavior": "reveal"}, "reveal"),
        ({"japreader_post_capture_behavior": "focus"}, "focus"),
        ({"japreader_post_capture_behavior": "hidden"}, "hidden"),
        ({"japreader_post_capture_behavior": "invalid"}, "reveal"),
    ]
    for payload, expected in cases:
        settings = load_settings(MainWindow, main_window_module, payload)
        assert_equal(
            settings["japreader_post_capture_behavior"],
            expected,
            f"settings migration for {payload!r}",
        )
        if "japreader_focus_after_ocr" in settings:
            raise AssertionError("Legacy japReader focus key survived migration")


def test_settings_dialog_control(SettingsDialog, QApplication) -> None:
    app = QApplication.instance() or QApplication([])
    dialog = SettingsDialog(
        {
            "japreader_integration_mode": "direct",
            "japreader_post_capture_behavior": "reveal",
        }
    )
    try:
        assert_equal(
            dialog._japreader_behavior_combo.currentData(),
            "reveal",
            "settings dialog loaded behavior",
        )
        focus_index = dialog._japreader_behavior_combo.findData("focus")
        dialog._japreader_behavior_combo.setCurrentIndex(focus_index)
        dialog._apply_settings()
        assert_equal(
            dialog.get_settings()["japreader_post_capture_behavior"],
            "focus",
            "settings dialog saved behavior",
        )
        if "japreader_focus_after_ocr" in dialog.get_settings():
            raise AssertionError("Settings dialog restored the legacy focus key")
    finally:
        dialog.close()
        app.processEvents()


def main() -> int:
    try:
        from src.integration.japreader_manager import JapReaderStatus
        from src.ui import main_window as main_window_module
        from src.ui.main_window import MainWindow
        from src.ui.settings_dialog import SettingsDialog
        from src.ui.tray import TrayManager
        from PyQt6.QtWidgets import QApplication
    except ModuleNotFoundError as exc:
        if exc.name == "PyQt6":
            print("[SKIP] PyQt6 is unavailable")
            return 0
        raise

    test_status_and_toggle(MainWindow, JapReaderStatus)
    test_tray_actions(TrayManager)
    test_settings_migration(MainWindow, main_window_module)
    test_settings_dialog_control(SettingsDialog, QApplication)
    print("[OK] Managed japReader companion UI and settings behavior passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
