"""
manga-ocr Engine - Singleton wrapper for the Vision Encoder-Decoder model.

Thread-safe singleton with async loading, GPU/CPU detection, and error handling.
"""

from __future__ import annotations
import sys
import io
import threading
from typing import Optional, Callable, TYPE_CHECKING
from PIL import Image

from ..utils.logger import log_info, log_error, log_debug, log_warning


def _ensure_stdio() -> None:
    """Ensure sys.stdout and sys.stderr exist (needed for pythonw.exe)."""
    if sys.stdout is None:
        sys.stdout = io.StringIO()
    if sys.stderr is None:
        sys.stderr = io.StringIO()

if TYPE_CHECKING:
    from manga_ocr import MangaOcr


class MangaOCRWrapper:
    """
    Singleton wrapper for manga-ocr model.

    The model is loaded once and reused across all OCR operations.
    Thread-safe initialization ensures only one model instance exists.
    """

    _instance: Optional[MangaOCRWrapper] = None
    _lock = threading.Lock()
    _initialized = False

    def __new__(cls) -> MangaOCRWrapper:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        with MangaOCRWrapper._lock:
            if MangaOCRWrapper._initialized:
                return

            self._mocr: Optional[MangaOcr] = None
            self._is_loaded = False
            self._is_loading = False
            self._load_error: Optional[str] = None
            self._load_lock = threading.Lock()
            self._load_event = threading.Event()
            self._use_gpu = False
            self._fp16 = False

            MangaOCRWrapper._initialized = True

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
        """Load the manga-ocr model in a background thread."""
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
        """Synchronously load the manga-ocr model."""
        with self._load_lock:
            if self._is_loaded:
                return

            self._is_loading = True
            self._load_error = None
            self._load_event.clear()

            try:
                log_info("Loading manga-ocr model...")
                log_info("Note: First run may download model (~400MB). Please wait...")

                try:
                    import torch
                    if torch.cuda.is_available():
                        self._use_gpu = True
                        gpu_name = torch.cuda.get_device_name(0)
                        log_info(f"CUDA available: {gpu_name}")
                        # Enable cuDNN autotuner for faster convolutions
                        torch.backends.cudnn.benchmark = True
                    else:
                        log_info("CUDA not available, using CPU")
                except ImportError:
                    log_warning("PyTorch not found for GPU check")

                _ensure_stdio()

                from manga_ocr import MangaOcr

                log_info("Initializing manga-ocr model (downloading if needed)...")
                self._mocr = MangaOcr()

                # GPU optimizations: FP16 and torch.compile
                if self._use_gpu:
                    self._apply_gpu_optimizations()

                self._is_loaded = True
                log_info("manga-ocr model loaded successfully!")

            except ImportError as e:
                self._load_error = (
                    "manga-ocr is not installed.\n"
                    "Please run: pip install manga-ocr"
                )
                log_error(f"Import error: {e}")

            except RuntimeError as e:
                error_str = str(e)
                if "CUDA" in error_str or "GPU" in error_str:
                    self._load_error = (
                        f"GPU/CUDA error: {e}\n\n"
                        "Try installing CPU-only PyTorch:\n"
                        "  pip uninstall torch\n"
                        "  pip install torch --index-url https://download.pytorch.org/whl/cpu"
                    )
                else:
                    self._load_error = f"Runtime error loading model: {e}"
                log_error(f"Runtime error: {e}")

            except Exception as e:
                import platform
                if platform.system() == "Windows" and ("DLL" in str(e) or "WinError" in str(e)):
                    self._load_error = (
                        "A required system library is missing.\n\n"
                        "Solutions:\n"
                        "1. Install Microsoft Visual C++ Redistributable\n"
                        "2. Try CPU-only PyTorch:\n"
                        "   pip uninstall torch\n"
                        "   pip install torch --index-url https://download.pytorch.org/whl/cpu"
                    )
                else:
                    self._load_error = f"Unexpected error: {e}"
                log_error(f"Error loading model: {e}")

            finally:
                self._is_loading = False
                self._load_event.set()

    def _apply_gpu_optimizations(self) -> None:
        """Apply FP16 and torch.compile optimizations for GPU inference."""
        try:
            import torch

            model = getattr(self._mocr, 'model', None)
            if model is None:
                log_debug("Could not access manga-ocr internal model for optimization")
                return

            # FP16 (half precision) — roughly 2x speedup on modern GPUs
            try:
                model.half()
                self._fp16 = True
                log_info("manga-ocr: FP16 (half precision) enabled")
            except Exception as e:
                self._fp16 = False
                log_warning(f"FP16 conversion failed, using FP32: {e}")

            # torch.compile (PyTorch 2.x) — JIT optimization
            if hasattr(torch, 'compile'):
                try:
                    compiled = torch.compile(model, mode="reduce-overhead")
                    self._mocr.model = compiled
                    log_info("manga-ocr: torch.compile enabled (reduce-overhead)")
                except Exception as e:
                    log_debug(f"torch.compile not available: {e}")

        except Exception as e:
            log_debug(f"GPU optimization failed: {e}")

    def wait_for_load(self, timeout: Optional[float] = None) -> bool:
        """Wait for the model to finish loading."""
        self._load_event.wait(timeout)
        return self._is_loaded

    def perform_ocr(self, image: Image.Image) -> str:
        """Perform OCR on a PIL Image."""
        if not self._is_loaded:
            if self._load_error:
                raise RuntimeError(f"OCR model failed to load: {self._load_error}")
            raise RuntimeError("OCR model not loaded. Call load_model_async() first.")

        if self._mocr is None:
            raise RuntimeError("OCR model is None despite being marked as loaded")

        try:
            if image.mode != 'RGB':
                image = image.convert('RGB')

            if self._use_gpu:
                import torch
                with torch.inference_mode():
                    result = self._mocr(image)
            else:
                result = self._mocr(image)

            return result.strip() if result else ""

        except RuntimeError as e:
            if "out of memory" in str(e).lower():
                log_error("GPU out of memory during OCR inference")
                raise RuntimeError(
                    "GPU out of memory. Try:\n"
                    "1. Close other GPU-intensive applications\n"
                    "2. Use a smaller capture area\n"
                    "3. Switch to CPU-only PyTorch"
                )
            raise

    def unload_model(self) -> None:
        """Unload the model to free memory."""
        with self._load_lock:
            if self._mocr is not None:
                del self._mocr
                self._mocr = None

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

            log_info("manga-ocr model unloaded")


def get_manga_engine() -> MangaOCRWrapper:
    """Get the singleton manga-ocr engine instance."""
    return MangaOCRWrapper()
