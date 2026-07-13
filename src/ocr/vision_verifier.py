"""
Vision OCR verification using a multimodal Gemma model.

This layer is deliberately not a second OCR engine. It verifies the selected
OCR text against the captured image and only accepts visual corrections when
the model returns a high-confidence structured answer.
"""

from __future__ import annotations

import base64
from contextlib import nullcontext
from dataclasses import dataclass, replace
import io
import json
import re
import threading
import time
from typing import Optional
from urllib import error as url_error
from urllib import request as url_request

from PIL import Image

from ..utils.logger import log_debug, log_error, log_info, log_warning
from .comparison import OCRCandidate, assess_candidate
from .manager import get_engine_name


VISION_VERIFICATION_MODE_OFF = "off"
VISION_VERIFICATION_MODE_SUSPICIOUS = "suspicious"
VISION_VERIFICATION_MODE_ALWAYS = "always"

DEFAULT_GEMMA_VISION_MODEL = "google/gemma-4-E2B-it"
DEFAULT_OLLAMA_VISION_MODEL = "huihui_ai/gemma-4-abliterated:e4b"
DEFAULT_VISION_VERIFICATION_CONFIDENCE = 0.82
OLLAMA_MODEL_PREFIX = "ollama:"
OLLAMA_BASE_URL = "http://127.0.0.1:11434"

VISION_VERIFICATION_MODE_LABELS = {
    VISION_VERIFICATION_MODE_OFF: "Off",
    VISION_VERIFICATION_MODE_SUSPICIOUS: "Suspicious Only",
    VISION_VERIFICATION_MODE_ALWAYS: "Always Verify",
}

_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_WHITESPACE_RE = re.compile(r"\s+")
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class VisionVerificationResult:
    """Structured response from the vision verifier."""

    matches: Optional[bool]
    corrected_text: str
    confidence: float
    uncertain_chars: tuple[str, ...] = ()
    reason: str = ""
    raw_response: str = ""
    model_id: str = ""


@dataclass(frozen=True)
class VisionVerificationDecision:
    """Decision after applying verifier output to an OCR candidate."""

    selected: OCRCandidate
    used_correction: bool
    notes: tuple[str, ...]
    verification: Optional[VisionVerificationResult] = None


def normalize_verification_mode(value: object) -> str:
    """Normalize a visual verification mode string to a supported value."""
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in VISION_VERIFICATION_MODE_LABELS:
            return normalized
    return VISION_VERIFICATION_MODE_OFF


def get_verification_mode_label(mode: object) -> str:
    """Return the UI label for a visual verification mode."""
    normalized = normalize_verification_mode(mode)
    return VISION_VERIFICATION_MODE_LABELS[normalized]


