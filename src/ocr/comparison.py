"""
Selective multi-engine OCR comparison helpers.

The comparison layer is intentionally conservative:
- it only asks for a secondary OCR pass when enabled
- suspicious-only mode limits expensive second passes to risky results
- the chooser only overrides the primary OCR when the secondary result
  looks materially healthier
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

from .manager import OCREngine, get_engine_name


OCR_COMPARISON_MODE_OFF = "off"
OCR_COMPARISON_MODE_SUSPICIOUS = "suspicious"
OCR_COMPARISON_MODE_ALWAYS = "always"
OCR_COMPARISON_ENGINE_AUTO = "auto"

OCR_COMPARISON_MODE_LABELS = {
    OCR_COMPARISON_MODE_OFF: "Off",
    OCR_COMPARISON_MODE_SUSPICIOUS: "Suspicious Only",
    OCR_COMPARISON_MODE_ALWAYS: "Always Compare",
}

OCR_COMPARISON_ENGINE_LABELS = {
    OCR_COMPARISON_ENGINE_AUTO: "Auto (Recommended)",
    OCREngine.PADDLE_OCR.value: get_engine_name(OCREngine.PADDLE_OCR),
    OCREngine.PADDLE_VL.value: get_engine_name(OCREngine.PADDLE_VL),
    OCREngine.RAPID_OCR.value: get_engine_name(OCREngine.RAPID_OCR),
    OCREngine.MANGA_OCR.value: get_engine_name(OCREngine.MANGA_OCR),
    OCREngine.SURYA.value: get_engine_name(OCREngine.SURYA),
}

_AUTO_ENGINE_FALLBACKS = {
    OCREngine.PADDLE_OCR: OCREngine.MANGA_OCR,
    OCREngine.PADDLE_VL: OCREngine.MANGA_OCR,
    OCREngine.RAPID_OCR: OCREngine.PADDLE_OCR,
    OCREngine.MANGA_OCR: OCREngine.PADDLE_OCR,
    OCREngine.SURYA: OCREngine.PADDLE_OCR,
}

_SUSPICIOUS_PATTERNS: tuple[tuple[re.Pattern[str], str, float], ...] = (
    (
        re.compile(r"\u3066\u3044\u306a[\u3041\u3042](?=(?:\u3068|\u3063|\u3067|\u306d|\u3088|[。、！？!?]|$))"),
        "possible missing \u308b in \u301c\u3066\u3044\u308b",
        3.5,
    ),
    (
        re.compile(r"\u306b\u3087(?=(?:\u3063\u3066|\u308a|\u308b|\u308c\u3070))"),
        "possible \u306b\u3088... misread as \u306b\u3087...",
        3.0,
    ),
)

_WHITESPACE_RE = re.compile(r"\s+")
_HIRAGANA_AND_KATAKANA_RE = re.compile(r"[\u3041-\u3096\u30a1-\u30fa]")
_SMALL_KANA_RE = re.compile(r"[\u3041\u3043\u3045\u3047\u3049\u3063\u3083\u3085\u3087\u308e\u30a1\u30a3\u30a5\u30a7\u30a9\u30c3\u30e3\u30e5\u30e7\u30ee]")


@dataclass(frozen=True)
class OCRCandidate:
    """One OCR candidate that can participate in comparison."""

    engine: OCREngine
    text: str
    raw_text: str
    average_confidence: Optional[float] = None
    corrections: tuple[str, ...] = ()


@dataclass(frozen=True)
class OCRQualityAssessment:
    """Heuristic quality estimate for an OCR candidate."""

    score: float
    suspicious_reasons: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def suspicious(self) -> bool:
        return bool(self.suspicious_reasons)


@dataclass(frozen=True)
class OCRComparisonDecision:
    """Outcome of comparing a primary OCR result with a secondary one."""

    selected: OCRCandidate
    used_secondary: bool
    performed: bool
    notes: tuple[str, ...]
    primary_assessment: OCRQualityAssessment
    secondary_assessment: Optional[OCRQualityAssessment] = None


def normalize_comparison_mode(value: object) -> str:
    """Normalize a comparison mode string to a supported value."""
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in OCR_COMPARISON_MODE_LABELS:
            return normalized
    return OCR_COMPARISON_MODE_OFF


def normalize_comparison_engine(value: object) -> str:
    """Normalize a comparison engine string to a supported value."""
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == OCR_COMPARISON_ENGINE_AUTO:
            return normalized
        try:
            return OCREngine(normalized).value
        except ValueError:
            return OCR_COMPARISON_ENGINE_AUTO
    return OCR_COMPARISON_ENGINE_AUTO


def get_comparison_mode_label(mode: object) -> str:
    """Return the UI-friendly label for a comparison mode."""
    normalized = normalize_comparison_mode(mode)
    return OCR_COMPARISON_MODE_LABELS[normalized]


def get_comparison_engine_label(engine: object) -> str:
    """Return the UI-friendly label for a comparison engine setting."""
    normalized = normalize_comparison_engine(engine)
    return OCR_COMPARISON_ENGINE_LABELS[normalized]


def resolve_comparison_engine(primary_engine: OCREngine, configured_engine: object) -> Optional[OCREngine]:
    """Resolve the secondary comparison engine for a given primary engine."""
    normalized = normalize_comparison_engine(configured_engine)
    if normalized == OCR_COMPARISON_ENGINE_AUTO:
        return _AUTO_ENGINE_FALLBACKS.get(primary_engine)

    try:
        resolved = OCREngine(normalized)
    except ValueError:
        return _AUTO_ENGINE_FALLBACKS.get(primary_engine)

    if resolved == primary_engine:
        return None
    return resolved


def assess_candidate(candidate: OCRCandidate) -> OCRQualityAssessment:
    """Heuristically assess how trustworthy an OCR candidate looks."""
    text = candidate.text.strip()
    if not text:
        return OCRQualityAssessment(
            score=-100.0,
            suspicious_reasons=("empty OCR result",),
        )

    suspicious_reasons: list[str] = []
    notes: list[str] = []
    score = 0.0

    score += min(len(text), 80) * 0.05

    if candidate.average_confidence is not None:
        score += candidate.average_confidence * 12.0
        notes.append(f"{get_engine_name(candidate.engine)} confidence {candidate.average_confidence:.2f}")
        if candidate.average_confidence < 0.78:
            suspicious_reasons.append("low primary confidence")
            score -= 3.0

    for pattern, reason, penalty in _SUSPICIOUS_PATTERNS:
        if pattern.search(text):
            suspicious_reasons.append(reason)
            score -= penalty

    if candidate.corrections:
        notes.append(f"post-correction applied ({len(candidate.corrections)})")
        suspicious_reasons.append("post-correction changed the OCR text")
        score -= min(1.5, len(candidate.corrections) * 0.4)

    kana_chars = _HIRAGANA_AND_KATAKANA_RE.findall(text)
    if kana_chars:
        small_kana_count = len(_SMALL_KANA_RE.findall(text))
        small_kana_ratio = small_kana_count / len(kana_chars)
        if small_kana_ratio > 0.34:
            suspicious_reasons.append("unusually dense small-kana usage")
            score -= 1.5

    if text.count("?") + text.count("\uff1f") >= 2:
        suspicious_reasons.append("multiple question marks in OCR result")
        score -= 1.0

    return OCRQualityAssessment(
        score=score,
        suspicious_reasons=tuple(_dedupe(suspicious_reasons)),
        notes=tuple(_dedupe(notes)),
    )


def should_run_comparison(mode: object, primary_candidate: OCRCandidate) -> tuple[bool, OCRQualityAssessment]:
    """Return whether comparison should run for the primary candidate."""
    normalized_mode = normalize_comparison_mode(mode)
    assessment = assess_candidate(primary_candidate)

    if normalized_mode == OCR_COMPARISON_MODE_OFF:
        return False, assessment
    if normalized_mode == OCR_COMPARISON_MODE_ALWAYS:
        return True, assessment
    return assessment.suspicious, assessment


def compare_candidates(primary_candidate: OCRCandidate, secondary_candidate: OCRCandidate) -> OCRComparisonDecision:
    """Choose the safer OCR candidate between the primary and secondary outputs."""
    primary_assessment = assess_candidate(primary_candidate)
    secondary_assessment = assess_candidate(secondary_candidate)

    primary_name = get_engine_name(primary_candidate.engine)
    secondary_name = get_engine_name(secondary_candidate.engine)

    if not secondary_candidate.text.strip():
        return OCRComparisonDecision(
            selected=primary_candidate,
            used_secondary=False,
            performed=True,
            notes=(f"OCR comparison kept {primary_name}: {secondary_name} returned no text.",),
            primary_assessment=primary_assessment,
            secondary_assessment=secondary_assessment,
        )

    if not primary_candidate.text.strip():
        return OCRComparisonDecision(
            selected=secondary_candidate,
            used_secondary=True,
            performed=True,
            notes=(f"OCR comparison selected {secondary_name}: primary result was empty.",),
            primary_assessment=primary_assessment,
            secondary_assessment=secondary_assessment,
        )

    if _normalize_text(primary_candidate.text) == _normalize_text(secondary_candidate.text):
        note = f"OCR comparison confirmed the result with {secondary_name}."
        return OCRComparisonDecision(
            selected=primary_candidate,
            used_secondary=False,
            performed=True,
            notes=(note,),
            primary_assessment=primary_assessment,
            secondary_assessment=secondary_assessment,
        )

    score_gap = secondary_assessment.score - primary_assessment.score
    if primary_assessment.suspicious and not secondary_assessment.suspicious and score_gap >= -1.0:
        note = _build_selection_note(
            selected_name=secondary_name,
            other_name=primary_name,
            reasons=primary_assessment.suspicious_reasons,
        )
        return OCRComparisonDecision(
            selected=secondary_candidate,
            used_secondary=True,
            performed=True,
            notes=(note,),
            primary_assessment=primary_assessment,
            secondary_assessment=secondary_assessment,
        )

    if score_gap >= 3.0:
        note = f"OCR comparison selected {secondary_name}: it scored more cleanly than {primary_name}."
        return OCRComparisonDecision(
            selected=secondary_candidate,
            used_secondary=True,
            performed=True,
            notes=(note,),
            primary_assessment=primary_assessment,
            secondary_assessment=secondary_assessment,
        )

    if score_gap <= -3.0:
        note = f"OCR comparison kept {primary_name}: {secondary_name} did not look better."
        return OCRComparisonDecision(
            selected=primary_candidate,
            used_secondary=False,
            performed=True,
            notes=(note,),
            primary_assessment=primary_assessment,
            secondary_assessment=secondary_assessment,
        )

    primary_confidence = primary_candidate.average_confidence
    secondary_confidence = secondary_candidate.average_confidence
    if (
        primary_confidence is not None
        and secondary_confidence is not None
        and secondary_confidence >= primary_confidence + 0.08
        and len(secondary_candidate.text) >= max(2, len(primary_candidate.text) - 1)
        and not secondary_assessment.suspicious
    ):
        note = f"OCR comparison selected {secondary_name}: stronger confidence on a comparable read."
        return OCRComparisonDecision(
            selected=secondary_candidate,
            used_secondary=True,
            performed=True,
            notes=(note,),
            primary_assessment=primary_assessment,
            secondary_assessment=secondary_assessment,
        )

    if primary_assessment.suspicious and not _contains_suspicious_pattern(secondary_candidate.text):
        note = _build_selection_note(
            selected_name=secondary_name,
            other_name=primary_name,
            reasons=primary_assessment.suspicious_reasons,
        )
        return OCRComparisonDecision(
            selected=secondary_candidate,
            used_secondary=True,
            performed=True,
            notes=(note,),
            primary_assessment=primary_assessment,
            secondary_assessment=secondary_assessment,
        )

    return OCRComparisonDecision(
        selected=primary_candidate,
        used_secondary=False,
        performed=True,
        notes=(f"OCR comparison kept {primary_name}: the secondary read was not clearly safer.",),
        primary_assessment=primary_assessment,
        secondary_assessment=secondary_assessment,
    )


def _contains_suspicious_pattern(text: str) -> bool:
    return any(pattern.search(text) for pattern, _, _ in _SUSPICIOUS_PATTERNS)


def _normalize_text(text: str) -> str:
    return _WHITESPACE_RE.sub("", text or "")


def _build_selection_note(selected_name: str, other_name: str, reasons: tuple[str, ...]) -> str:
    if reasons:
        return (
            f"OCR comparison selected {selected_name}: {other_name} looked suspicious "
            f"({', '.join(reasons)})."
        )
    return f"OCR comparison selected {selected_name}: it looked safer than {other_name}."


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item not in seen:
            ordered.append(item)
            seen.add(item)
    return ordered
