#!/usr/bin/env python3
"""
Smoke test for Surya confidence extraction without loading Surya model weights.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from PIL import Image

from _bootstrap import bootstrap


bootstrap()

from src.ocr.surya_engine import get_surya_engine


@dataclass
class FakeLine:
    text: str
    confidence: float


@dataclass
class FakePrediction:
    text_lines: list[FakeLine]


class FakeRecognitionPredictor:
    def __call__(self, images, det_predictor=None):
        return [
            FakePrediction([
                FakeLine("縦書き", 0.9),
                FakeLine("テスト", 0.8),
                FakeLine("noise", 0.1),
            ])
        ]


def main() -> int:
    print("=" * 70)
    print("Surya Analysis Smoke Test")
    print("=" * 70)

    engine = get_surya_engine()
    old_state = (
        engine._is_loaded,
        engine._recognition_predictor,
        engine._detection_predictor,
        engine._load_error,
    )

    try:
        engine._is_loaded = True
        engine._load_error = None
        engine._recognition_predictor = FakeRecognitionPredictor()
        engine._detection_predictor = object()

        result = engine.perform_ocr_analysis(Image.new("RGB", (120, 80), "white"))
        if result.text != "縦書き\nテスト":
            print(f"[FAIL] Unexpected Surya text: {result.text!r}")
            return 1
        if result.average_confidence is None or round(result.average_confidence, 2) != 0.85:
            print(f"[FAIL] Unexpected confidence: {result.average_confidence!r}")
            return 1

        print("[OK] Surya text and confidence metadata are extracted")
        return 0

    finally:
        (
            engine._is_loaded,
            engine._recognition_predictor,
            engine._detection_predictor,
            engine._load_error,
        ) = old_state


if __name__ == "__main__":
    sys.exit(main())
