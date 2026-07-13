"""
PaddleOCR Engine - PP-OCRv5 Japanese OCR model wrapper.

Thread-safe singleton with PaddleOCR 3.x API support (predict() method).

Workarounds applied at module level (must happen before any paddle imports):
1. FLAGS_use_mkldnn=0 - Disables oneDNN to avoid PIR attribute conversion bug
   in PaddlePaddle 3.x. See: https://github.com/PaddlePaddle/PaddleOCR/discussions/17350
2. torch imported before paddle - PaddlePaddle's native libs interfere with
   torch's DLL search path on Windows, causing shm.dll load failures.
3. DISABLE_MODEL_SOURCE_CHECK - Skips slow model hoster connectivity check.
"""

from __future__ import annotations
import os
import threading
from typing import Optional, Callable
from PIL import Image
import numpy as np

# --- Environment workarounds (must be set BEFORE importing paddle) ---
# Aggressively disable oneDNN/MKLDNN to prevent tensor allocation crashes
# (PreconditionNotMetError: Tensor holds no memory) in PaddlePaddle 3.x.
os.environ["FLAGS_use_mkldnn"] = "0"
os.environ["FLAGS_use_onednn"] = "0"
os.environ["MKLDNN_DISABLE"] = "1"
os.environ.setdefault("DISABLE_MODEL_SOURCE_CHECK", "True")

# Import torch BEFORE paddle on Windows to prevent DLL search path conflicts
# that cause "shm.dll: The specified procedure could not be found" errors.
try:
    import torch  # noqa: F401
except ImportError:
    pass

from ..utils.logger import log_info, log_error, log_debug, log_warning
from .types import OCRAnalysisResult


DEFAULT_PADDLE_PROFILE = "standard"

FAST_PADDLE_PREDICT_KWARGS = {
    "use_doc_orientation_classify": False,
    "use_doc_unwarping": False,
    "use_textline_orientation": True,
    "text_det_limit_type": "min",
    "text_det_limit_side_len": 736,
    "text_rec_score_thresh": 0.0,
}

STANDARD_PADDLE_PREDICT_KWARGS = {
    "use_doc_orientation_classify": False,
    "use_doc_unwarping": False,
    "use_textline_orientation": True,
    "text_det_limit_type": "min",
    "text_det_limit_side_len": 960,
    "text_rec_score_thresh": 0.0,
}

ACCURATE_PADDLE_PREDICT_KWARGS = {
    "use_doc_orientation_classify": False,
    "use_doc_unwarping": False,
    "use_textline_orientation": True,
    "text_det_limit_type": "min",
    "text_det_limit_side_len": 1280,
    "text_rec_score_thresh": 0.0,
}

FAST_HARD_TEXT_RETRY_PREDICT_KWARGS = {
    "use_doc_orientation_classify": False,
    "use_doc_unwarping": False,
    "use_textline_orientation": True,
    "text_det_limit_type": "min",
    "text_det_limit_side_len": 960,
    "text_rec_score_thresh": 0.0,
}

HARD_TEXT_RETRY_PREDICT_KWARGS = {
    "use_doc_orientation_classify": True,
    "use_doc_unwarping": True,
    "use_textline_orientation": True,
    "text_det_limit_type": "min",
    "text_det_limit_side_len": 960,
    "text_rec_score_thresh": 0.0,
}

ACCURATE_HARD_TEXT_RETRY_PREDICT_KWARGS = {
    "use_doc_orientation_classify": True,
    "use_doc_unwarping": True,
    "use_textline_orientation": True,
    "text_det_limit_type": "min",
    "text_det_limit_side_len": 1280,
    "text_rec_score_thresh": 0.0,
}

PADDLE_PROFILE_INFO = {
    "fast": {
        "name": "Fast",
        "description": (
            "Uses the PP-OCRv5 mobile detector and recognizer with a lighter "
            "detection pass. Best for CPU use, rapid captures, and continuous "
            "reading when you can fall back to comparison for hard text."
        ),
        "predict_kwargs": FAST_PADDLE_PREDICT_KWARGS,
        "retry_predict_kwargs": FAST_HARD_TEXT_RETRY_PREDICT_KWARGS,
    },
    "standard": {
        "name": "Standard",
        "description": (
            "Recommended default for screenshots. Uses the PP-OCRv5 server "
            "models and automatically retries difficult captures with heavier "
            "preprocessing when the first pass looks weak."
        ),
        "predict_kwargs": STANDARD_PADDLE_PREDICT_KWARGS,
        "retry_predict_kwargs": HARD_TEXT_RETRY_PREDICT_KWARGS,
    },
    "accurate": {
        "name": "Accurate",
        "description": (
            "Uses the PP-OCRv5 server models with a larger detection limit. "
            "Slower, but useful for dense screenshots, small UI text, and "
            "captures where missing a line is worse than waiting longer."
        ),
        "predict_kwargs": ACCURATE_PADDLE_PREDICT_KWARGS,
        "retry_predict_kwargs": ACCURATE_HARD_TEXT_RETRY_PREDICT_KWARGS,
    },
}

