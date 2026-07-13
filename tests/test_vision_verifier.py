#!/usr/bin/env python3
"""
Smoke tests for the Gemma vision verification helper without loading a model.
"""

from __future__ import annotations

import sys

from _bootstrap import bootstrap


bootstrap()

from src.ocr.manager import OCREngine
from src.ocr.comparison import OCRCandidate
from src.ocr.vision_verifier import (
    VISION_VERIFICATION_MODE_ALWAYS,
    VISION_VERIFICATION_MODE_OFF,
    VISION_VERIFICATION_MODE_SUSPICIOUS,
    VisionVerificationResult,
    apply_verification_result,
    get_ollama_model_name,
    is_ollama_verification_model,
    normalize_verification_mode,
    parse_verification_response,
    should_run_visual_verification,
)


def main() -> int:
    print("=" * 70)
    print("Gemma Vision Verification Helper Test")
    print("=" * 70)

    failures: list[str] = []

    if normalize_verification_mode("bad-mode") != VISION_VERIFICATION_MODE_OFF:
        failures.append("Unknown verification mode did not normalize to off")

    ollama_id = "ollama:huihui_ai/gemma-4-abliterated:e4b"
    if not is_ollama_verification_model(ollama_id):
        failures.append("Ollama-prefixed verifier model was not detected")
    if get_ollama_model_name(ollama_id) != "huihui_ai/gemma-4-abliterated:e4b":
        failures.append("Ollama model name was not extracted correctly")

    candidate = OCRCandidate(
        engine=OCREngine.MANGA_OCR,
        text="\u9aef\u837b",
        raw_text="\u9aef\u837b",
        average_confidence=0.95,
    )
    should_verify, reasons = should_run_visual_verification(
        VISION_VERIFICATION_MODE_SUSPICIOUS,
        candidate,
    )
    print(f"[INFO] Suspicious short-CJK trigger: {should_verify} | reasons={reasons}")
    if not should_verify:
        failures.append("Short dense CJK text did not trigger suspicious vision verification")

    always_verify, _ = should_run_visual_verification(
        VISION_VERIFICATION_MODE_ALWAYS,
        candidate,
    )
    if not always_verify:
        failures.append("Always Verify mode did not trigger verification")

    parsed = parse_verification_response(
        '```json\n{"matches": false, "corrected_text": "\\u9aef\\u838e", '
        '"confidence": 0.91, "uncertain_chars": [], "reason": "bottom strokes differ"}\n```',
        model_id="google/gemma-4-E2B-it",
    )
    if parsed.matches is not False or parsed.corrected_text != "\u9aef\u838e":
        failures.append("Verifier JSON response did not parse correctly")

    decision = apply_verification_result(candidate, parsed, min_confidence=0.82)
    if not decision.used_correction or decision.selected.text != "\u9aef\u838e":
        failures.append("High-confidence verifier correction was not applied")

    low_confidence = VisionVerificationResult(
        matches=False,
        corrected_text="\u9aef\u838e",
        confidence=0.40,
        reason="too blurry",
        model_id="google/gemma-4-E2B-it",
    )
    low_decision = apply_verification_result(candidate, low_confidence, min_confidence=0.82)
    if low_decision.used_correction or low_decision.selected.text != candidate.text:
        failures.append("Low-confidence verifier correction should have been rejected")

    if failures:
        print("[FAIL] Vision verification helper test failed")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("[OK] Vision verification helper passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