def normalize_verification_model(value: object) -> str:
    """Return a non-empty Gemma model id or the default model id."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return DEFAULT_GEMMA_VISION_MODEL


def is_ollama_verification_model(model_id: object) -> bool:
    """Return True when the verifier model id points at local Ollama."""
    return isinstance(model_id, str) and model_id.strip().lower().startswith(OLLAMA_MODEL_PREFIX)


def get_ollama_model_name(model_id: str) -> str:
    """Return the raw Ollama model name from an ollama:-prefixed id."""
    if is_ollama_verification_model(model_id):
        return model_id.strip()[len(OLLAMA_MODEL_PREFIX):].strip()
    return model_id.strip()


def should_run_visual_verification(
    mode: object,
    candidate: OCRCandidate,
) -> tuple[bool, tuple[str, ...]]:
    """Return whether the Gemma visual verifier should run for this candidate."""
    normalized = normalize_verification_mode(mode)
    text = candidate.text.strip()
    if normalized == VISION_VERIFICATION_MODE_OFF or not text:
        return False, ()

    if normalized == VISION_VERIFICATION_MODE_ALWAYS:
        return True, ("verification mode is Always Verify",)

    assessment = assess_candidate(candidate)
    reasons = list(assessment.suspicious_reasons)

    if _looks_like_short_dense_cjk(text):
        reasons.append("short dense CJK text can hide lookalike glyph substitutions")

    if candidate.average_confidence is not None and candidate.average_confidence < 0.82:
        reasons.append(f"{get_engine_name(candidate.engine)} confidence below verifier threshold")

    return bool(reasons), tuple(_dedupe(reasons))


def apply_verification_result(
    candidate: OCRCandidate,
    result: VisionVerificationResult,
    min_confidence: float = DEFAULT_VISION_VERIFICATION_CONFIDENCE,
) -> VisionVerificationDecision:
    """Apply a structured visual verification result to an OCR candidate."""
    confidence = _clamp_confidence(min_confidence, DEFAULT_VISION_VERIFICATION_CONFIDENCE)
    model_label = result.model_id or "Gemma"
    result_confidence = _clamp_confidence(result.confidence, 0.0)
    corrected_text = (result.corrected_text or "").strip()
    original_text = candidate.text.strip()

    if result.matches is True:
        note = (
            f"Vision verification confirmed {get_engine_name(candidate.engine)} "
            f"with {model_label} ({result_confidence:.2f})."
        )
        return VisionVerificationDecision(
            selected=candidate,
            used_correction=False,
            notes=(note,),
            verification=result,
        )

    if (
        result.matches is False
        and corrected_text
        and corrected_text != original_text
        and result_confidence >= confidence
    ):
        correction_note = _format_text_change("Vision verification", original_text, corrected_text)
        selected = replace(
            candidate,
            text=corrected_text,
            corrections=candidate.corrections + (correction_note,),
        )
        reason = f": {result.reason}" if result.reason else ""
        note = (
            f"Vision verification corrected OCR with {model_label} "
            f"({result_confidence:.2f}){reason}."
        )
        return VisionVerificationDecision(
            selected=selected,
            used_correction=True,
            notes=(note,),
            verification=result,
        )

    if result.matches is False and corrected_text == original_text:
        reason = f": {result.reason}" if result.reason else ""
        note = (
            f"Vision verification kept {get_engine_name(candidate.engine)}: "
            f"{model_label} reported a mismatch but returned the original OCR text "
            f"({result_confidence:.2f}){reason}."
        )
        return VisionVerificationDecision(
            selected=candidate,
            used_correction=False,
            notes=(note,),
            verification=result,
        )

    uncertain_bits: list[str] = []
    if result.uncertain_chars:
        uncertain_bits.append("uncertain chars: " + ", ".join(result.uncertain_chars))
    if result.reason:
        uncertain_bits.append(result.reason)
    suffix = f" ({'; '.join(uncertain_bits)})" if uncertain_bits else ""
    note = (
        f"Vision verification kept {get_engine_name(candidate.engine)}: "
        f"{model_label} was not confident enough ({result_confidence:.2f}){suffix}."
    )
    return VisionVerificationDecision(
        selected=candidate,
        used_correction=False,
        notes=(note,),
        verification=result,
    )


def parse_verification_response(raw_response: str, model_id: str = "") -> VisionVerificationResult:
    """Parse the verifier's JSON-only response, tolerating code fences and extra text."""
    raw = raw_response.strip()
    payload = _extract_json_payload(raw)
    data = json.loads(payload)

    matches_value = data.get("matches")
    matches = matches_value if isinstance(matches_value, bool) else None
    corrected_text = str(data.get("corrected_text") or "")
    confidence = _parse_confidence(data.get("confidence"))
    uncertain_chars = data.get("uncertain_chars") or ()
    if isinstance(uncertain_chars, str):
        uncertain_tuple = (uncertain_chars,)
    elif isinstance(uncertain_chars, list):
        uncertain_tuple = tuple(str(item) for item in uncertain_chars if str(item))
    else:
        uncertain_tuple = ()

    return VisionVerificationResult(
        matches=matches,
        corrected_text=corrected_text,
        confidence=confidence,
        uncertain_chars=uncertain_tuple,
        reason=str(data.get("reason") or ""),
        raw_response=raw_response,
        model_id=model_id,
    )