LEGACY_PADDLE_PROFILE_ALIASES = {
    "balanced": DEFAULT_PADDLE_PROFILE,
    "default": DEFAULT_PADDLE_PROFILE,
    "server": DEFAULT_PADDLE_PROFILE,
    "mobile": "fast",
    "speed": "fast",
    "quality": "accurate",
}

PADDLE_MODEL_KEY_BY_PROFILE = {
    "fast": "ppocrv5_mobile_japan",
    "standard": "ppocrv5_server_japan",
    "accurate": "ppocrv5_server_japan",
}

PADDLE_MODEL_CONFIGS = {
    "ppocrv5_mobile_japan": {
        "display_name": "PP-OCRv5 mobile Japanese-capable models",
        "text_detection_model_name": "PP-OCRv5_mobile_det",
        "text_recognition_model_name": "PP-OCRv5_mobile_rec",
    },
    "ppocrv5_server_japan": {
        "display_name": "PP-OCRv5 server Japanese models",
        "text_detection_model_name": "PP-OCRv5_server_det",
        "text_recognition_model_name": "PP-OCRv5_server_rec",
    },
}


def normalize_paddle_profile(profile: Optional[str]) -> str:
    """Normalize an arbitrary Paddle profile string to a supported value."""
    if isinstance(profile, str):
        normalized = profile.strip().lower()
        normalized = LEGACY_PADDLE_PROFILE_ALIASES.get(normalized, normalized)
        if normalized in PADDLE_PROFILE_INFO:
            return normalized
    return DEFAULT_PADDLE_PROFILE


def get_paddle_profile_name(profile: Optional[str]) -> str:
    """Return the UI-friendly name for a Paddle profile."""
    normalized = normalize_paddle_profile(profile)
    return PADDLE_PROFILE_INFO[normalized]["name"]


def get_paddle_profile_description(profile: Optional[str]) -> str:
    """Return a short description for a Paddle profile."""
    normalized = normalize_paddle_profile(profile)
    return PADDLE_PROFILE_INFO[normalized]["description"]


def get_available_paddle_profiles() -> tuple[str, ...]:
    """Return Paddle profile keys in UI/display order."""
    return tuple(PADDLE_PROFILE_INFO.keys())


