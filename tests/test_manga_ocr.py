#!/usr/bin/env python3
"""
Smoke test for the active manga-ocr wrapper.

By default this verifies imports and app integration without downloading model
weights. Set DAISHO_TEST_LOAD_MODELS=1 or pass --load-model to run inference.
"""

from __future__ import annotations

import os
import sys

from PIL import Image, ImageDraw

from _bootstrap import bootstrap


bootstrap()

from src.ocr.manager import OCREngine, get_engine_description, get_engine_name
from src.ocr.manga_engine import get_manga_engine


def should_load_model() -> bool:
    return "--load-model" in sys.argv or os.environ.get("DAISHO_TEST_LOAD_MODELS") == "1"


def make_sample_image() -> Image.Image:
    image = Image.new("RGB", (240, 96), color="white")
    draw = ImageDraw.Draw(image)
    draw.text((16, 32), "テスト", fill="black")
    return image


def main() -> int:
    print("=" * 70)
    print("manga-ocr Wrapper Smoke Test")
    print("=" * 70)

    failures: list[str] = []

    try:
        import manga_ocr  # noqa: F401
        print("[OK] manga-ocr package imports")
    except Exception as exc:
        failures.append(f"manga-ocr package import failed: {exc}")

    engine_name = get_engine_name(OCREngine.MANGA_OCR)
    description = get_engine_description(OCREngine.MANGA_OCR)
    if "manga" not in engine_name.lower() or not description:
        failures.append("OCR manager metadata for manga-ocr is missing")
    else:
        print(f"[OK] manager exposes {engine_name}")

    wrapper = get_manga_engine()
    if wrapper.is_loaded:
        print("[OK] manga-ocr wrapper is already loaded")
    else:
        print("[OK] manga-ocr wrapper initializes lazily")

    if should_load_model() and not failures:
        print("[INFO] Loading model because deep inference was requested")
        wrapper.load_model_async()
        wrapper.wait_for_load(timeout=300)
        if not wrapper.is_loaded:
            failures.append(f"manga-ocr model failed to load: {wrapper.load_error}")
        else:
            result = wrapper.perform_ocr(make_sample_image())
            print(f"[OK] inference completed, result={result!r}")
    else:
        print("[SKIP] model load/inference skipped; pass --load-model for the deep check")

    if failures:
        print("[FAIL] manga-ocr smoke test failed")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("[OK] manga-ocr wrapper smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