class GemmaVisionVerifier:
    """Lazy singleton wrapper around a Gemma image-text-to-text model."""

    MAX_IMAGE_EDGE = 1600
    FAILED_LOAD_RETRY_SEC = 180.0
    OLLAMA_LOAD_TIMEOUT_SEC = 180.0
    OLLAMA_VERIFY_TIMEOUT_SEC = 120.0

    _instance: Optional["GemmaVisionVerifier"] = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> "GemmaVisionVerifier":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._model = None
        self._processor = None
        self._model_id = ""
        self._backend = ""
        self._load_error: Optional[str] = None
        self._failed_model_id = ""
        self._load_retry_after = 0.0
        self._is_loading = False
        self._load_event = threading.Event()
        self._load_lock = threading.RLock()
        self._initialized = True

    @property
    def is_loaded(self) -> bool:
        if self._backend == "ollama":
            return bool(self._model_id)
        return self._model is not None and self._processor is not None

    @property
    def is_loading(self) -> bool:
        return self._is_loading

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def load_error(self) -> Optional[str]:
        return self._load_error

    def can_retry_load(self, model_id: str = DEFAULT_GEMMA_VISION_MODEL) -> tuple[bool, str]:
        """Return whether a failed verifier load is outside its cooldown window."""
        model_id = normalize_verification_model(model_id)
        if self.is_loaded:
            return True, ""
        if self._failed_model_id != model_id:
            return True, ""
        now = time.monotonic()
        if now >= self._load_retry_after:
            return True, ""
        retry_in = max(1, int(self._load_retry_after - now))
        return (
            False,
            f"Gemma vision verifier load previously failed; retrying in {retry_in}s "
            f"({self._load_error or 'unknown error'}).",
        )

    def load_model_async(
        self,
        model_id: str = DEFAULT_GEMMA_VISION_MODEL,
        callback=None,
    ) -> None:
        """Start loading Gemma in the background without blocking OCR delivery."""
        model_id = normalize_verification_model(model_id)
        if self.is_loaded and self._model_id == model_id:
            if callback:
                callback(True, self._load_error)
            return

        can_retry, retry_message = self.can_retry_load(model_id)
        if not can_retry:
            if callback:
                callback(False, retry_message)
            return

        with self._load_lock:
            if self.is_loaded and self._model_id == model_id:
                if callback:
                    callback(True, self._load_error)
                return
            if self._is_loading:
                if callback:
                    def wait_thread() -> None:
                        self._load_event.wait()
                        callback(self.is_loaded and self._model_id == model_id, self._load_error)

                    thread = threading.Thread(target=wait_thread, daemon=True)
                    thread.start()
                return

            self._is_loading = True
            self._load_event.clear()

        def load_thread() -> None:
            try:
                self._load_model(model_id)
            finally:
                if callback:
                    callback(self.is_loaded and self._model_id == model_id, self._load_error)

        thread = threading.Thread(
            target=load_thread,
            name="gemma-vision-verifier-loader",
            daemon=True,
        )
        thread.start()

    def verify(
        self,
        image: Image.Image,
        candidate_text: str,
        model_id: str = DEFAULT_GEMMA_VISION_MODEL,
        max_new_tokens: int = 220,
    ) -> VisionVerificationResult:
        """Compare an image against OCR text and return structured verifier output."""
        model_id = normalize_verification_model(model_id)
        self._load_model(model_id)
        if not self.is_loaded:
            raise RuntimeError(self._load_error or "Gemma vision verifier is not loaded")

        prompt = _build_verification_prompt(candidate_text)
        prepared_image = self._prepare_image(image)
        if is_ollama_verification_model(model_id):
            raw_response = self._generate_ollama(
                prepared_image,
                prompt,
                max_new_tokens=max_new_tokens,
                timeout=self.OLLAMA_VERIFY_TIMEOUT_SEC,
            )
        else:
            raw_response = self._generate_hf(prepared_image, prompt, max_new_tokens=max_new_tokens)
        try:
            result = parse_verification_response(raw_response, model_id=model_id)
            log_info(
                "Gemma verification response: "
                f"model={result.model_id}, matches={result.matches}, "
                f"confidence={result.confidence:.2f}, "
                f"corrected={_preview(result.corrected_text)!r}, "
                f"reason={_preview(result.reason, 80)!r}"
            )
            return result
        except Exception as exc:
            log_warning(f"Gemma verification returned non-JSON output: {exc}")
            return VisionVerificationResult(
                matches=None,
                corrected_text=candidate_text,
                confidence=0.0,
                reason="verifier returned an unparsable response",
                raw_response=raw_response,
                model_id=model_id,
            )

    def unload_model(self, wait: bool = True) -> None:
        acquired = self._load_lock.acquire(blocking=wait)
        if not acquired:
            log_warning(
                "Gemma vision verifier is still loading during shutdown; "
                "process exit will interrupt it."
            )
            return

        try:
            ollama_model_id = self._model_id if self._backend == "ollama" else ""
            if ollama_model_id:
                self._unload_ollama_model(ollama_model_id)

            self._model = None
            self._processor = None
            self._model_id = ""
            self._backend = ""
            self._load_error = None
            self._failed_model_id = ""
            self._load_retry_after = 0.0
            self._is_loading = False
            self._load_event.set()
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
        finally:
            self._load_lock.release()

    def _unload_ollama_model(self, model_id: str) -> None:
        ollama_model = get_ollama_model_name(model_id)
        if not ollama_model:
            return
        try:
            _post_ollama_json(
                "/api/generate",
                {
                    "model": ollama_model,
                    "prompt": "",
                    "stream": False,
                    "keep_alive": 0,
                },
                timeout=10.0,
            )
            log_info(f"Ollama vision verifier unloaded: {ollama_model}")
        except Exception as exc:
            log_warning(f"Failed to unload Ollama vision verifier {ollama_model}: {exc}")

    def _load_model(self, model_id: str) -> None:
        with self._load_lock:
            target_backend = "ollama" if is_ollama_verification_model(model_id) else "hf"
            if self.is_loaded and self._model_id == model_id:
                self._is_loading = False
                self._load_event.set()
                return
            if self.is_loaded and (self._model_id != model_id or self._backend != target_backend):
                self.unload_model()
            if (
                not self.is_loaded
                and self._failed_model_id == model_id
                and time.monotonic() < self._load_retry_after
            ):
                self._is_loading = False
                self._load_event.set()
                retry_in = max(1, int(self._load_retry_after - time.monotonic()))
                raise RuntimeError(
                    f"Gemma vision verifier load previously failed; "
                    f"retrying in {retry_in}s ({self._load_error or 'unknown error'})."
                )

            self._load_error = None
            try:
                log_info(f"Loading Gemma vision verifier: {model_id}")
                if target_backend == "ollama":
                    self._load_ollama_model(model_id)
                    return

                try:
                    from transformers import AutoModelForImageTextToText, AutoProcessor
                except ImportError as exc:
                    raise RuntimeError(
                        "Transformers with Gemma 4 image-text support is required. "
                        "Install or upgrade transformers, accelerate, and torchvision."
                    ) from exc

                self._processor = _load_processor(AutoProcessor, model_id)
                self._model = _load_image_text_model(AutoModelForImageTextToText, model_id)
                self._model_id = model_id
                self._backend = "hf"
                self._failed_model_id = ""
                self._load_retry_after = 0.0
                log_info(f"Gemma vision verifier loaded: {model_id}")
            except Exception as exc:
                self._model = None
                self._processor = None
                self._model_id = ""
                self._backend = ""
                self._failed_model_id = model_id
                self._load_retry_after = time.monotonic() + self.FAILED_LOAD_RETRY_SEC
                self._load_error = str(exc)
                log_error(f"Failed to load Gemma vision verifier: {exc}")
            finally:
                self._is_loading = False
                self._load_event.set()

    def _prepare_image(self, image: Image.Image) -> Image.Image:
        prepared = image.convert("RGB") if image.mode != "RGB" else image
        width, height = prepared.size
        max_edge = max(width, height)
        if max_edge <= self.MAX_IMAGE_EDGE:
            return prepared

        scale = self.MAX_IMAGE_EDGE / max_edge
        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        return prepared.resize(new_size, Image.Resampling.LANCZOS)

    def _load_ollama_model(self, model_id: str) -> None:
        ollama_model = get_ollama_model_name(model_id)
        if not ollama_model:
            raise RuntimeError("Ollama model name is empty")

        response = _post_ollama_json(
            "/api/generate",
            {
                "model": ollama_model,
                "prompt": 'Return only {"ready": true}.',
                "format": "json",
                "stream": False,
                "keep_alive": "30m",
                "options": {
                    "temperature": 0,
                    "num_predict": 16,
                },
            },
            timeout=self.OLLAMA_LOAD_TIMEOUT_SEC,
        )
        if "error" in response:
            raise RuntimeError(str(response["error"]))

        self._model_id = model_id
        self._backend = "ollama"
        self._failed_model_id = ""
        self._load_retry_after = 0.0
        log_info(f"Ollama vision verifier ready: {ollama_model}")

    def _generate_hf(self, image: Image.Image, prompt: str, max_new_tokens: int) -> str:
        processor = self._processor
        model = self._model
        if processor is None or model is None:
            raise RuntimeError("Gemma vision verifier is not loaded")

        inputs = self._build_inputs(processor, model, image, prompt)
        input_len = inputs["input_ids"].shape[-1] if "input_ids" in inputs else 0
        context = _torch_inference_context()
        with context:
            output = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
            )

        generated = output[0][input_len:] if input_len else output[0]
        decoder = getattr(processor, "decode", None)
        if callable(decoder):
            return decoder(generated, skip_special_tokens=True).strip()

        tokenizer = getattr(processor, "tokenizer", None)
        if tokenizer is not None and hasattr(tokenizer, "decode"):
            return tokenizer.decode(generated, skip_special_tokens=True).strip()
        return str(generated)

    def _build_inputs(self, processor, model, image: Image.Image, prompt: str):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        try:
            inputs = processor.apply_chat_template(
                messages,
                tokenize=True,
                return_dict=True,
                return_tensors="pt",
                add_generation_prompt=True,
            )
        except Exception as exc:
            log_debug(f"Gemma chat template image path failed, using processor fallback: {exc}")
            inputs = processor(
                text="<|image|>\n\n" + prompt,
                images=image,
                return_tensors="pt",
            )

        device = getattr(model, "device", None)
        if device is not None and hasattr(inputs, "to"):
            inputs = inputs.to(device)
        return inputs

    def _generate_ollama(
        self,
        image: Image.Image,
        prompt: str,
        max_new_tokens: int,
        timeout: float,
    ) -> str:
        ollama_model = get_ollama_model_name(self._model_id)
        if not ollama_model:
            raise RuntimeError("Ollama verifier model is not loaded")

        response = _post_ollama_json(
            "/api/generate",
            {
                "model": ollama_model,
                "prompt": prompt,
                "images": [_image_to_base64_png(image)],
                "format": "json",
                "stream": False,
                "keep_alive": "30m",
                "options": {
                    "temperature": 0,
                    "top_p": 1,
                    "num_predict": max_new_tokens,
                },
            },
            timeout=timeout,
        )
        if "error" in response:
            raise RuntimeError(str(response["error"]))
        return str(response.get("response") or "")


