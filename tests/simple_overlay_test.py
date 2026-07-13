#!/usr/bin/env python3
"""Manual smoke check for the real PyQt capture overlay."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.capture.overlay import CaptureWindow  # noqa: E402


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    overlay = CaptureWindow()
    overlay.captureCompleted.connect(
        lambda image: print(f"Captured {image.size[0]}x{image.size[1]} image")
    )
    overlay.show()
    overlay.raise_()
    overlay.activateWindow()

    print("Manual overlay check")
    print("- Drag the overlay interior to move it")
    print("- Drag an edge or corner to resize it")
    print("- Click the toggle button to pause/resume capture")
    print("- Press Ctrl+Z while focused to undo the last geometry change")
    print("- Press Esc to hide the overlay")
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
