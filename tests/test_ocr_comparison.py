#!/usr/bin/env python3
"""
Smoke tests for the OCR comparison helper.
"""

from __future__ import annotations

import sys

from _bootstrap import bootstrap


bootstrap()

from src.ocr.comparison import (
    OCRCandidate,
    OCR_COMPARISON_MODE_SUSPICIOUS,
    compare_candidates,
    resolve_comparison_engine,
    should_run_comparison,
)
from src.ocr.manager import OCREngine


def main() -> int:
    print("=" * 70)
    print("OCR Comparison Test")
    print("=" * 70)

    failures: list[str] = []

    auto_primary = resolve_comparison_engine(OCREngine.PADDLE_OCR, "auto")
    if auto_primary != OCREngine.MANGA_OCR:
        failures.append(f"Expected Paddle auto comparison engine to be manga-ocr, got {auto_primary}")

    auto_rapid = resolve_comparison_engine(OCREngine.RAPID_OCR, "auto")
    if auto_rapid != OCREngine.PADDLE_OCR:
        failures.append(f"Expected RapidOCR auto comparison engine to be PaddleOCR, got {auto_rapid}")

    suspicious_primary = OCRCandidate(
        engine=OCREngine.PADDLE_OCR,
        text="\u63c3\u3063\u3066\u3044\u306a\u3042\u3068\u601d\u3063\u3066\u3002",
        raw_text="\u63c3\u3063\u3066\u3044\u306a\u3042\u3068\u601d\u3063\u3066\u3002",
        average_confidence=0.72,
    )
    should_compare, assessment = should_run_comparison(
        OCR_COMPARISON_MODE_SUSPICIOUS,
        suspicious_primary,
    )
    print(f"[INFO] Suspicious compare trigger: {should_compare} | reasons={assessment.suspicious_reasons}")
    if not should_compare:
        failures.append("Suspicious ていなあ pattern did not trigger OCR comparison")

    safer_secondary = OCRCandidate(
        engine=OCREngine.MANGA_OCR,
        text="\u63c3\u3063\u3066\u3044\u308b\u306a\u3041\u3068\u601d\u3063\u3066\u3002",
        raw_text="\u63c3\u3063\u3066\u3044\u308b\u306a\u3041\u3068\u601d\u3063\u3066\u3002",
    )
    decision = compare_candidates(suspicious_primary, safer_secondary)
    print(f"[INFO] Comparison decision: used_secondary={decision.used_secondary} | notes={decision.notes}")
    if not decision.used_secondary:
        failures.append("Expected comparison to choose the safer secondary candidate")

    corrected_primary = OCRCandidate(
        engine=OCREngine.PADDLE_OCR,
        text="\u306b\u3088\u3063\u3066",
        raw_text="\u306b\u3087\u3063\u3066",
        average_confidence=0.91,
        corrections=("\u306b\u3087\u3063\u3066 -> \u306b\u3088\u3063\u3066",),
    )
    corrected_should_compare, corrected_assessment = should_run_comparison(
        OCR_COMPARISON_MODE_SUSPICIOUS,
        corrected_primary,
    )
    print(
        "[INFO] Post-corrected compare trigger: "
        f"{corrected_should_compare} | reasons={corrected_assessment.suspicious_reasons}"
    )
    if not corrected_should_compare:
        failures.append("Expected post-corrected OCR text to trigger suspicious-only comparison")

    confirmed_secondary = OCRCandidate(
        engine=OCREngine.MANGA_OCR,
        text="\u306b\u3088\u3063\u3066",
        raw_text="\u306b\u3088\u3063\u3066",
    )
    confirmed_decision = compare_candidates(corrected_primary, confirmed_secondary)
    if confirmed_decision.used_secondary:
        failures.append("Expected matching comparison result to keep the primary candidate")

    if failures:
        print("[FAIL] OCR comparison test failed")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("[OK] OCR comparison helper passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
