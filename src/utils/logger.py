"""
Logging Utility - Centralized logging for 代書 (Daisho).

Provides file and console logging with timestamps, log levels,
rotation, system diagnostics, and performance timing utilities.
"""

from __future__ import annotations
import logging
import os
import sys
import time
import platform
import functools
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Optional, Callable, Any
from contextlib import contextmanager


from . import BASE_DIR

LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = "daisho.log"
MAX_LOG_SIZE = 5 * 1024 * 1024  # 5 MB
BACKUP_COUNT = 3

_logger: Optional[logging.Logger] = None


def setup_logger(
    name: str = "代書",
    log_level: Optional[int] = None,
    console_level: int = logging.INFO,
    log_to_file: bool = True,
    log_to_console: bool = True
) -> logging.Logger:
    """Set up and configure the application logger."""
    global _logger

    if _logger is not None:
        return _logger

    if log_level is None:
        log_level = (
            logging.DEBUG
            if os.environ.get("DAISHO_DEBUG_LOG", "0") == "1"
            else logging.INFO
        )

    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    if logger.handlers:
        _logger = logger
        return logger

    file_formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%H:%M:%S'
    )

    if log_to_file:
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            log_path = os.path.join(LOG_DIR, LOG_FILE)
            file_handler = RotatingFileHandler(
                log_path,
                maxBytes=MAX_LOG_SIZE,
                backupCount=BACKUP_COUNT,
                encoding='utf-8'
            )
            file_handler.setLevel(log_level)
            file_handler.setFormatter(file_formatter)
            logger.addHandler(file_handler)
        except Exception as e:
            print(f"Warning: Could not set up file logging: {e}")

    if log_to_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(console_level)
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

    _logger = logger

    logger.info("=" * 60)
    logger.info(f"MangaReader-OCR Starting - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    return logger


def get_logger() -> logging.Logger:
    """Get the application logger, creating it if necessary."""
    global _logger
    if _logger is None:
        _logger = setup_logger()
    return _logger


def log_exception(exc: Exception, context: str = "") -> None:
    """Log an exception with full traceback."""
    logger = get_logger()
    if context:
        logger.error(f"Exception in {context}: {type(exc).__name__}: {exc}")
    else:
        logger.error(f"Exception: {type(exc).__name__}: {exc}")
    logger.debug("Full traceback:", exc_info=True)


def log_debug(message: str) -> None:
    get_logger().debug(message)


def log_info(message: str) -> None:
    get_logger().info(message)


def log_warning(message: str) -> None:
    get_logger().warning(message)


def log_error(message: str) -> None:
    get_logger().error(message)


# =============================================================================
# System Diagnostics
# =============================================================================

def log_system_info(heavy: bool = False) -> None:
    """Log system information. Heavy checks are optional."""
    logger = get_logger()

    logger.info("-" * 60)
    logger.info("SYSTEM DIAGNOSTICS")
    logger.info("-" * 60)

    logger.info(f"Platform: {platform.system()} {platform.release()}")
    logger.info(f"Platform Version: {platform.version()}")
    logger.info(f"Machine: {platform.machine()}")
    logger.info(f"Python Version: {sys.version}")
    logger.info(f"Python Executable: {sys.executable}")

    try:
        import psutil
        mem = psutil.virtual_memory()
        logger.info(f"RAM: {mem.total / (1024**3):.1f} GB total, {mem.available / (1024**3):.1f} GB available")
    except ImportError:
        logger.debug("psutil not available for memory info")

    if heavy:
        _log_gpu_info(logger)
        _log_package_versions(logger)

    logger.info("-" * 60)


def _log_gpu_info(logger: logging.Logger) -> None:
    """Log GPU availability and information."""
    try:
        import torch
        if torch.cuda.is_available():
            logger.info(f"PyTorch CUDA: Available - {torch.cuda.get_device_name(0)}")
            logger.info(f"PyTorch CUDA Version: {torch.version.cuda}")
            mem_total = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            logger.info(f"GPU Memory: {mem_total:.1f} GB")
        else:
            logger.info("PyTorch CUDA: Not available (CPU mode)")
    except ImportError:
        logger.info("PyTorch: Not installed")
    except Exception as e:
        logger.warning(f"PyTorch GPU check failed: {e}")

    try:
        import paddle
        if paddle.device.is_compiled_with_cuda():
            gpu_count = paddle.device.cuda.device_count()
            if gpu_count > 0:
                logger.info(f"PaddlePaddle CUDA: Available, {gpu_count} GPU(s)")
            else:
                logger.info("PaddlePaddle CUDA: Compiled but no GPU found")
        else:
            logger.info("PaddlePaddle: CPU version")
    except ImportError:
        logger.info("PaddlePaddle: Not installed")
    except Exception as e:
        logger.warning(f"PaddlePaddle GPU check failed: {e}")


def _log_package_versions(logger: logging.Logger) -> None:
    """Log versions of key packages."""
    packages = [
        "PyQt6", "manga_ocr", "paddleocr", "paddlepaddle",
        "rapidocr", "onnxruntime", "surya", "torch", "torchvision",
        "transformers", "accelerate",
        "opencv-python-headless", "Pillow", "numpy",
        "dxcam", "pynput", "mouse", "fugashi", "unidic-lite",
    ]

    logger.info("Package Versions:")
    for pkg in packages:
        try:
            import_name = pkg.replace("-", "_").replace("opencv_python_headless", "cv2")
            if import_name == "cv2":
                import cv2
                version = cv2.__version__
            elif import_name == "Pillow":
                from PIL import __version__ as version
            else:
                import importlib
                mod = importlib.import_module(import_name)
                version = getattr(mod, "__version__", "unknown")
            logger.info(f"  {pkg}: {version}")
        except ImportError:
            logger.debug(f"  {pkg}: Not installed")
        except Exception as e:
            logger.debug(f"  {pkg}: Error getting version - {e}")


# =============================================================================
# Performance Timing
# =============================================================================

@contextmanager
def log_timing(operation: str, level: int = logging.DEBUG):
    """Context manager to log the duration of an operation."""
    logger = get_logger()
    start = time.perf_counter()
    logger.log(level, f"Starting: {operation}")
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        if elapsed < 1:
            logger.log(level, f"Completed: {operation} in {elapsed*1000:.1f}ms")
        else:
            logger.log(level, f"Completed: {operation} in {elapsed:.2f}s")


def timed(func: Callable) -> Callable:
    """Decorator to log function execution time."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            elapsed = time.perf_counter() - start
            log_debug(f"{func.__name__} completed in {elapsed*1000:.1f}ms")
            return result
        except Exception as e:
            elapsed = time.perf_counter() - start
            log_error(f"{func.__name__} failed after {elapsed*1000:.1f}ms: {e}")
            raise
    return wrapper
