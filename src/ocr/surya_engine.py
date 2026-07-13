"""
Surya OCR Engine - Optional line-aware OCR wrapper.

Thread-safe singleton with async loading, GPU/CPU detection, and
defensive result parsing for Surya's prediction objects.
"""

from __future__ import annotations
import os
import threading
import warnings
from typing import Any, Optional, Callable
from PIL import Image

from ..utils.logger import log_info, log_error, log_debug, log_warning
from .types import OCRAnalysisResult

# Surya's default GPU batch size targets large document workloads. Use a
# smaller default so a desktop OCR helper does not over-allocate VRAM.
os.environ.setdefault("RECOGNITION_BATCH_SIZE", "16")


class SuryaOCRWrapper:
    """Wrapper for Surya OCR with Japanese-focused screenshot recognition."""

    _instance: Optional[SuryaOCRWrapper] = None
    _lock = threading.Lock()
    _initialized = False

    def __new__(cls) -> SuryaOCRWrapper:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        with SuryaOCRWrapper._lock:
            if SuryaOCRWrapper._initialized:
                return

            self._foundation_predictor = None
            self._recognition_predictor = None
            self._detection_predictor = None
            self._is_loaded = False
            self._is_loading = False
            self._load_error: Optional[str] = None
            self._load_lock = threading.Lock()
            self._load_event = threading.Event()
            self._use_gpu = False

            SuryaOCRWrapper._initialized = True

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
        return self._use_gpu

    def load_model_async(self, callback: Optional[Callable[[bool, Optional[str]], None]] = None) -> None:
        """Load the Surya model in a background thread."""
        if self._is_loaded:
            if callback:
                callback(self._is_loaded, self._load_error)
            return

        if self._is_loading:
            if callback:
                def wait_thread():
                    self.wait_for_load()
                    callback(self._is_loaded, self._load_error)

                thread = threading.Thread(target=wait_thread, daemon=True)
                thread.start()
            return

        self._is_loading = True
        self._load_error = None
        self._load_event.clear()

        def load_thread():
            self._load_model_sync()
            if callback:
                callback(self._is_loaded, self._load_error)

        thread = threading.Thread(target=load_thread, daemon=True)
        thread.start()

    def _load_model_sync(self) -> None:
        """Synchronously load the Surya OCR predictors."""
        with self._load_lock:
            if self._is_loaded:
                return

            self._is_loading = True
            self._load_error = None
            self._load_event.clear()

            try:
                log_info("Loading Surya OCR predictors...")
                log_info("Note: First run may download Surya weights. Please wait...")
                self._apply_surya_decoder_token_compatibility()

                try:
                    import torch
                    if torch.cuda.is_available():
                        self._use_gpu = True
                        log_info(f"CUDA available: {torch.cuda.get_device_name(0)}")
                    else:
                        log_info("CUDA not available, using CPU")
                except ImportError:
                    log_warning("PyTorch not found for GPU check")

                from surya.foundation import FoundationPredictor
                from surya.recognition import RecognitionPredictor
                from surya.detection import DetectionPredictor

                self._foundation_predictor = FoundationPredictor()
                self._recognition_predictor = RecognitionPredictor(self._foundation_predictor)
                self._detection_predictor = DetectionPredictor()

                self._is_loaded = True
                log_info("Surya OCR loaded successfully!")

            except ImportError as e:
                self._load_error = (
                    "Surya OCR is not installed.\n"
                    "Please run: pip install surya-ocr"
                )
                log_error(f"Import error: {e}")

            except Exception as e:
                self._load_error = f"Error loading Surya OCR: {e}"
                log_error(f"Error loading Surya OCR: {e}")

            finally:
                self._is_loading = False
                self._load_event.set()

    def _apply_surya_decoder_token_compatibility(self) -> None:
        """
        Patch Surya's decoder config for Transformers builds that no longer add
        default special-token attributes to nested decoder configs.
        """
        try:
            from surya.common.surya.decoder.config import SuryaDecoderConfig
        except Exception as exc:
            log_debug(f"Surya decoder compatibility patch skipped: {exc}")
            return

        if getattr(SuryaDecoderConfig, "_daisho_token_patch_applied", False):
            return

        original_init = SuryaDecoderConfig.__init__

        def patched_init(config_self, *args, **kwargs):
            pad_token_id = kwargs.get("pad_token_id", 2)
            bos_token_id = kwargs.get("bos_token_id", 0)
            eos_token_id = kwargs.get("eos_token_id", 1)
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message=".*rope_config_validation.*",
                    category=FutureWarning,
                )
                original_init(config_self, *args, **kwargs)
            if getattr(config_self, "pad_token_id", None) is None:
                config_self.pad_token_id = pad_token_id
            if getattr(config_self, "bos_token_id", None) is None:
                config_self.bos_token_id = bos_token_id
            if getattr(config_self, "eos_token_id", None) is None:
                config_self.eos_token_id = eos_token_id

        SuryaDecoderConfig.__init__ = patched_init
        SuryaDecoderConfig.pad_token_id = 2
        SuryaDecoderConfig.bos_token_id = 0
        SuryaDecoderConfig.eos_token_id = 1
        SuryaDecoderConfig._daisho_token_patch_applied = True
        log_debug("Applied Surya decoder token compatibility patch")

    def wait_for_load(self, timeout: Optional[float] = None) -> bool:
        """Wait for the model to finish loading."""
        self._load_event.wait(timeout)
        return self._is_loaded

    def perform_ocr_analysis(self, image: Image.Image) -> OCRAnalysisResult:
        """Perform OCR on a PIL Image and include Surya line confidence."""
        if not self._is_loaded:
            if self._load_error:
                raise RuntimeError(f"OCR model failed to load: {self._load_error}")
            raise RuntimeError("OCR model not loaded. Call load_model_async() first.")

        if self._recognition_predictor is None or self._detection_predictor is None:
            raise RuntimeError("Surya OCR predictors are not initialized")

        try:
            if image.mode != "RGB":
                image = image.convert("RGB")

            predictions = self._recognition_predictor(
                [image],
                det_predictor=self._detection_predictor,
            )
            log_debug(f"Surya OCR returned {len(predictions) if predictions else 0} page predictions")

            if not predictions:
                return OCRAnalysisResult(text="")

            lines: list[str] = []
            confidences: list[float] = []
            for prediction in predictions:
                extracted_lines, extracted_confidences = self._extract_text_lines_with_scores(prediction)
                lines.extend(extracted_lines)
                confidences.extend(extracted_confidences)

            full_text = "\n".join(line for line in lines if line.strip()).strip()
            log_debug(f"Surya OCR extracted {len(full_text)} characters")
            average_confidence = (
                float(sum(confidences) / len(confidences))
                if confidences
                else None
            )
            return OCRAnalysisResult(
                text=full_text,
                average_confidence=average_confidence,
            )

        except Exception as e:
            log_error(f"Surya OCR inference error: {e}")
            raise RuntimeError(f"OCR inference failed: {e}")

    def perform_ocr(self, image: Image.Image) -> str:
        """Perform OCR on a PIL Image and return text only."""
        return self.perform_ocr_analysis(image).text

    def _extract_text_lines(self, prediction: Any) -> list[str]:
        """Extract recognized text lines from a Surya page prediction."""
        lines, _ = self._extract_text_lines_with_scores(prediction)
        return lines

    def _extract_text_lines_with_scores(self, prediction: Any) -> tuple[list[str], list[float]]:
        """Extract recognized text lines and confidence scores from a Surya page prediction."""
        prediction_data = self._to_mapping(prediction)
        text_lines = self._get_field(prediction, prediction_data, "text_lines") or []

        if not text_lines:
            fallback_text = self._get_field(prediction, prediction_data, "text")
            if fallback_text:
                return [str(fallback_text).strip()], []
            return [], []

        lines = []
        confidences = []
        for line in text_lines:
            line_data = self._to_mapping(line)
            text = self._get_field(line, line_data, "text")
            confidence = self._get_field(line, line_data, "confidence")
            parsed_confidence = self._coerce_confidence(confidence)
            if text and (parsed_confidence is None or parsed_confidence >= 0.2):
                lines.append(str(text).strip())
                if parsed_confidence is not None:
                    confidences.append(parsed_confidence)
        return lines, confidences

    def _coerce_confidence(self, value: Any) -> Optional[float]:
        """Convert a confidence-like value to float when Surya supplies one."""
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _to_mapping(self, value: Any) -> dict[str, Any]:
        """Convert Surya prediction objects to a dictionary when possible."""
        if isinstance(value, dict):
            return value
        if hasattr(value, "model_dump"):
            try:
                dumped = value.model_dump()
                if isinstance(dumped, dict):
                    return dumped
            except Exception:
                pass
        if hasattr(value, "dict"):
            try:
                dumped = value.dict()
                if isinstance(dumped, dict):
                    return dumped
            except Exception:
                pass
        if hasattr(value, "__dict__"):
            try:
                return {
                    key: val
                    for key, val in vars(value).items()
                    if not key.startswith("_")
                }
            except Exception:
                pass
        return {}

    def _get_field(self, raw_value: Any, mapped_value: dict[str, Any], field: str) -> Any:
        """Read a field from either an object-like or mapping-like result."""
        if field in mapped_value:
            return mapped_value[field]
        return getattr(raw_value, field, None)

    def unload_model(self) -> None:
        """Unload the model to free memory."""
        with self._load_lock:
            self._detection_predictor = None
            self._recognition_predictor = None
            self._foundation_predictor = None

            self._is_loaded = False
            self._is_loading = False
            self._load_error = None
            self._load_event.clear()

            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass

            log_info("Surya OCR unloaded")


def get_surya_engine() -> SuryaOCRWrapper:
    """Get the singleton Surya OCR engine instance."""
    return SuryaOCRWrapper()
