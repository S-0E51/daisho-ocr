"""
RapidOCR Engine - Optional ONNX Runtime-backed Japanese OCR wrapper.

RapidOCR is useful as a lightweight CPU fallback because it runs Paddle-style
OCR models through ONNX Runtime without importing PaddlePaddle at inference time.
"""

from __future__ import annotations

import os
import threading
from typing import Any, Callable, Optional

import numpy as np
from PIL import Image

from ..utils.logger import log_debug, log_error, log_info
from .types import OCRAnalysisResult


os.environ.setdefault("ORT_LOG_SEVERITY_LEVEL", "3")


class RapidOCRWrapper:
    """Wrapper for RapidOCR with Japanese PP-OCRv5 recognition settings."""

    _instance: Optional[RapidOCRWrapper] = None
    _lock = threading.Lock()
    _initialized = False

    def __new__(cls) -> RapidOCRWrapper:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        with RapidOCRWrapper._lock:
            if RapidOCRWrapper._initialized:
                return

            self._ocr = None
            self._is_loaded = False
            self._is_loading = False
            self._load_error: Optional[str] = None
            self._load_lock = threading.Lock()
            self._load_event = threading.Event()

            RapidOCRWrapper._initialized = True

    @property
    def is_loaded(self) -> bool:
        return self._is_loaded

    @property
    def is_loading(self) -> bool:
        return self._is_loading

    @property
    def load_error(self) -> Optional[str]:
        return self._load_error

    @property
    def uses_gpu(self) -> bool:
        return False

    def load_model_async(self, callback: Optional[Callable[[bool, Optional[str]], None]] = None) -> None:
        """Load RapidOCR in a background thread."""
        if self._is_loaded:
            if callback:
                callback(self._is_loaded, self._load_error)
            return

        if self._is_loading:
            if callback:
                def wait_thread() -> None:
                    self.wait_for_load()
                    callback(self._is_loaded, self._load_error)

                thread = threading.Thread(target=wait_thread, daemon=True)
                thread.start()
            return

        self._is_loading = True
        self._load_error = None
        self._load_event.clear()

        def load_thread() -> None:
            self._load_model_sync()
            if callback:
                callback(self._is_loaded, self._load_error)

        thread = threading.Thread(target=load_thread, daemon=True)
        thread.start()

    def _load_model_sync(self) -> None:
        """Synchronously initialize RapidOCR."""
        with self._load_lock:
            if self._is_loaded:
                return

            self._is_loading = True
            self._load_error = None
            self._load_event.clear()

            try:
                log_info("Loading RapidOCR Japanese ONNX engine...")
                log_info("Note: First run may download RapidOCR model files. Please wait...")

                from rapidocr import RapidOCR

                params = self._build_rapidocr_params()
                self._ocr = RapidOCR(params=params)
                self._is_loaded = True
                log_info("RapidOCR loaded successfully!")

            except ImportError as e:
                self._load_error = (
                    "RapidOCR is not installed.\n"
                    "Please run: pip install rapidocr onnxruntime"
                )
                log_error(f"Import error: {e}")

            except Exception as e:
                self._load_error = f"Error loading RapidOCR: {e}"
                log_error(f"Error loading RapidOCR: {e}")

            finally:
                self._is_loading = False
                self._load_event.set()

    def _build_rapidocr_params(self) -> dict[str, Any]:
        """Build params with enum values when the installed RapidOCR exposes them."""
        params: dict[str, Any] = {
            "Global.text_score": 0.45,
            "Global.use_det": True,
            "Global.use_cls": True,
            "Global.use_rec": True,
            "Global.max_side_len": 1600,
            "Global.min_side_len": 24,
        }

        try:
            from rapidocr import EngineType, LangRec, ModelType, OCRVersion

            params.update({
                "Det.engine_type": EngineType.ONNXRUNTIME,
                "Cls.engine_type": EngineType.ONNXRUNTIME,
                "Rec.engine_type": EngineType.ONNXRUNTIME,
                "Rec.lang_type": LangRec.JAPAN,
                "Rec.model_type": ModelType.MOBILE,
                "Rec.ocr_version": OCRVersion.PPOCRV5,
            })
        except Exception as e:
            log_debug(f"RapidOCR enum configuration unavailable, using defaults: {e}")
            params.update({
                "Rec.lang_type": "japan",
                "Rec.model_type": "mobile",
                "Rec.ocr_version": "PP-OCRv5",
            })

        return params

    def wait_for_load(self, timeout: Optional[float] = None) -> bool:
        """Wait for the model to finish loading."""
        self._load_event.wait(timeout)
        return self._is_loaded

    def perform_ocr_analysis(self, image: Image.Image) -> OCRAnalysisResult:
        """Perform OCR on a PIL Image and return confidence metadata."""
        if not self._is_loaded:
            if self._load_error:
                raise RuntimeError(f"OCR model failed to load: {self._load_error}")
            raise RuntimeError("OCR model not loaded. Call load_model_async() first.")

        if self._ocr is None:
            raise RuntimeError("RapidOCR model is None despite being marked as loaded")

        try:
            if image.mode != "RGB":
                image = image.convert("RGB")

            img_array = np.asarray(image)[:, :, ::-1]
            result = self._ocr(img_array)
            text, scores = self._extract_text_and_scores(result)
            average_confidence = float(sum(scores) / len(scores)) if scores else None
            log_debug(f"RapidOCR extracted {len(text)} characters")
            return OCRAnalysisResult(
                text=text,
                average_confidence=average_confidence,
            )

        except Exception as e:
            log_error(f"RapidOCR inference error: {e}")
            raise RuntimeError(f"OCR inference failed: {e}")

    def perform_ocr(self, image: Image.Image) -> str:
        """Perform OCR on a PIL Image and return text only."""
        return self.perform_ocr_analysis(image).text

    def _extract_text_and_scores(self, result: Any) -> tuple[str, list[float]]:
        """Normalize RapidOCR 3.x and legacy output shapes."""
        if isinstance(result, tuple) and len(result) >= 1:
            result = result[0]

        texts: list[str] = []
        scores: list[float] = []

        result_texts = getattr(result, "txts", None)
        if result_texts is not None:
            texts.extend(str(text) for text in result_texts if text)
            for score in getattr(result, "scores", ()) or ():
                parsed_score = self._coerce_score(score)
                if parsed_score is not None:
                    scores.append(parsed_score)
            return "".join(texts).strip(), scores

        if isinstance(result, list):
            for item in result:
                if not isinstance(item, (list, tuple)) or len(item) < 2:
                    continue
                text = item[1]
                if text:
                    texts.append(str(text))
                if len(item) >= 3:
                    parsed_score = self._coerce_score(item[2])
                    if parsed_score is not None:
                        scores.append(parsed_score)

        return "".join(texts).strip(), scores

    def _coerce_score(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def unload_model(self) -> None:
        """Unload RapidOCR to free memory."""
        with self._load_lock:
            self._ocr = None
            self._is_loaded = False
            self._is_loading = False
            self._load_error = None
            self._load_event.clear()
            log_info("RapidOCR unloaded")


def get_rapid_engine() -> RapidOCRWrapper:
    """Get the singleton RapidOCR engine instance."""
    return RapidOCRWrapper()