def get_gemma_vision_verifier() -> GemmaVisionVerifier:
    """Return the global Gemma vision verifier."""
    return GemmaVisionVerifier()


def _load_processor(auto_processor, model_id: str):
    try:
        return auto_processor.from_pretrained(model_id, padding_side="left")
    except TypeError:
        return auto_processor.from_pretrained(model_id)


def _load_image_text_model(auto_model, model_id: str):
    load_attempts = (
        {"device_map": "auto", "attn_implementation": "sdpa"},
        {"device_map": "auto"},
        {},
    )
    last_error: Optional[Exception] = None
    for kwargs in load_attempts:
        try:
            return auto_model.from_pretrained(model_id, **kwargs)
        except TypeError as exc:
            last_error = exc
            continue
        except ImportError as exc:
            last_error = exc
            continue
        except ValueError as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    return auto_model.from_pretrained(model_id)


def _build_verification_prompt(candidate_text: str) -> str:
    return (
        "You are verifying OCR against an image.\n\n"
        "OCR result:\n"
        f"{candidate_text}\n\n"
        "Task:\n"
        "1. Compare each visible character in the image to the OCR result.\n"
        "2. Judge only by visible strokes and spacing.\n"
        "3. Do not use grammar, word likelihood, dictionary knowledge, or context.\n"
        "4. Rare or unusual characters may be correct.\n"
        "5. If the OCR differs from the image, return the exact text visible in the image.\n"
        "6. Preserve line breaks when they are visible.\n"
        "7. If unsure, set matches to false only when the visual mismatch is clear.\n\n"
        "Return JSON only with this schema:\n"
        "{\n"
        '  "matches": true,\n'
        '  "corrected_text": "",\n'
        '  "confidence": 0.0,\n'
        '  "uncertain_chars": [],\n'
        '  "reason": "brief visual reason"\n'
        "}\n"
    )


