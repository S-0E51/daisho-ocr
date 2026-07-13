#!/usr/bin/env python3
"""
代書 (Daisho) - High-Precision Japanese OCR Desktop Application

A PyQt6-based application for capturing and recognizing Japanese text
from screen regions using PP-OCRv5, manga-ocr, or Surya OCR engines.

Usage:
    python main.py
"""

import sys
import os
import io

# Ensure stdout/stderr exist for pythonw.exe (no console window)
# Must be done before any imports that use tqdm/transformers progress bars
if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"

# --- PaddlePaddle/PyTorch compatibility workarounds ---
# Must be set before ANY paddle or torch imports anywhere in the app.
# 1. Disable oneDNN to avoid PIR attribute conversion bugs in PaddlePaddle 3.x
os.environ.setdefault("FLAGS_use_mkldnn", "0")
# 2. Skip slow model hoster connectivity check on startup
os.environ.setdefault("DISABLE_MODEL_SOURCE_CHECK", "True")


def check_dependencies() -> list[str]:
    """Check for missing required dependencies."""
    missing = []
    required = [
        ("PyQt6", "PyQt6"),
        ("PIL", "Pillow"),
        ("numpy", "numpy"),
    ]
    for import_name, package_name in required:
        try:
            __import__(import_name)
        except ImportError:
            missing.append(package_name)
    return missing


def show_dependency_error(missing: list[str]) -> None:
    """Show error dialog for missing dependencies."""
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox
        app = QApplication(sys.argv)
        QMessageBox.critical(
            None,
            "Missing Dependencies",
            f"The following packages are required but not installed:\n\n"
            f"{chr(10).join('- ' + p for p in missing)}\n\n"
            f"Please install them with:\n"
            f"pip install {' '.join(missing)}"
        )
        sys.exit(1)
    except ImportError:
        print("ERROR: Missing required dependencies:")
        for package in missing:
            print(f"  - {package}")
        print(f"\nInstall with: pip install {' '.join(missing)}")
        sys.exit(1)


def main() -> int:
    """Main entry point."""
    from src.utils.logger import (
        setup_logger,
        log_info,
        log_error,
        log_warning,
        log_exception,
        log_system_info,
    )

    logger = setup_logger()
    log_info("Application starting...")
    log_system_info(heavy=os.environ.get("DAISHO_HEAVY_DIAGNOSTICS", "0") == "1")

    missing = check_dependencies()
    if missing:
        log_error(f"Missing dependencies: {missing}")
        show_dependency_error(missing)
        return 1

    log_info("All dependencies found")

    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import Qt

        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )

        app = QApplication(sys.argv)
        app.setApplicationName("代書")
        app.setOrganizationName("Daisho")

        log_info("QApplication created")

        from src.ui.main_window import MainWindow

        window = MainWindow()
        log_info("MainWindow created")

        start_minimized = window._settings.get("start_minimized", True)
        tray_available = window._tray is not None and window._tray.is_visible

        if start_minimized and tray_available:
            log_info("Starting minimized to system tray")
            print("Starting minimized to system tray")
            print("Double-click tray icon or use menu to show overlay")
        else:
            if start_minimized and not tray_available:
                log_warning("System tray unavailable, showing main window instead of starting minimized")
            window.show()
            log_info("Main window shown")

        log_info("Entering main event loop")
        result = app.exec()
        log_info(f"Application exiting with code {result}")
        return result

    except Exception as e:
        log_exception(e, "main()")
        print(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
