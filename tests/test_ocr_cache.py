#!/usr/bin/env python3
"""Smoke tests for OCR cache key correctness and pipeline cacheability."""

from __future__ import annotations

from types import SimpleNamespace
import sys

from _bootstrap import bootstrap


bootstrap()

from PIL import Image  # noqa: E402

from src.ocr.cache import OCRCache  # noqa: E402
from src.ocr.comparison import OCRCandidate  # noqa: E402
from src.ocr.manager import OCREngine  # noqa: E402


def assert_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_large_image_hash_uses_all_pixels() -> None:
    cache = OCRCache()
    first = Image.new("RGB", (1000, 1000), "white")
    second = first.copy()
    second.putpixel((500, 500), (0, 0, 0))

    first_hash = cache._compute_image_hash(first)
    second_hash = cache._compute_image_hash(second)

    if first_hash == second_hash:
        raise AssertionError("large-image cache hash ignored a single-pixel OCR-significant change")
    if not first_hash.startswith("full:") or not second_hash.startswith("full:"):
        raise AssertionError("cache hash should use the exact full-pixel path")


def test_skipped_optional_stages_are_not_cacheable() -> None:
    try:
        from src.ui import main_window
    except ModuleNotFoundError as exc:
        if exc.name == "PyQt6":
            print("[SKIP] PyQt6 is unavailable")
            return
        raise

    candidate = OCRCandidate(
        engine=OCREngine.PADDLE_OCR,
        text="代書",
        raw_text="代書",
        average_confidence=0.91,
    )
    window = main_window.MainWindow.__new__(main_window.MainWindow)

    class FakeVerifier:
        is_loaded = False
        is_loading = False
        model_id = ""

        def __init__(self) -> None:
            self.load_requested = False

        def can_retry_load(self, model_id: str):
            return True, ""

        def load_model_async(self, model_id: str) -> None:
            self.load_requested = True

    verifier = FakeVerifier()
    original_verifier_getter = main_window.get_gemma_vision_verifier
    main_window.get_gemma_vision_verifier = lambda: verifier
    try:
        job = SimpleNamespace(
            ocr_verification_mode="always",
            ocr_verification_model="test-gemma",
            ocr_verification_min_confidence=0.82,
        )
        selected, notes, cacheable = main_window.MainWindow._resolve_visual_verification_candidate(
            window,
            job,
            Image.new("RGB", (40, 20), "white"),
            candidate,
        )
    finally:
        main_window.get_gemma_vision_verifier = original_verifier_getter

    assert_equal(selected, candidate, "verification skip should keep original candidate")
    assert_equal(cacheable, False, "verification skip cacheability")
    if not verifier.load_requested:
        raise AssertionError("verification skip should request background verifier load")
    if not notes or "loading" not in notes[0].lower():
        raise AssertionError(f"expected verifier loading note, got {notes!r}")

    class FakeOCRManager:
        current_engine = OCREngine.PADDLE_OCR

        def is_engine_loaded(self, engine: OCREngine) -> bool:
            return False

        def is_engine_loading(self, engine: OCREngine) -> bool:
            return False

        def load_engine_blocking(self, engine: OCREngine, timeout: float):
            return False, "missing optional model"

    comparison_window = main_window.MainWindow.__new__(main_window.MainWindow)
    comparison_window._ocr_manager = FakeOCRManager()
    comparison_window._settings = {"keep_inactive_ocr_engines_warm": False}
    comparison_window._optional_engine_retry_after = {}
    comparison_window._optional_engine_load_errors = {}
    comparison_job = SimpleNamespace(
        ocr_comparison_mode="always",
        ocr_comparison_engine=OCREngine.MANGA_OCR.value,
    )

    selected, notes, cacheable = main_window.MainWindow._resolve_comparison_candidate(
        comparison_window,
        comparison_job,
        Image.new("RGB", (40, 20), "white"),
        candidate,
    )

    assert_equal(selected, candidate, "comparison skip should keep primary candidate")
    assert_equal(cacheable, False, "comparison skip cacheability")
    if not notes or "could not load" not in notes[0]:
        raise AssertionError(f"expected comparison load failure note, got {notes!r}")


def main() -> int:
    print("=" * 70)
    print("OCR Cache Test")
    print("=" * 70)
    test_large_image_hash_uses_all_pixels()
    test_skipped_optional_stages_are_not_cacheable()
    print("[OK] OCR cache behavior passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