class PaddleOCRWrapper:
    """
    Wrapper for PaddleOCR Japanese OCR profiles.

    Uses PaddleOCR 3.x API with fast/mobile and server-backed profiles plus
    smart fallback retry for difficult captures.
    """

    _instance: Optional[PaddleOCRWrapper] = None
    _lock = threading.Lock()
    _initialized = False

    def __new__(cls) -> PaddleOCRWrapper:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        with PaddleOCRWrapper._lock:
            if PaddleOCRWrapper._initialized:
                return

            self._ocr = None
            self._is_loaded = False
            self._is_loading = False
            self._load_error: Optional[str] = None
            self._load_lock = threading.Lock()
            self._load_event = threading.Event()
            self._use_gpu = False
            self._profile = DEFAULT_PADDLE_PROFILE
            self._ocr_cache: dict[str, object] = {}
            self._active_model_key = self._get_model_key_for_profile(self._profile)
            self._loading_model_key: Optional[str] = None

            PaddleOCRWrapper._initialized = True

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

    @property
    def profile(self) -> str:
        return self._profile

    def set_profile(self, profile: Optional[str]) -> str:
        """Update the active Paddle profile used at inference time."""
        normalized = normalize_paddle_profile(profile)
        if normalized != self._profile:
            previous_model_key = self._get_model_key_for_profile(self._profile)
            self._profile = normalized
            self._active_model_key = self._get_model_key_for_profile(normalized)
            if self._active_model_key != previous_model_key:
                self._ocr = self._ocr_cache.get(self._active_model_key)
                self._is_loaded = self._ocr is not None
                self._load_error = None
                if self._is_loaded:
                    self._load_event.set()
                else:
                    self._load_event.clear()
            log_info(f"PaddleOCR profile set to {get_paddle_profile_name(normalized)}")
        return self._profile

    def _get_model_key_for_profile(self, profile: Optional[str]) -> str:
        """Return the cached model family key for a given profile."""
        normalized = normalize_paddle_profile(profile)
        return PADDLE_MODEL_KEY_BY_PROFILE[normalized]

    def _get_active_model_config(self) -> dict:
        """Return the model configuration for the active profile family."""
        return PADDLE_MODEL_CONFIGS[self._active_model_key]

    def _get_predict_kwargs(self) -> dict:
        """Return per-inference kwargs for the active Paddle profile."""
        profile_info = PADDLE_PROFILE_INFO[self._profile]
        return dict(profile_info["predict_kwargs"])

    def _get_hard_text_retry_predict_kwargs(self) -> dict:
        """Return the heavier retry settings used for difficult captures."""
        profile_info = PADDLE_PROFILE_INFO[self._profile]
        return dict(profile_info["retry_predict_kwargs"])

    def load_model_async(self, callback: Optional[Callable[[bool, Optional[str]], None]] = None) -> None:
        """Load the PaddleOCR model in a background thread."""
        requested_model_key = self._active_model_key
        if self._is_loaded:
            if callback:
                callback(self._is_loaded and self._active_model_key == requested_model_key, self._load_error)
            return

        if self._is_loading:
            loading_model_key = self._loading_model_key
            needs_follow_up_load = loading_model_key != requested_model_key

            def wait_thread():
                self.wait_for_load()
                if (
                    needs_follow_up_load
                    and self._active_model_key == requested_model_key
                    and requested_model_key not in self._ocr_cache
                ):
                    self.load_model_async(callback)
                    return
                if callback:
                    callback(
                        self._is_loaded and self._active_model_key == requested_model_key,
                        self._load_error,
                    )

            if callback or needs_follow_up_load:
                thread = threading.Thread(target=wait_thread, daemon=True)
                thread.start()
            return

        self._is_loading = True
        self._loading_model_key = requested_model_key
        self._load_error = None
        self._load_event.clear()

        def load_thread():
            self._load_model_sync(requested_model_key)
            if callback:
                callback(
                    self._is_loaded and self._active_model_key == requested_model_key,
                    self._load_error,
                )

        thread = threading.Thread(target=load_thread, daemon=True)
        thread.start()

    def _load_model_sync(self, model_key: Optional[str] = None) -> None:
        """Synchronously load the PaddleOCR model."""
        with self._load_lock:
            model_key = model_key or self._active_model_key
            model_config = PADDLE_MODEL_CONFIGS[model_key]

            if model_key in self._ocr_cache:
                if self._active_model_key == model_key:
                    self._ocr = self._ocr_cache[model_key]
                    self._is_loaded = True
                else:
                    self._ocr = self._ocr_cache.get(self._active_model_key)
                    self._is_loaded = self._ocr is not None
                self._is_loading = False
                self._loading_model_key = None
                self._load_error = None
                self._load_event.set()
                return

            self._is_loading = True
            self._is_loaded = False
            self._load_error = None
            self._load_event.clear()
            self._loading_model_key = model_key

            try:
                log_info(f"Loading PaddleOCR {model_config['display_name']}...")
                log_info("Note: First run may download models. Please wait...")

                try:
                    import paddle
                    if paddle.device.is_compiled_with_cuda():
                        gpu_count = paddle.device.cuda.device_count()
                        if gpu_count > 0:
                            self._use_gpu = True
                            log_info(f"PaddlePaddle CUDA available, GPU count: {gpu_count}")
                        else:
                            log_info("PaddlePaddle compiled with CUDA but no GPU found, using CPU")
                    else:
                        log_info("PaddlePaddle CPU version, using CPU")
                except Exception as e:
                    log_debug(f"GPU check failed: {e}, defaulting to CPU")

                from paddleocr import PaddleOCR

                log_info("Initializing PaddleOCR (downloading models if needed)...")

                ocr_kwargs = dict(
                    text_detection_model_name=model_config["text_detection_model_name"],
                    text_recognition_model_name=model_config["text_recognition_model_name"],
                )
                if self._use_gpu:
                    ocr_kwargs["device"] = "gpu"
                    log_info("PaddleOCR: using GPU device")

                loaded_model = PaddleOCR(**ocr_kwargs)
                self._ocr_cache[model_key] = loaded_model
                if self._active_model_key == model_key:
                    self._ocr = loaded_model
                    self._is_loaded = True
                else:
                    self._ocr = self._ocr_cache.get(self._active_model_key)
                    self._is_loaded = self._ocr is not None

                log_info(
                    f"PaddleOCR {model_config['display_name']} loaded successfully! "
                    f"Active profile: {get_paddle_profile_name(self._profile)}"
                )

            except ImportError as e:
                self._load_error = (
                    "PaddleOCR is not installed.\n"
                    "Please run: pip install paddleocr"
                )
                log_error(f"Import error: {e}")

            except Exception as e:
                error_str = str(e)
                if "paddle" in error_str.lower():
                    self._load_error = (
                        f"PaddlePaddle error: {e}\n\n"
                        "Try reinstalling PaddlePaddle:\n"
                        "  pip uninstall paddlepaddle\n"
                        "  pip install paddlepaddle"
                    )
                else:
                    self._load_error = f"Error loading PaddleOCR: {e}"
                log_error(f"Error loading model: {e}")

            finally:
                self._is_loading = False
                self._loading_model_key = None
                self._load_event.set()

    def wait_for_load(self, timeout: Optional[float] = None) -> bool:
        """Wait for the model to finish loading."""
        self._load_event.wait(timeout)
        return self._is_loaded

    # Maximum dimension (pixels) to pass to PaddleOCR.
    # Large images can trigger oneDNN tensor allocation failures.
    MAX_OCR_DIM = 4096
    DETECTION_AUTO_CROP_MIN_DIM = 700
    DETECTION_AUTO_CROP_MIN_AREA = 220_000
    DETECTION_AUTO_CROP_SCORE_THRESH = 0.45
    DETECTION_AUTO_CROP_KEEP_AREA_RATIO = 0.94
    HARD_TEXT_RETRY_MIN_DIM = 360
    HARD_TEXT_RETRY_MIN_AREA = 120_000
    HARD_TEXT_RETRY_SHORT_TEXT_LEN = 4
    HARD_TEXT_RETRY_LOW_SCORE = 0.72

    def _prepare_image_for_inference(self, image: Image.Image) -> tuple[Image.Image, float]:
        """Convert to RGB and downscale oversized images for stable OCR inference."""
        if image.mode != "RGB":
            image = image.convert("RGB")

        width, height = image.size
        max_dim = max(width, height)
        if max_dim > self.MAX_OCR_DIM:
            scale = self.MAX_OCR_DIM / max_dim
            new_size = (int(width * scale), int(height * scale))
            log_info(
                f"Resizing image for PaddleOCR: {width}x{height} -> "
                f"{new_size[0]}x{new_size[1]}"
            )
            return image.resize(new_size, Image.Resampling.LANCZOS), scale

        return image, 1.0

    def _extract_detector_boxes(
        self,
        detection_result,
        scale: float,
        image_size: tuple[int, int],
    ) -> list[tuple[int, int, int, int, float]]:
        """Normalize Paddle detector polygons into filtered axis-aligned boxes."""
        width, height = image_size
        min_box_area = max(64, int(width * height * 0.00002))

        if hasattr(detection_result, "to_dict"):
            detection_result = detection_result.to_dict()

        if isinstance(detection_result, dict):
            dt_polys = detection_result.get("dt_polys", [])
            dt_scores = detection_result.get("dt_scores", [])
        else:
            dt_polys = getattr(detection_result, "dt_polys", [])
            dt_scores = getattr(detection_result, "dt_scores", [])

        poly_iterable = dt_polys if dt_polys is not None else []
        score_iterable = dt_scores if dt_scores is not None else []
        boxes: list[tuple[int, int, int, int, float]] = []
        for index, poly in enumerate(poly_iterable):
            poly_array = np.asarray(poly)
            if poly_array.ndim != 2 or poly_array.shape[0] < 4 or poly_array.shape[1] < 2:
                continue

            score = 0.0
            if index < len(score_iterable):
                try:
                    score = float(score_iterable[index])
                except (TypeError, ValueError):
                    score = 0.0
            if score < self.DETECTION_AUTO_CROP_SCORE_THRESH:
                continue

            xs = poly_array[:, 0].astype(np.float32) / scale
            ys = poly_array[:, 1].astype(np.float32) / scale
            left = max(0, int(np.floor(xs.min())))
            top = max(0, int(np.floor(ys.min())))
            right = min(width, int(np.ceil(xs.max())))
            bottom = min(height, int(np.ceil(ys.max())))

            if right - left < 4 or bottom - top < 4:
                continue
            if (right - left) * (bottom - top) < min_box_area:
                continue

            boxes.append((left, top, right, bottom, score))

        return boxes

    def _cluster_detector_boxes(
        self,
        boxes: list[tuple[int, int, int, int, float]],
    ) -> list[dict[str, object]]:
        """Group nearby detector boxes into text regions."""
        if not boxes:
            return []

        if len(boxes) == 1:
            left, top, right, bottom, score = boxes[0]
            return [{
                "bounds": (left, top, right, bottom),
                "weight": (right - left) * (bottom - top) * max(score, 0.1),
                "count": 1,
            }]

        widths = [right - left for left, _, right, _, _ in boxes]
        heights = [bottom - top for _, top, _, bottom, _ in boxes]
        gap_x = max(18, int(np.median(widths) * 1.2))
        gap_y = max(18, int(np.median(heights) * 1.2))

        cluster_boxes: list[list[tuple[int, int, int, int, float]]] = []
        for box in boxes:
            left, top, right, bottom, _ = box
            attached_clusters: list[int] = []
            for idx, cluster in enumerate(cluster_boxes):
                if any(
                    not (
                        right + gap_x < other_left
                        or other_right + gap_x < left
                        or bottom + gap_y < other_top
                        or other_bottom + gap_y < top
                    )
                    for other_left, other_top, other_right, other_bottom, _ in cluster
                ):
                    attached_clusters.append(idx)

            if not attached_clusters:
                cluster_boxes.append([box])
                continue

            primary_idx = attached_clusters[0]
            cluster_boxes[primary_idx].append(box)
            for merge_idx in reversed(attached_clusters[1:]):
                cluster_boxes[primary_idx].extend(cluster_boxes[merge_idx])
                del cluster_boxes[merge_idx]

        clusters: list[dict[str, object]] = []
        for cluster in cluster_boxes:
            left = min(box[0] for box in cluster)
            top = min(box[1] for box in cluster)
            right = max(box[2] for box in cluster)
            bottom = max(box[3] for box in cluster)
            weight = sum((box[2] - box[0]) * (box[3] - box[1]) * max(box[4], 0.1) for box in cluster)
            clusters.append({
                "bounds": (left, top, right, bottom),
                "weight": weight,
                "count": len(cluster),
            })

        return clusters

    def _select_crop_bounds(
        self,
        clusters: list[dict[str, object]],
        image_size: tuple[int, int],
        boxes: list[tuple[int, int, int, int, float]],
    ) -> Optional[tuple[int, int, int, int]]:
        """Choose a conservative crop box from clustered detector output."""
        if not clusters:
            return None

        width, height = image_size
        image_area = width * height
        union_left = min(box[0] for box in boxes)
        union_top = min(box[1] for box in boxes)
        union_right = max(box[2] for box in boxes)
        union_bottom = max(box[3] for box in boxes)
        union_bounds = (union_left, union_top, union_right, union_bottom)

        chosen_cluster = max(clusters, key=lambda cluster: float(cluster["weight"]))
        total_weight = sum(float(cluster["weight"]) for cluster in clusters)
        chosen_bounds = chosen_cluster["bounds"]

        if len(clusters) > 1 and total_weight > 0:
            chosen_weight = float(chosen_cluster["weight"])
            chosen_left, chosen_top, chosen_right, chosen_bottom = chosen_bounds
            chosen_area = (chosen_right - chosen_left) * (chosen_bottom - chosen_top)
            union_area = (union_right - union_left) * (union_bottom - union_top)
            if chosen_weight / total_weight < 0.6 or chosen_area > union_area * 0.85:
                chosen_bounds = union_bounds

        chosen_left, chosen_top, chosen_right, chosen_bottom = chosen_bounds
        widths = [right - left for left, _, right, _, _ in boxes]
        heights = [bottom - top for _, top, _, bottom, _ in boxes]
        pad_x = max(12, int(np.median(widths) * 0.18), int((chosen_right - chosen_left) * 0.03))
        pad_y = max(12, int(np.median(heights) * 0.35), int((chosen_bottom - chosen_top) * 0.05))

        left = max(0, chosen_left - pad_x)
        top = max(0, chosen_top - pad_y)
        right = min(width, chosen_right + pad_x)
        bottom = min(height, chosen_bottom + pad_y)

        crop_width = right - left
        crop_height = bottom - top
        crop_area = crop_width * crop_height
        if crop_width < 24 or crop_height < 24:
            return None
        if (
            crop_area >= image_area * self.DETECTION_AUTO_CROP_KEEP_AREA_RATIO
            and crop_width >= width * 0.92
            and crop_height >= height * 0.92
        ):
            return None

        return (left, top, right, bottom)

    def get_detected_text_crop_box(self, image: Image.Image) -> Optional[tuple[int, int, int, int]]:
        """Return a text-focused crop box using Paddle's detector, if worthwhile."""
        if not self._is_loaded or self._ocr is None:
            return None

        width, height = image.size
        if (
            max(width, height) < self.DETECTION_AUTO_CROP_MIN_DIM
            and width * height < self.DETECTION_AUTO_CROP_MIN_AREA
        ):
            return None

        try:
            prepared_image, scale = self._prepare_image_for_inference(image)
            img_array = np.asarray(prepared_image)[:, :, ::-1]
            predict_kwargs = self._get_predict_kwargs()
            det_kwargs = {}
            if "text_det_limit_side_len" in predict_kwargs:
                det_kwargs["limit_side_len"] = predict_kwargs["text_det_limit_side_len"]
            if "text_det_limit_type" in predict_kwargs:
                det_kwargs["limit_type"] = predict_kwargs["text_det_limit_type"]

            det_model = self._ocr.paddlex_pipeline.text_det_model
            detection_results = list(det_model([img_array], **det_kwargs))
            if not detection_results:
                return None

            boxes = self._extract_detector_boxes(
                detection_results[0],
                scale=scale,
                image_size=image.size,
            )
            clusters = self._cluster_detector_boxes(boxes)
            crop_box = self._select_crop_bounds(clusters, image.size, boxes)
            if crop_box:
                log_debug(
                    "Paddle detector crop selected: "
                    f"{image.size[0]}x{image.size[1]} -> "
                    f"{crop_box[2] - crop_box[0]}x{crop_box[3] - crop_box[1]}"
                )
            return crop_box

        except Exception as e:
            log_debug(f"Paddle detector crop failed, keeping original image: {e}")
            return None

    def crop_to_detected_text(
        self,
        image: Image.Image,
    ) -> tuple[Image.Image, Optional[tuple[int, int, int, int]]]:
        """Crop to the dominant detected text region when it meaningfully helps."""
        crop_box = self.get_detected_text_crop_box(image)
        if crop_box is None:
            return image, None
        return image.crop(crop_box), crop_box

    def _run_predict(self, img_array: np.ndarray, predict_kwargs: dict) -> list:
        """Run PaddleOCR predict with a one-time retry for transient backend failures."""
        try:
            return self._ocr.predict(img_array, **predict_kwargs)
        except Exception as predict_err:
            err_str = str(predict_err)
            if "Tensor holds no memory" in err_str or "onednn" in err_str.lower():
                log_warning(f"PaddleOCR oneDNN error, retrying: {predict_err}")
                return self._ocr.predict(img_array, **predict_kwargs)
            raise

    def _normalize_result_entry(self, result):
        """Convert PaddleOCR result objects into dict-like structures when possible."""
        if hasattr(result, "__dict__") and not isinstance(result, dict):
            try:
                if hasattr(result, "to_dict"):
                    result = result.to_dict()
                elif hasattr(result, "__getitem__"):
                    result_dict = {}
                    for key in ["rec_texts", "rec_scores"]:
                        try:
                            result_dict[key] = result[key]
                        except (KeyError, TypeError):
                            pass
                    if result_dict:
                        result = result_dict
            except Exception as e:
                log_debug(f"Could not convert result to dict: {e}")
        return result

    def _extract_text_and_scores(self, results: list) -> tuple[str, list[float]]:
        """Collect OCR text and confidence scores from Paddle results."""
        texts: list[str] = []
        scores: list[float] = []

        for res in results:
            res = self._normalize_result_entry(res)

            if hasattr(res, "rec_texts") and res.rec_texts:
                rec_texts = list(res.rec_texts)
                rec_scores = list(getattr(res, "rec_scores", []))
                for index, text in enumerate(rec_texts):
                    if text:
                        texts.append(str(text))
                        if index < len(rec_scores):
                            try:
                                scores.append(float(rec_scores[index]))
                            except (TypeError, ValueError):
                                pass

            elif isinstance(res, dict):
                rec_texts = list(res.get("rec_texts", []))
                rec_scores = list(res.get("rec_scores", []))
                for index, text in enumerate(rec_texts):
                    if text:
                        texts.append(str(text))
                        if index < len(rec_scores):
                            try:
                                scores.append(float(rec_scores[index]))
                            except (TypeError, ValueError):
                                pass

            elif isinstance(res, list):
                for detection in res:
                    if detection is None or not isinstance(detection, (list, tuple)):
                        continue
                    if len(detection) >= 2:
                        text_info = detection[1]
                        if isinstance(text_info, (list, tuple)) and len(text_info) >= 1:
                            text = text_info[0]
                            if text:
                                texts.append(str(text))
                            if len(text_info) >= 2:
                                try:
                                    scores.append(float(text_info[1]))
                                except (TypeError, ValueError):
                                    pass

        return "".join(texts).strip(), scores

    def _average_score(self, scores: list[float]) -> float:
        """Compute the average recognition score when available."""
        return float(sum(scores) / len(scores)) if scores else 0.0

    def _should_retry_hard_text(
        self,
        text: str,
        scores: list[float],
        image_size: tuple[int, int],
    ) -> bool:
        """Decide whether a difficult-text retry is worth the extra work."""
        width, height = image_size
        if (
            max(width, height) < self.HARD_TEXT_RETRY_MIN_DIM
            and width * height < self.HARD_TEXT_RETRY_MIN_AREA
        ):
            return False
        if not text:
            return True
        if len(text) <= self.HARD_TEXT_RETRY_SHORT_TEXT_LEN and width * height >= self.HARD_TEXT_RETRY_MIN_AREA:
            return True
        if scores and self._average_score(scores) < self.HARD_TEXT_RETRY_LOW_SCORE:
            return True
        return False

    def _should_use_retry_result(
        self,
        primary_text: str,
        primary_scores: list[float],
        retry_text: str,
        retry_scores: list[float],
    ) -> bool:
        """Choose whether the retry output is meaningfully better than the first pass."""
        if not retry_text:
            return False
        if not primary_text:
            return True
        if len(retry_text) >= len(primary_text) + 2:
            return True
        if len(primary_text) <= self.HARD_TEXT_RETRY_SHORT_TEXT_LEN and len(retry_text) > len(primary_text):
            return True

        primary_avg = self._average_score(primary_scores)
        retry_avg = self._average_score(retry_scores)
        if retry_avg >= primary_avg + 0.08 and len(retry_text) >= max(2, len(primary_text) - 1):
            return True
        return False

    def _perform_ocr_legacy(self, image: Image.Image) -> str:
        """Legacy OCR path kept only as a historical reference while migrating."""
        if not self._is_loaded:
            if self._load_error:
                raise RuntimeError(f"OCR model failed to load: {self._load_error}")
            raise RuntimeError("OCR model not loaded. Call load_model_async() first.")

        if self._ocr is None:
            raise RuntimeError("OCR model is None despite being marked as loaded")

        try:
            image, _ = self._prepare_image_for_inference(image)
            img_array = np.asarray(image)
            predict_kwargs = self._get_predict_kwargs()
            log_debug(
                f"Running PaddleOCR on image shape: {img_array.shape} "
                f"with profile={self._profile}"
            )

            try:
                results = self._ocr.predict(img_array, **predict_kwargs)
            except Exception as predict_err:
                err_str = str(predict_err)
                if "Tensor holds no memory" in err_str or "onednn" in err_str.lower():
                    log_warning(f"PaddleOCR oneDNN error, retrying: {predict_err}")
                    # Retry once — transient oneDNN failures sometimes resolve
                    results = self._ocr.predict(img_array, **predict_kwargs)
                else:
                    raise
            log_debug(f"PaddleOCR result count: {len(results) if results else 0}")

            if not results:
                log_debug("PaddleOCR returned no results")
                return ""

            texts = []
            for res in results:

                # Try to_dict conversion for OCRResult objects
                if hasattr(res, '__dict__') and not isinstance(res, dict):
                    try:
                        if hasattr(res, 'to_dict'):
                            res = res.to_dict()
                        elif hasattr(res, '__getitem__'):
                            res_dict = {}
                            for key in ['rec_texts', 'rec_scores']:
                                try:
                                    res_dict[key] = res[key]
                                except (KeyError, TypeError):
                                    pass
                            if res_dict:
                                res = res_dict
                    except Exception as e:
                        log_debug(f"Could not convert result to dict: {e}")

                # PaddleOCR 3.x: rec_texts attribute
                if hasattr(res, 'rec_texts') and res.rec_texts:
                    rec_texts = res.rec_texts
                    for text in rec_texts:
                        if text:
                            texts.append(text)

                # Dictionary-style access
                elif isinstance(res, dict):
                    if 'rec_texts' in res:
                        rec_texts = res['rec_texts']
                        for text in rec_texts:
                            if text:
                                texts.append(text)

                # Legacy API: [[box, (text, conf)], ...]
                elif isinstance(res, list):
                    for detection in res:
                        if detection is None or not isinstance(detection, (list, tuple)):
                            continue
                        if len(detection) >= 2:
                            text_info = detection[1]
                            if isinstance(text_info, (list, tuple)) and len(text_info) >= 1:
                                text = text_info[0]
                                if text:
                                    texts.append(str(text))

            full_text = ''.join(texts)
            log_debug(f"PaddleOCR extracted {len(full_text)} characters")
            return full_text.strip()

        except Exception as e:
            log_error(f"PaddleOCR inference error: {e}")
            raise RuntimeError(f"OCR inference failed: {e}")

    def perform_ocr_analysis(self, image: Image.Image) -> OCRAnalysisResult:
        """Perform OCR on a PIL Image using the standard profile with smart retry."""
        if not self._is_loaded:
            if self._load_error:
                raise RuntimeError(f"OCR model failed to load: {self._load_error}")
            raise RuntimeError("OCR model not loaded. Call load_model_async() first.")

        if self._ocr is None:
            raise RuntimeError("OCR model is None despite being marked as loaded")

        try:
            image, _ = self._prepare_image_for_inference(image)
            img_array = np.asarray(image)
            predict_kwargs = self._get_predict_kwargs()
            log_debug(
                f"Running PaddleOCR on image shape: {img_array.shape} "
                f"with profile={self._profile}"
            )

            results = self._run_predict(img_array, predict_kwargs)
            log_debug(f"PaddleOCR result count: {len(results) if results else 0}")

            if not results:
                log_debug("PaddleOCR returned no results")
                return OCRAnalysisResult(text="")

            full_text, scores = self._extract_text_and_scores(results)
            used_retry = False
            if self._should_retry_hard_text(full_text, scores, image.size):
                retry_kwargs = self._get_hard_text_retry_predict_kwargs()
                if retry_kwargs != predict_kwargs:
                    log_debug("Retrying PaddleOCR with hard-text preprocessing")
                    retry_results = self._run_predict(img_array, retry_kwargs)
                    retry_text, retry_scores = self._extract_text_and_scores(retry_results)
                    if self._should_use_retry_result(full_text, scores, retry_text, retry_scores):
                        log_info("PaddleOCR hard-text retry improved the result")
                        full_text = retry_text
                        scores = retry_scores
                        used_retry = True

            log_debug(f"PaddleOCR extracted {len(full_text)} characters")
            return OCRAnalysisResult(
                text=full_text.strip(),
                average_confidence=self._average_score(scores) if scores else None,
                used_retry=used_retry,
            )

        except Exception as e:
            log_error(f"PaddleOCR inference error: {e}")
            raise RuntimeError(f"OCR inference failed: {e}")

    def perform_ocr(self, image: Image.Image) -> str:
        """Perform OCR on a PIL Image and return text only."""
        return self.perform_ocr_analysis(image).text

    def unload_model(self) -> None:
        """Unload the model to free memory."""
        with self._load_lock:
            for model in self._ocr_cache.values():
                del model
            self._ocr_cache.clear()
            self._ocr = None

            self._is_loaded = False
            self._is_loading = False
            self._load_error = None
            self._load_event.clear()

            try:
                import paddle
                paddle.device.cuda.empty_cache()
            except Exception:
                pass

            log_info("PaddleOCR model unloaded")


def get_paddle_engine() -> PaddleOCRWrapper:
    """Get the singleton PaddleOCR engine instance."""
    return PaddleOCRWrapper()