def _extract_json_payload(raw: str) -> str:
    fence_match = _JSON_FENCE_RE.search(raw)
    if fence_match:
        return fence_match.group(1).strip()

    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        return raw[start:end + 1]
    return raw


def _parse_confidence(value: object) -> float:
    try:
        return _clamp_confidence(float(value), 0.0)
    except (TypeError, ValueError):
        return 0.0


def _clamp_confidence(value: float, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0.0, min(1.0, parsed))


def _looks_like_short_dense_cjk(text: str) -> bool:
    compact = _WHITESPACE_RE.sub("", text)
    if len(compact) < 2 or len(compact) > 8:
        return False
    cjk_count = len(_CJK_RE.findall(compact))
    return cjk_count >= 2 and cjk_count / len(compact) >= 0.75


def _format_text_change(prefix: str, before: str, after: str) -> str:
    return f"{prefix}: {_preview(before)} -> {_preview(after)}"


def _preview(text: str, limit: int = 40) -> str:
    one_line = " ".join(text.split())
    if len(one_line) <= limit:
        return one_line
    return one_line[: limit - 3] + "..."


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item and item not in seen:
            ordered.append(item)
            seen.add(item)
    return ordered


def _torch_inference_context():
    try:
        import torch

        return torch.inference_mode()
    except Exception:
        return nullcontext()


def _post_ollama_json(path: str, payload: dict, timeout: float) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = url_request.Request(
        OLLAMA_BASE_URL + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with url_request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except url_error.URLError as exc:
        raise RuntimeError(f"Ollama request failed: {exc}") from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Ollama returned non-JSON response: {raw[:200]}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Ollama returned an unexpected response")
    return parsed


def _image_to_base64_png(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")
