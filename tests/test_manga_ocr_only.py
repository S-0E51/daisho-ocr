#!/usr/bin/env python3
"""
Legacy command shim for the old manga-only smoke test.

The current app is intentionally multi-engine. This script now verifies the
active OCR manager instead of importing the removed overlay.py application.
"""

from __future__ import annotations

import sys

from _bootstrap import bootstrap


bootstrap()

from src.ocr.comparison import resolve_comparison_engine
from src.ocr.manager import OCREngine, get_engine_description, get_engine_name
from src.ocr.paddle_engine import get_available_paddle_profiles, normalize_paddle_profile


def main() -> int:
    print("=" * 70)
    print("OCR Manager Compatibility Smoke Test")
    print("=" * 70)

    failures: list[str] = []

    expected_engines = {
        OCREngine.PADDLE_OCR,
        OCREngine.RAPID_OCR,
        OCREngine.MANGA_OCR,
        OCREngine.SURYA,
    }
    actual_engines = set(OCREngine)
    if actual_engines != expected_engines:
        failures.append(f"Unexpected OCR engines: {actual_engines}")
    else:
        print("[OK] active multi-engine registry is complete")

    for engine in OCREngine:
        if not get_engine_name(engine) or not get_engine_description(engine):
            failures.append(f"Missing metadata for {engine.value}")
    print("[OK] engine names and descriptions are present")

    profiles = get_available_paddle_profiles()
    if profiles != ("fast", "standard", "accurate"):
        failures.append(f"Unexpected Paddle profiles: {profiles}")
    if normalize_paddle_profile("mobile") != "fast":
        failures.append("Legacy Paddle profile alias 'mobile' did not normalize to 'fast'")
    if normalize_paddle_profile("quality") != "accurate":
        failures.append("Legacy Paddle profile alias 'quality' did not normalize to 'accurate'")
    print("[OK] Paddle profile normalization works")

    if resolve_comparison_engine(OCREngine.RAPID_OCR, "auto") != OCREngine.PADDLE_OCR:
        failures.append("RapidOCR auto comparison should fall back to PaddleOCR")
    print("[OK] comparison fallback map handles RapidOCR")

    if failures:
        print("[FAIL] OCR manager compatibility smoke test failed")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("[OK] OCR manager compatibility smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
