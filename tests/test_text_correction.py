#!/usr/bin/env python3
"""
Smoke tests for the conservative Japanese post-OCR corrector.
"""

from __future__ import annotations

import sys

from _bootstrap import bootstrap


bootstrap()

from src.correction import get_text_corrector


def main() -> int:
    corrector = get_text_corrector()
    print("=" * 70)
    print("Japanese Post-OCR Correction Test")
    print("=" * 70)
    print(f"Corrector available: {corrector.available}")
    print()

    if not corrector.available:
        print("[SKIP] fugashi is unavailable, conservative correction is disabled")
        return 0

    cases = [
        ("ずつと", "ずっと", True),
        ("ちよつと", "ちょっと", True),
        ("ちよっと", "ちょっと", True),
        ("しゆっぱつ", "しゅっぱつ", True),
        ("じやあ", "じゃあ", True),
        ("にょって", "によって", True),
        ("質問内容にょっては", "質問内容によっては", True),
        ("きよう", "きよう", False),
        ("しよう", "しよう", False),
        ("によって", "によって", False),
        ("質問内容によっては", "質問内容によっては", False),
    ]

    failures = []
    for source, expected, should_change in cases:
        result = corrector.correct(source)
        changed = result.text != source
        ok = result.text == expected and changed == should_change
        status = "OK" if ok else "FAIL"
        notes = ", ".join(result.corrections) if result.corrections else "<none>"
        print(f"[{status}] {source} -> {result.text} | expected {expected} | corrections: {notes}")
        if not ok:
            failures.append((source, expected, result.text, should_change, changed))

    print()
    if failures:
        print("[FAIL] Correction test failed")
        for source, expected, actual, should_change, changed in failures:
            print(
                f"  source={source!r} expected={expected!r} actual={actual!r} "
                f"expected_change={should_change} actual_change={changed}"
            )
        return 1

    print("[OK] All correction cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
