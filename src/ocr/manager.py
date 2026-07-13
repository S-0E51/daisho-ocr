"""
OCR Manager - Unified interface for multiple OCR engines.

Provides a consistent interface for loading models, performing OCR,
and switching between engines at runtime.
"""

from __future__ import annotations
from enum import Enum
import time
from typing import Optional, Callable
from PIL import Image

from ..utils.logger import log_info, log_error, log_debug, log_warning
from .types import OCRAnalysisResult


class OCREngine(Enum):
    """Available OCR engines."""
    PADDLE_OCR = "paddle_ocr"
    PADDLE_VL = "paddle_ocr_vl"
    RAPID_OCR = "rapid_ocr"
    MANGA_OCR = "manga_ocr"
    SURYA = "surya"


ENGINE_INFO = {
    OCREngine.PADDLE_OCR: {
        "name": "PaddleOCR (PP-OCRv5)",
        "description": "Best general-purpose Japanese OCR for UI, VN, and clean game text. Fast and reliable.",
    },
    OCREngine.PADDLE_VL: {
        "name": "PaddleOCR-VL (0.9B)",
        "description": "One-stop vision-language OCR: SOTA vertical Japanese, 109 languages, manga/games/docs. Needs GPU + paddlex[ocr].",
    },
    OCREngine.RAPID_OCR: {
        "name": "RapidOCR (ONNX)",
        "description": "Optional lightweight ONNX Runtime engine for fast CPU OCR and PaddlePaddle-free fallback.",
    },
    OCREngine.MANGA_OCR: {
        "name": "manga-ocr",
        "description": "Vision Encoder-Decoder model optimized for manga/games. Best fallback for stylized text.",
    },
    OCREngine.SURYA: {
        "name": "Surya OCR",
        "description": "Document-style OCR with line-aware recognition. Strong optional fallback for clean print layouts.",
    },
}


def get_engine_name(engine: OCREngine) -> str:
    return ENGINE_INFO.get(engine, {}).get("name", engine.value)


def get_engine_description(engine: OCREngine) -> str:
    return ENGINE_INFO.get(engine, {}).get("description", "")


