"""
Image Operations - Preprocessing pipelines for OCR accuracy.

Provides multiple preprocessing modes optimized for Japanese text
recognition from manga and screen captures.
"""

from __future__ import annotations
from enum import Enum
from typing import Tuple
import numpy as np
from PIL import Image

from ..utils.logger import log_warning

try:
    import cv2
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False

# Constants
UPSCALE_FACTOR = 2.0
AUTO_CROP_MAX_DIM = 1400

# Retinex constants
RETINEX_SIGMA_LIST = [15, 80, 250]
RETINEX_ALPHA = 0.1
RETINEX_BETA = 0.3
RETINEX_GAMMA = 2.4


class PreprocessingMode(Enum):
    """Available preprocessing modes."""
    NONE = "none"
    ENHANCED = "enhanced"
    RETINEX = "retinex"


class TextOrientation:
    """Text orientation detection result."""
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"
    UNKNOWN = "unknown"


def preprocess_image(
    image: Image.Image,
    mode: PreprocessingMode = PreprocessingMode.NONE
) -> Image.Image:
    """Preprocess an image for OCR based on the selected mode."""
    if mode == PreprocessingMode.NONE:
        return _preprocess_none(image)
    elif mode == PreprocessingMode.ENHANCED:
        return _preprocess_enhanced(image)
    elif mode == PreprocessingMode.RETINEX:
        return _preprocess_retinex(image)
    return _preprocess_none(image)


def _preprocess_none(image: Image.Image) -> Image.Image:
    """No preprocessing - just ensure RGB format."""
    if image.mode != 'RGB':
        return image.convert('RGB')
    return image


def _preprocess_enhanced(image: Image.Image) -> Image.Image:
    """2x Lanczos upscale + contrast + sharpening."""
    from PIL import ImageEnhance

    if image.mode != 'RGB':
        image = image.convert('RGB')

    width, height = image.size
    new_size = (int(width * UPSCALE_FACTOR), int(height * UPSCALE_FACTOR))
    image = image.resize(new_size, Image.Resampling.LANCZOS)

    contrast_enhancer = ImageEnhance.Contrast(image)
    image = contrast_enhancer.enhance(1.4)

    sharpness_enhancer = ImageEnhance.Sharpness(image)
    return sharpness_enhancer.enhance(1.3)


def _preprocess_retinex(image: Image.Image) -> Image.Image:
    """Multi-Scale Retinex in LAB color space for low-contrast recovery.

    Best for dark backgrounds, low contrast manga, colored text on
    colored backgrounds. Preserves color information while enhancing
    luminance contrast across multiple spatial scales.
    """
    if not OPENCV_AVAILABLE:
        log_warning("OpenCV not available, falling back to enhanced mode")
        return _preprocess_enhanced(image)

    if image.mode != 'RGB':
        image = image.convert('RGB')

    img_array = np.asarray(image)
    img_bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)

    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
    l_chan, a_chan, b_chan = cv2.split(lab)

    l_float = l_chan.astype(np.float32) / 255.0

    # Multi-Scale Retinex on L channel
    msr = np.zeros_like(l_float)
    for sigma in RETINEX_SIGMA_LIST:
        blurred = cv2.GaussianBlur(l_float, (0, 0), sigma)
        msr += np.log(l_float + 1e-6) - np.log(blurred + 1e-6)
    msr /= len(RETINEX_SIGMA_LIST)

    l_msr = RETINEX_BETA * msr
    l_result = RETINEX_ALPHA * l_msr + (1 - RETINEX_ALPHA) * l_float
    l_result = np.clip(l_result, 0, 1)
    l_result = l_result ** (1.0 / RETINEX_GAMMA)
    l_result = (l_result * 255).astype(np.uint8)

    lab_result = cv2.merge([l_result, a_chan, b_chan])
    result_bgr = cv2.cvtColor(lab_result, cv2.COLOR_LAB2BGR)
    result_rgb = cv2.cvtColor(result_bgr, cv2.COLOR_BGR2RGB)

    return Image.fromarray(result_rgb)


# =============================================================================
# Smart Crop and Orientation Detection
# =============================================================================

