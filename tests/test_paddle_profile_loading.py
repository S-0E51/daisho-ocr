#!/usr/bin/env python3
"""Smoke test for Paddle profile changes while a model load is in flight."""

from __future__ import annotations

import sys
import threading
import time

from _bootstrap import bootstrap


bootstrap()

from src.ocr.paddle_engine import get_paddle_engine  # noqa: E402


def main() -> int:
    print("=" * 70)
    print("Paddle Profile Loading Test")
    print("=" * 70)

    engine = get_paddle_engine()
    original_load_model_sync = engine._load_model_sync
    callbacks: list[tuple[str, bool, object]] = []
    fast_callback_done = threading.Event()

    def reset_engine_state() -> None:
        engine._ocr = None
        engine._ocr_cache.clear()
        engine._is_loaded = False
        engine._is_loading = False
        engine._load_error = None
        engine._loading_model_key = None
        engine._load_event.set()
        engine.set_profile("standard")

    def fake_load_model_sync(model_key=None) -> None:
        key = model_key or engine._active_model_key
        time.sleep(0.05)
        engine._ocr_cache[key] = object()
        if engine._active_model_key == key:
            engine._ocr = engine._ocr_cache[key]
            engine._is_loaded = True
        else:
            engine._ocr = engine._ocr_cache.get(engine._active_model_key)
            engine._is_loaded = engine._ocr is not None
        engine._load_error = None
        engine._is_loading = False
        engine._loading_model_key = None
        engine._load_event.set()

    try:
        reset_engine_state()
        engine._load_model_sync = fake_load_model_sync

        engine.load_model_async(
            lambda success, error: callbacks.append(("standard", success, error))
        )
        engine.set_profile("fast")
        engine.load_model_async(
            lambda success, error: (
                callbacks.append(("fast", success, error)),
                fast_callback_done.set(),
            )
        )

        if not fast_callback_done.wait(2.0):
            raise AssertionError("timed out waiting for follow-up fast profile load")
        if engine.profile != "fast":
            raise AssertionError(f"expected fast profile to remain active, got {engine.profile!r}")
        if not engine.is_loaded:
            raise AssertionError("expected fast profile to be loaded after in-flight profile switch")
        if not callbacks or callbacks[-1] != ("fast", True, None):
            raise AssertionError(f"expected successful fast callback, got {callbacks!r}")
    finally:
        engine._load_model_sync = original_load_model_sync
        reset_engine_state()

    print("[OK] Paddle profile in-flight load switching passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