class OCRManager:
    """Unified manager for OCR engines with runtime switching and model caching."""

    ALL_ENGINES = (
        OCREngine.PADDLE_OCR,
        OCREngine.PADDLE_VL,
        OCREngine.RAPID_OCR,
        OCREngine.MANGA_OCR,
        OCREngine.SURYA,
    )

    def __init__(self) -> None:
        self._current_engine = OCREngine.PADDLE_OCR
        self._paddle_ocr = None
        self._paddle_vl_ocr = None
        self._rapid_ocr = None
        self._manga_ocr = None
        self._surya_ocr = None

    @property
    def current_engine(self) -> OCREngine:
        return self._current_engine

    @property
    def is_loaded(self) -> bool:
        engine = self._get_engine_instance()
        return engine is not None and engine.is_loaded

    @property
    def is_loading(self) -> bool:
        engine = self._get_engine_instance()
        return engine is not None and engine.is_loading

    @property
    def load_error(self) -> Optional[str]:
        engine = self._get_engine_instance()
        return engine.load_error if engine else None

    @property
    def uses_gpu(self) -> bool:
        engine = self._get_engine_instance()
        return engine.uses_gpu if engine else False

    def is_any_engine_loading(self) -> bool:
        """Return True when any instantiated engine is still loading."""
        return any(
            engine is not None and engine.is_loading
            for _, engine in self._engine_instances()
        )

    def _engine_instances(self):
        """Yield engines that have already been instantiated."""
        yield OCREngine.PADDLE_OCR, self._paddle_ocr
        yield OCREngine.PADDLE_VL, self._paddle_vl_ocr
        yield OCREngine.RAPID_OCR, self._rapid_ocr
        yield OCREngine.MANGA_OCR, self._manga_ocr
        yield OCREngine.SURYA, self._surya_ocr

    def _get_engine_instance(self, engine: Optional[OCREngine] = None):
        """Get an engine instance, lazily initialized and kept cached in memory."""
        target_engine = engine or self._current_engine

        if target_engine == OCREngine.PADDLE_OCR:
            if self._paddle_ocr is None:
                from .paddle_engine import get_paddle_engine
                self._paddle_ocr = get_paddle_engine()
            return self._paddle_ocr
        elif target_engine == OCREngine.PADDLE_VL:
            if self._paddle_vl_ocr is None:
                from .paddle_vl_engine import get_paddle_vl_engine
                self._paddle_vl_ocr = get_paddle_vl_engine()
            return self._paddle_vl_ocr
        elif target_engine == OCREngine.RAPID_OCR:
            if self._rapid_ocr is None:
                from .rapid_engine import get_rapid_engine
                self._rapid_ocr = get_rapid_engine()
            return self._rapid_ocr
        elif target_engine == OCREngine.MANGA_OCR:
            if self._manga_ocr is None:
                from .manga_engine import get_manga_engine
                self._manga_ocr = get_manga_engine()
            return self._manga_ocr
        elif target_engine == OCREngine.SURYA:
            if self._surya_ocr is None:
                from .surya_engine import get_surya_engine
                self._surya_ocr = get_surya_engine()
            return self._surya_ocr
        return None

    def is_engine_loaded(self, engine: OCREngine) -> bool:
        """Return True when the requested engine already has a loaded model."""
        instance = self._get_engine_instance(engine)
        return instance is not None and instance.is_loaded

    def is_engine_loading(self, engine: OCREngine) -> bool:
        """Return True when the requested engine is still loading."""
        instance = self._get_engine_instance(engine)
        return instance is not None and instance.is_loading

    def load_engine_async(
        self,
        engine: OCREngine,
        callback: Optional[Callable[[bool, Optional[str]], None]] = None,
    ) -> None:
        """Load a specific engine asynchronously without changing the active engine."""
        instance = self._get_engine_instance(engine)
        if instance:
            log_info(f"Loading {get_engine_name(engine)} model...")
            instance.load_model_async(callback)
        elif callback:
            callback(False, "No engine available")

    def load_engine_blocking(
        self,
        engine: OCREngine,
        timeout: Optional[float] = None,
    ) -> tuple[bool, Optional[str]]:
        """Load a specific engine and wait until it finishes loading."""
        instance = self._get_engine_instance(engine)
        if instance is None:
            return False, "No engine available"
        if instance.is_loaded:
            return True, instance.load_error

        instance.load_model_async()
        wait_for_load = getattr(instance, "wait_for_load", None)
        if callable(wait_for_load):
            wait_for_load(timeout)
        return instance.is_loaded, instance.load_error

    def set_paddle_profile(self, profile: str) -> str:
        """Set the active PaddleOCR performance profile."""
        instance = self._get_engine_instance(OCREngine.PADDLE_OCR)
        if instance is None:
            from .paddle_engine import normalize_paddle_profile
            return normalize_paddle_profile(profile)
        return instance.set_profile(profile)

    def get_paddle_profile(self) -> str:
        """Return the active PaddleOCR performance profile."""
        instance = self._get_engine_instance(OCREngine.PADDLE_OCR)
        if instance is None:
            from .paddle_engine import DEFAULT_PADDLE_PROFILE
            return DEFAULT_PADDLE_PROFILE
        return instance.profile

    def set_engine(self, engine: OCREngine) -> None:
        """Set the active OCR engine while keeping previously loaded models cached."""
        if engine != self._current_engine:
            log_info(f"Switching OCR engine from {self._current_engine.value} to {engine.value}")
            self._current_engine = engine

    def load_model_async(self, callback: Optional[Callable[[bool, Optional[str]], None]] = None) -> None:
        """Load the current engine's model asynchronously."""
        engine = self._get_engine_instance()
        if engine:
            log_info(f"Loading {get_engine_name(self._current_engine)} model...")
            engine.load_model_async(callback)
        elif callback:
            callback(False, "No engine available")

    def perform_ocr(self, image: Image.Image) -> str:
        """Perform OCR using the current engine."""
        engine = self._get_engine_instance()
        if engine is None:
            raise RuntimeError("No OCR engine available")
        if not engine.is_loaded:
            raise RuntimeError(f"{get_engine_name(self._current_engine)} model not loaded")
        return engine.perform_ocr(image)

    def perform_ocr_with_engine(self, target_engine: OCREngine, image: Image.Image) -> str:
        """Perform OCR using a specific engine snapshot instead of the mutable current engine."""
        engine = self._get_engine_instance(target_engine)
        if engine is None:
            raise RuntimeError(f"No OCR engine available for {get_engine_name(target_engine)}")
        if not engine.is_loaded:
            raise RuntimeError(f"{get_engine_name(target_engine)} model not loaded")
        return engine.perform_ocr(image)

    def perform_ocr_analysis(self, image: Image.Image) -> OCRAnalysisResult:
        """Perform OCR using the current engine and include confidence metadata when available."""
        return self.perform_ocr_analysis_with_engine(self._current_engine, image)

    def perform_ocr_analysis_with_engine(
        self,
        target_engine: OCREngine,
        image: Image.Image,
    ) -> OCRAnalysisResult:
        """Perform OCR with a specific engine and return structured result metadata."""
        engine = self._get_engine_instance(target_engine)
        if engine is None:
            raise RuntimeError(f"No OCR engine available for {get_engine_name(target_engine)}")
        if not engine.is_loaded:
            raise RuntimeError(f"{get_engine_name(target_engine)} model not loaded")

        perform_analysis = getattr(engine, "perform_ocr_analysis", None)
        if callable(perform_analysis):
            analysis = perform_analysis(image)
            if isinstance(analysis, OCRAnalysisResult):
                return analysis
            if isinstance(analysis, dict):
                return OCRAnalysisResult(
                    text=str(analysis.get("text", "") or ""),
                    average_confidence=analysis.get("average_confidence"),
                    used_retry=bool(analysis.get("used_retry", False)),
                )

        return OCRAnalysisResult(text=engine.perform_ocr(image))

    def crop_image_to_text(self, image: Image.Image) -> tuple[Image.Image, Optional[tuple[int, int, int, int]]]:
        """Crop an image to detected text bounds when the active engine supports it."""
        engine = self._get_engine_instance()
        if engine is None or not hasattr(engine, "crop_to_detected_text"):
            return image, None
        return engine.crop_to_detected_text(image)

    def crop_image_to_text_with_engine(
        self,
        target_engine: OCREngine,
        image: Image.Image,
    ) -> tuple[Image.Image, Optional[tuple[int, int, int, int]]]:
        """Crop using a specific engine snapshot when that engine supports detector-backed cropping."""
        engine = self._get_engine_instance(target_engine)
        if engine is None or not hasattr(engine, "crop_to_detected_text"):
            return image, None
        return engine.crop_to_detected_text(image)

    def unload_current(self) -> None:
        """Unload the current engine."""
        engine = self._get_engine_instance()
        if engine and engine.is_loaded:
            log_info(f"Unloading {get_engine_name(self._current_engine)} model...")
            engine.unload_model()

    def unload_engine(self, engine: OCREngine) -> None:
        """Unload a specific engine without changing the active engine selection."""
        instance = self._get_engine_instance(engine)
        if instance and instance.is_loaded:
            log_info(f"Unloading {get_engine_name(engine)} model...")
            instance.unload_model()

    def unload_all(self, wait_timeout_sec: float = 0.0) -> None:
        """Unload every instantiated engine that can be released immediately."""
        deadline = time.monotonic() + max(0.0, wait_timeout_sec)

        for engine, instance in self._engine_instances():
            if instance is None:
                continue
            if getattr(instance, "is_loading", False):
                wait_for_load = getattr(instance, "wait_for_load", None)
                remaining = max(0.0, deadline - time.monotonic())
                if callable(wait_for_load) and remaining > 0:
                    log_info(
                        f"Waiting up to {remaining:.1f}s for "
                        f"{get_engine_name(engine)} to finish loading before unload..."
                    )
                    wait_for_load(remaining)

            if getattr(instance, "is_loading", False):
                log_warning(
                    f"{get_engine_name(engine)} is still loading during shutdown; "
                    "process exit will release it."
                )
                continue

            unload_model = getattr(instance, "unload_model", None)
            if not callable(unload_model):
                continue

            try:
                log_info(f"Unloading {get_engine_name(engine)} model...")
                unload_model()
            except Exception as exc:
                log_error(f"Failed to unload {get_engine_name(engine)}: {exc}")

        try:
            import gc

            gc.collect()
        except Exception:
            pass


_manager: Optional[OCRManager] = None


def get_ocr_manager() -> OCRManager:
    """Get the global OCR manager instance."""
    global _manager
    if _manager is None:
        _manager = OCRManager()
    return _manager