def detect_text_orientation(image: Image.Image) -> str:
    """Detect whether text is primarily horizontal or vertical."""
    if not OPENCV_AVAILABLE:
        return TextOrientation.UNKNOWN

    try:
        img_array = np.asarray(image.convert('L'))
        _, binary = cv2.threshold(img_array, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if len(contours) < 3:
            return TextOrientation.UNKNOWN

        min_area = (image.width * image.height) * 0.0001
        boxes = []
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            if w * h > min_area:
                boxes.append((x, y, w, h))

        if len(boxes) < 3:
            return TextOrientation.UNKNOWN

        centers = [(x + w/2, y + h/2) for x, y, w, h in boxes]
        x_coords = [c[0] for c in centers]
        y_coords = [c[1] for c in centers]

        x_variance = np.var(x_coords) if len(x_coords) > 1 else 0
        y_variance = np.var(y_coords) if len(y_coords) > 1 else 0

        vertical_boxes = sum(1 for _, _, w, h in boxes if h > w * 1.5)
        horizontal_boxes = sum(1 for _, _, w, h in boxes if w > h * 1.5)

        score = 0  # Positive = horizontal, negative = vertical

        if x_variance > 0 and y_variance > 0:
            ratio = x_variance / y_variance
            if ratio > 2:
                score += 1
            elif ratio < 0.5:
                score -= 1

        if horizontal_boxes > vertical_boxes * 1.5:
            score += 1
        elif vertical_boxes > horizontal_boxes * 1.5:
            score -= 1

        if score > 0:
            return TextOrientation.HORIZONTAL
        elif score < 0:
            return TextOrientation.VERTICAL
        return TextOrientation.UNKNOWN

    except Exception:
        return TextOrientation.UNKNOWN


def auto_crop_text(image: Image.Image, padding: int = 5) -> Image.Image:
    """Crop image to tightest bounding box around text content."""
    if not OPENCV_AVAILABLE:
        return image

    try:
        gray = np.asarray(image.convert('L'))
        original_height, original_width = gray.shape

        scale = 1.0
        analysis = gray
        max_dim = max(original_width, original_height)
        if max_dim > AUTO_CROP_MAX_DIM:
            scale = AUTO_CROP_MAX_DIM / max_dim
            analysis = cv2.resize(
                gray,
                (int(original_width * scale), int(original_height * scale)),
                interpolation=cv2.INTER_AREA
            )

        analysis_height, analysis_width = analysis.shape
        pad = max(1, int(padding * scale))

        _, binary = cv2.threshold(analysis, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            return image

        min_area = (analysis_width * analysis_height) * 0.0005
        all_x, all_y, all_x2, all_y2 = [], [], [], []

        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            if w * h > min_area:
                all_x.append(x)
                all_y.append(y)
                all_x2.append(x + w)
                all_y2.append(y + h)

        if not all_x:
            return image

        if scale < 1.0:
            left = max(0, int((min(all_x) - pad) / scale))
            top = max(0, int((min(all_y) - pad) / scale))
            right = min(original_width, int((max(all_x2) + pad) / scale))
            bottom = min(original_height, int((max(all_y2) + pad) / scale))
        else:
            left = max(0, min(all_x) - pad)
            top = max(0, min(all_y) - pad)
            right = min(original_width, max(all_x2) + pad)
            bottom = min(original_height, max(all_y2) + pad)

        crop_width = right - left
        crop_height = bottom - top

        if crop_width >= original_width * 0.9 and crop_height >= original_height * 0.9:
            return image
        if crop_width < 20 or crop_height < 20:
            return image

        return image.crop((left, top, right, bottom))

    except Exception:
        return image


def smart_preprocess(
    image: Image.Image,
    auto_crop: bool = True,
    detect_orientation: bool = True,
    preprocessing_mode: PreprocessingMode = PreprocessingMode.NONE
) -> Tuple[Image.Image, str]:
    """Apply smart preprocessing pipeline with auto-crop and orientation detection."""
    orientation = TextOrientation.UNKNOWN

    if auto_crop:
        image = auto_crop_text(image)

    if detect_orientation:
        orientation = detect_text_orientation(image)

    image = preprocess_image(image, preprocessing_mode)

    return image, orientation


def get_available_modes() -> list[PreprocessingMode]:
    """Get list of available preprocessing modes based on installed packages."""
    modes = [PreprocessingMode.NONE, PreprocessingMode.ENHANCED]
    if OPENCV_AVAILABLE:
        modes.append(PreprocessingMode.RETINEX)
    return modes


def mode_description(mode: PreprocessingMode) -> str:
    """Get human-readable description of a preprocessing mode."""
    descriptions = {
        PreprocessingMode.NONE: "Raw (No preprocessing)",
        PreprocessingMode.ENHANCED: "Enhanced (Upscale + sharpen)",
        PreprocessingMode.RETINEX: "Retinex (Low-contrast recovery)",
    }
    return descriptions.get(mode, str(mode.value))
