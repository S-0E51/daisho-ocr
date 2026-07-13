"""
OCR Cache - Persistent caching for OCR results using diskcache.

Caches OCR results based on image hash to avoid re-processing
identical images.
"""

from __future__ import annotations
import hashlib
import os
import threading
from typing import Optional, Dict, Any, Tuple
from PIL import Image

from ..utils.logger import log_info, log_debug, log_warning, log_error

try:
    import diskcache
    DISKCACHE_AVAILABLE = True
except ImportError:
    DISKCACHE_AVAILABLE = False

DEFAULT_CACHE_DIR = "ocr_cache"
DEFAULT_MAX_SIZE = 500 * 1024 * 1024  # 500 MB
DEFAULT_EXPIRY_DAYS = 30
HASH_BAND_HEIGHT = 128


class OCRCache:
    """Manages persistent caching of OCR results."""

    _instance: Optional['OCRCache'] = None

    def __new__(cls) -> 'OCRCache':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._cache = None
        self._enabled = False
        self._stats = {"hits": 0, "misses": 0, "stores": 0}
        self._lock = threading.RLock()
        self._initialized = True

    def _close_cache_handle(self) -> None:
        """Close the active diskcache handle without resetting stats."""
        if self._cache is not None:
            try:
                self._cache.close()
                log_debug("OCR cache closed")
            except Exception as e:
                log_warning(f"Error closing cache: {e}")
            self._cache = None

    def initialize(
        self,
        cache_dir: str = DEFAULT_CACHE_DIR,
        max_size: int = DEFAULT_MAX_SIZE,
        enabled: bool = True
    ) -> bool:
        """Initialize the cache storage."""
        with self._lock:
            self._close_cache_handle()
            self._enabled = enabled

            if not enabled:
                log_info("OCR cache disabled by configuration")
                return True

            if not DISKCACHE_AVAILABLE:
                log_warning("diskcache not available, caching disabled")
                self._enabled = False
                return False

            try:
                os.makedirs(cache_dir, exist_ok=True)
                self._cache = diskcache.Cache(
                    cache_dir,
                    size_limit=max_size,
                    eviction_policy='least-recently-used'
                )
                log_info(f"OCR cache initialized: {cache_dir} (max {max_size // 1024 // 1024}MB)")
                return True
            except Exception as e:
                log_error(f"Failed to initialize OCR cache: {e}")
                self._enabled = False
                return False

    def _compute_image_hash(self, image: Image.Image) -> str:
        """Compute an exact cache hash from all pixel bytes."""
        width, height = image.size
        hash_obj = hashlib.blake2s(digest_size=16)
        hash_obj.update(f"{width}x{height}:{image.mode}".encode())

        palette = image.getpalette()
        if palette:
            hash_obj.update(bytes(palette))

        for top in range(0, height, HASH_BAND_HEIGHT):
            bottom = min(height, top + HASH_BAND_HEIGHT)
            band = image.crop((0, top, width, bottom))
            hash_obj.update(band.tobytes())

        return f"full:{hash_obj.hexdigest()}"

    def _make_cache_key(self, image: Image.Image, engine: str = "") -> str:
        """Compute the full cache key for an image + engine combination."""
        image_hash = self._compute_image_hash(image)
        return f"{engine}:{image_hash}" if engine else image_hash

    def get(self, image: Image.Image, engine: str = "") -> Optional[str]:
        """Look up cached OCR result for an image."""
        result, _ = self.get_with_key(image, engine)
        return result

    def get_with_key(self, image: Image.Image, engine: str = "") -> Tuple[Optional[str], str]:
        """Look up cached OCR result and return (result, cache_key) for reuse."""
        with self._lock:
            if not self._enabled or self._cache is None:
                return None, ""

            try:
                cache_key = self._make_cache_key(image, engine)

                result = self._cache.get(cache_key)
                if result is not None:
                    self._stats["hits"] += 1
                    log_debug(f"Cache HIT for {cache_key[:16]}...")
                    return result, cache_key
                else:
                    self._stats["misses"] += 1
                    log_debug(f"Cache MISS for {cache_key[:16]}...")
                    return None, cache_key
            except Exception as e:
                log_warning(f"Cache lookup error: {e}")
                return None, ""

    def store(
        self,
        image: Image.Image,
        result: str,
        engine: str = "",
        expiry_days: int = DEFAULT_EXPIRY_DAYS
    ) -> bool:
        """Store an OCR result in the cache."""
        cache_key = self._make_cache_key(image, engine)
        return self.store_with_key(cache_key, result, expiry_days)

    def store_with_key(
        self,
        cache_key: str,
        result: str,
        expiry_days: int = DEFAULT_EXPIRY_DAYS
    ) -> bool:
        """Store an OCR result using a pre-computed cache key."""
        with self._lock:
            if not self._enabled or self._cache is None:
                return False

            if not result or not result.strip():
                return False

            if not cache_key:
                return False

            try:
                expiry_seconds = expiry_days * 24 * 60 * 60
                self._cache.set(cache_key, result, expire=expiry_seconds)
                self._stats["stores"] += 1
                log_debug(f"Cached result for {cache_key[:16]}... (expires in {expiry_days} days)")
                return True
            except Exception as e:
                log_warning(f"Cache store error: {e}")
                return False

    def clear(self) -> bool:
        """Clear all cached entries."""
        with self._lock:
            if self._cache is None:
                return False

            try:
                self._cache.clear()
                self._stats = {"hits": 0, "misses": 0, "stores": 0}
                log_info("OCR cache cleared")
                return True
            except Exception as e:
                log_error(f"Failed to clear cache: {e}")
                return False

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            stats = dict(self._stats)

            if self._cache is not None:
                try:
                    stats["entries"] = len(self._cache)
                    stats["size_bytes"] = self._cache.volume()
                    stats["size_mb"] = round(stats["size_bytes"] / 1024 / 1024, 2)
                except Exception:
                    stats["entries"] = 0
                    stats["size_bytes"] = 0
                    stats["size_mb"] = 0
            else:
                stats["entries"] = 0
                stats["size_bytes"] = 0
                stats["size_mb"] = 0

            total = stats["hits"] + stats["misses"]
            stats["hit_rate"] = round(stats["hits"] / total * 100, 1) if total > 0 else 0
            stats["enabled"] = self._enabled
            return stats

    def close(self) -> None:
        """Close the cache and release resources."""
        with self._lock:
            self._enabled = False
            self._close_cache_handle()

    @property
    def enabled(self) -> bool:
        return self._enabled and self._cache is not None


def get_ocr_cache() -> OCRCache:
    """Get the global OCR cache instance."""
    return OCRCache()
