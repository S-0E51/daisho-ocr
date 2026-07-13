#!/usr/bin/env python3
"""
Smoke test for the optional RapidOCR wrapper without loading model weights.
"""

from __future__ import annotations

import sys

from _bootstrap import bootstrap


bootstrap()

from src.ocr.rapid_engine import get_rapid_engine


class FakeRapidResult:
    txts = ("日本語", "テスト")
    scores = (0.91, 0.83)


def main() -> int:
    print("=" * 70)
    print("RapidOCR Wrapper Smoke Test")
    print("=" * 70)

    engine = get_rapid_engine()
    text, scores = engine._extract_text_and_scores(FakeRapidResult())
    if text != "日本語テスト":
        print(f"[FAIL] Unexpected normalized text: {text!r}")
        return 1
    if [round(score, 2) for score in scores] != [0.91, 0.83]:
        print(f"[FAIL] Unexpected scores: {scores!r}")
        return 1

    legacy_text, legacy_scores = engine._extract_text_and_scores([
        [None, "かな", "0.75"],
        [None, "漢字", 0.8],
    ])
    if legacy_text != "かな漢字" or [round(score, 2) for score in legacy_scores] != [0.75, 0.8]:
        print("[FAIL] Legacy RapidOCR output normalization failed")
        return 1

    print("[OK] RapidOCR result normalization works")
    return 0


if __name__ == "__main__":
    sys.exit(main())
