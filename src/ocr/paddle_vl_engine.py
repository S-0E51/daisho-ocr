"""
PaddleOCR-VL Engine - 0.9B vision-language OCR (detection + recognition in one).

A general-purpose one-stop engine: SOTA on vertical Japanese, 109 languages, and
strong on games/VNs/documents. Wraps the ``PaddleOCRVL`` pipeline from the same
``paddleocr`` toolkit used by the PP-OCRv5 engine, so it reuses the Windows
workarounds proven in ``paddle_engine.py``.

Module-level workarounds (must happen before any paddle import):
1. FLAGS_use_mkldnn=0 - avoids the PIR attribute conversion bug in PaddlePaddle 3.x.
2. torch imported before paddle - avoids Windows DLL search-path conflicts.
3. DISABLE_MODEL_SOURCE_CHECK - skips the slow model-hoster connectivity check.

It also installs a surgical numpy>=2 compatibility shim for paddle's tensor->int
converter (see _patch_paddle_numpy2).
"""

from __future__ import annotations
import os
import threading
from typing import Optional, Callable
from PIL import Image
import numpy as np

# --- Environment workarounds (must be set BEFORE importing paddle) ---
os.environ["FLAGS_use_mkldnn"] = "0"
os.environ["FLAGS_use_onednn"] = "0"
os.environ["MKLDNN_DISABLE"] = "1"
os.environ.setdefault("DISABLE_MODEL_SOURCE_CHECK", "True")

# Import torch BEFORE paddle on Windows to prevent DLL search path conflicts.
try:
    import torch  # noqa: F401
except ImportError:
    pass

# Import paddle at module load (in the importing thread — the main/UI thread) and
# force dynamic (eager) graph mode. The PaddleOCR-VL generation path relies on
# dynamic mode (`int(Tensor)`); if paddle is first initialized on a background
# worker thread, predict() runs in static-graph mode and fails. This is a no-op
# for PP-OCRv5, which already runs in the default dynamic mode.
try:
    import paddle  # noqa: F401
    paddle.disable_static()
except Exception:
    pass

from ..utils.logger import log_info, log_error, log_debug, log_warning
from .types import OCRAnalysisResult


_numpy2_patch_applied = False


def _patch_paddle_numpy2() -> None:
    """Add a numpy>=2 fallback to paddle's Tensor.__int__/__float__.

    PaddlePaddle 3.2.0 converts a scalar tensor with ``int(np.array(var))``, which
    numpy>=2 rejects for a 1-element but non-0-dimensional array (raising
    "only 0-dimensional arrays can be converted to Python scalars"). The
    PaddleOCR-VL preprocessor hits this on ``int(image_grid_thw[i].prod() // ...)``.

    The shim only adds a fallback for that exact ``TypeError`` — any conversion
    that already works (e.g. PP-OCRv5's) is passed straight through, so behaviour
    is unchanged for every other engine.
    """
    global _numpy2_patch_applied
    if _numpy2_patch_applied:
        return
    try:
        import paddle

        orig_int = paddle.Tensor.__int__
        orig_float = paddle.Tensor.__float__

        def _safe_int(var):
            try:
                return orig_int(var)
            except TypeError:
                return int(np.asarray(var).reshape(-1)[0])

        def _safe_float(var):
            try:
                return orig_float(var)
            except TypeError:
                return float(np.asarray(var).reshape(-1)[0])

        paddle.Tensor.__int__ = _safe_int
        paddle.Tensor.__float__ = _safe_float
        _numpy2_patch_applied = True
        log_debug("Applied numpy>=2 compatibility shim for paddle Tensor int/float")
    except Exception as exc:
        log_debug(f"Could not apply paddle numpy2 shim: {exc}")


class PaddleVLWrapper:
    """Singleton wrapper for the PaddleOCR-VL pipeline (thread-safe async load)."""

    _instance: Optional["PaddleVLWrapper"] = None
    _lock = threading.Lock()
    _initialized = False

    def __new__(cls) -> "PaddleVLWrapper":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        with PaddleVLWrapper._lock:
            if PaddleVLWrapper._initialized:
                return
            self._pipeline = None
            self._is_loaded = False
            self._is_loading = False
            self._load_error: Optional[str] = None
            self._load_lock = threading.Lock()
            self._load_event = threading.Event()
            self._use_gpu = False
            PaddleVLWrapper._initialized = True

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
        """Load the PaddleOCR-VL pipeline in a background thread."""
        if self._is_loaded:
            if callback:
                callback(self._is_loaded, self._load_error)
            return

        if self._is_loading:
            if callback:
                def wait_thread():
                    self.wait_for_load()
                    callback(self._is_loaded, self._load_error)

                threading.Thread(target=wait_thread, daemon=True).start()
            return

        self._is_loading = True
        self._load_error = None
        self._load_event.clear()

        def load_thread():
            self._load_model_sync()
            if callback:
                callback(self._is_loaded, self._load_error)

        threading.Thread(target=load_thread, daemon=True).start()

    def _load_model_sync(self) -> None:
        with self._load_lock:
            if self._is_loaded:
                return

            self._is_loading = True
            self._load_error = None
            self._load_event.clear()

            try:
                _patch_paddle_numpy2()

                try:
                    import paddle
                    if paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0:
                        self._use_gpu = True
                        log_info("PaddleOCR-VL: CUDA available, using GPU")
                    else:
                        log_info("PaddleOCR-VL: using CPU (a VLM on CPU is slow; GPU recommended)")
                except Exception as exc:
                    log_debug(f"PaddleOCR-VL GPU check failed: {exc}")

                from paddleocr import PaddleOCRVL

                log_info("Loading PaddleOCR-VL (first run downloads ~1GB of weights)...")
                device = "gpu" if self._use_gpu else "cpu"
                try:
                    self._pipeline = PaddleOCRVL(device=device)
                except TypeError:
                    # Older signature without an explicit device kwarg (auto-detects).
                    self._pipeline = PaddleOCRVL()

                self._is_loaded = True
                log_info("PaddleOCR-VL loaded successfully!")

            except ImportError as e:
                self._load_error = (
                    "PaddleOCR-VL requires the paddlex OCR extras.\n"
                    "Install with: pip install \"paddlex[ocr]\""
                )
                log_error(f"PaddleOCR-VL import error: {e}")
            except Exception as e:
                msg = str(e)
                if "paddlex[ocr]" in msg or "DependencyError" in msg or "additional dependencies" in msg:
                    self._load_error = (
                        "PaddleOCR-VL requires the paddlex OCR extras.\n"
                        "Install with: pip install \"paddlex[ocr]\""
                    )
                else:
                    self._load_error = f"Error loading PaddleOCR-VL: {e}"
                log_error(f"Error loading PaddleOCR-VL: {e}")
            finally:
                self._is_loading = False
                self._load_event.set()

    def wait_for_load(self, timeout: Optional[float] = None) -> bool:
        self._load_event.wait(timeout)
        return self._is_loaded

    @staticmethod
    def _extract_text(results) -> str:
        """Join recognized block text in reading order (block_order)."""
        parts: list[str] = []
        for res in results:
            data = None
            payload = getattr(res, "json", None)
            if isinstance(payload, dict):
                data = payload.get("res", payload)

            blocks = data.get("parsing_res_list") if isinstance(data, dict) else None
            if blocks:
                for block in sorted(blocks, key=lambda b: b.get("block_order", 0)):
                    content = str(block.get("block_content", "")).strip()
                    if content:
                        parts.append(content)
                continue

            # Fallback: markdown text (strip a leading heading marker).
            markdown = getattr(res, "markdown", None)
            if isinstance(markdown, dict):
                text = str(markdown.get("markdown_texts", "")).strip()
                text = text.lstrip("#").strip()
                if text:
                    parts.append(text)

        return "\n".join(parts).strip()

    def perform_ocr_analysis(self, image: Image.Image) -> OCRAnalysisResult:
        if not self._is_loaded:
            if self._load_error:
                raise RuntimeError(f"OCR model failed to load: {self._load_error}")
            raise RuntimeError("OCR model not loaded. Call load_model_async() first.")
        if self._pipeline is None:
            raise RuntimeError("PaddleOCR-VL pipeline is None despite being marked as loaded")

        try:
            # Ensure this thread runs in dynamic (eager) mode; the OCR pipeline is
            # invoked from the capture-worker thread, which must not be static.
            try:
                import paddle
                paddle.disable_static()
            except Exception:
                pass

            if image.mode != "RGB":
                image = image.convert("RGB")
            img_array = np.asarray(image)

            results = list(self._pipeline.predict(img_array))
            text = self._extract_text(results)
            log_debug(f"PaddleOCR-VL extracted {len(text)} characters")
            # The VLM does not expose per-token confidence; leave it unset.
            return OCRAnalysisResult(text=text, average_confidence=None)
        except Exception as e:
            log_error(f"PaddleOCR-VL inference error: {e}")
            raise RuntimeError(f"OCR inference failed: {e}")

    def perform_ocr(self, image: Image.Image) -> str:
        return self.perform_ocr_analysis(image).text

    def unload_model(self) -> None:
        with self._load_lock:
            self._pipeline = None
            self._is_loaded = False
            self._is_loading = False
            self._load_error = None
            self._load_event.clear()
            try:
                import paddle
                paddle.device.cuda.empty_cache()
            except Exception:
                pass
            log_info("PaddleOCR-VL model unloaded")


def get_paddle_vl_engine() -> PaddleVLWrapper:
    """Get the singleton PaddleOCR-VL engine instance."""
    return PaddleVLWrapper()
