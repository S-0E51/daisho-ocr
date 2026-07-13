"""
Conservative post-OCR correction for Japanese text.

Phase 1 intentionally limits itself to small-kana confusions that are very
common in OCR output:
- つ -> っ
- や/ゆ/よ -> ゃ/ゅ/ょ
- Katakana equivalents

The corrector uses fugashi/UniDic when available and only applies a change
when either:
1. the tokenizer already normalizes the token's reading/form to the corrected
   kana surface, or
2. a local replacement produces a meaningfully cleaner morphological parse.

This keeps the module conservative and avoids freeform rewrites.
"""

from __future__ import annotations

from dataclasses import dataclass
import itertools
import threading
import re
from typing import Iterable, Optional

from ..utils.logger import log_debug, log_warning

try:
    from fugashi import Tagger

    FUGASHI_AVAILABLE = True
except ImportError:
    Tagger = None
    FUGASHI_AVAILABLE = False


TEXT_CORRECTION_CACHE_TAG = "jp-safe-v1"

_HIGH_CONFIDENCE_DIRECT_REPLACEMENTS = (
    ("\u306b\u3087\u3063\u3066\u306f", "\u306b\u3088\u3063\u3066\u306f"),
    ("\u306b\u3087\u3063\u3066\u3082", "\u306b\u3088\u3063\u3066\u3082"),
    ("\u306b\u3087\u3063\u3066", "\u306b\u3088\u3063\u3066"),
    ("\u306b\u3087\u308c\u3070", "\u306b\u3088\u308c\u3070"),
    ("\u306b\u3087\u308b\u3068", "\u306b\u3088\u308b\u3068"),
    ("\u306b\u3087\u308b", "\u306b\u3088\u308b"),
    ("\u306b\u3087\u308a", "\u306b\u3088\u308a"),
)
_PROTECTED_PHRASES = tuple(correct for _, correct in _HIGH_CONFIDENCE_DIRECT_REPLACEMENTS)

_LARGE_TO_SMALL = {
    "つ": "っ",
    "や": "ゃ",
    "ゆ": "ゅ",
    "よ": "ょ",
    "ツ": "ッ",
    "ヤ": "ャ",
    "ユ": "ュ",
    "ヨ": "ョ",
}
_HIRAGANA_RANGE = range(ord("ぁ"), ord("ゖ") + 1)
_KATAKANA_RANGE = range(ord("ァ"), ord("ヶ") + 1)
_KATAKANA_EXTRA = {"ー", "ヷ", "ヸ", "ヹ", "ヺ", "ヽ", "ヾ"}
_YOON_BASE_HIRAGANA = set("きぎしじちぢにひびぴみりゔ")
_YOON_BASE_KATAKANA = set("キギシジチヂニヒビピミリヴ")
_SOKUON_FOLLOW_HIRAGANA = set("かきくけこさしすせそたちつてとはひふへほぱぴぷぺぽ")
_SOKUON_FOLLOW_KATAKANA = set("カキクケコサシスセソタチツテトハヒフヘホパピプペポ")
_CONTENT_POS = {"名詞", "動詞", "形容詞", "形状詞", "副詞", "連体詞", "感動詞", "接続詞"}
_WHITESPACE_SPLIT_RE = re.compile(r"(\s+)")


@dataclass(frozen=True)
class CorrectionResult:
    """Output of the correction pipeline."""

    text: str
    corrections: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return bool(self.corrections)


@dataclass(frozen=True)
class _SpanAnalysis:
    text: str
    token_count: int
    content_token_count: int
    symbol_token_count: int
    helper_token_count: int
    single_char_kana_count: int
    score: int


class JapaneseTextCorrector:
    """Conservative Japanese text corrector for OCR output."""

    MAX_PASSES = 3
    MAX_WINDOW_TOKENS = 4
    MAX_WINDOW_CHARS = 12
    MIN_IMPROVEMENT_SCORE = 4

    _instance: Optional["JapaneseTextCorrector"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "JapaneseTextCorrector":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return

        self._tagger = None
        if FUGASHI_AVAILABLE:
            try:
                self._tagger = Tagger()
            except Exception as exc:
                log_warning(f"Failed to initialize fugashi post-corrector: {exc}")
                self._tagger = None

        self._initialized = True

    @property
    def available(self) -> bool:
        return self._tagger is not None

    def correct(self, text: str) -> CorrectionResult:
        """Return a conservatively corrected version of OCR text."""
        if not text or not text.strip():
            return CorrectionResult(text=text)

        if self._tagger is None:
            return CorrectionResult(text=text)

        parts = _WHITESPACE_SPLIT_RE.split(text)
        corrected_parts: list[str] = []
        corrections: list[str] = []
        seen_notes: set[str] = set()

        for part in parts:
            if not part or part.isspace():
                corrected_parts.append(part)
                continue

            corrected_part, part_notes = self._correct_segment(part)
            corrected_parts.append(corrected_part)
            for note in part_notes:
                if note not in seen_notes:
                    corrections.append(note)
                    seen_notes.add(note)

        corrected_text = "".join(corrected_parts)
        if corrections:
            log_debug(
                "Post-OCR correction applied: "
                + " | ".join(note.encode("unicode_escape").decode() for note in corrections)
            )
        return CorrectionResult(text=corrected_text, corrections=tuple(corrections))

    def _correct_segment(self, segment: str) -> tuple[str, tuple[str, ...]]:
        if self._tagger is None or not _contains_kana(segment):
            return segment, ()

        current = segment
        corrections: list[str] = []
        seen_notes: set[str] = set()

        current, direct_notes = self._apply_high_confidence_replacements(current)
        for note in direct_notes:
            if note not in seen_notes:
                corrections.append(note)
                seen_notes.add(note)

        for _ in range(self.MAX_PASSES):
            changed = False

            next_value, notes = self._apply_form_based_token_corrections(current)
            if next_value != current:
                current = next_value
                changed = True
                for note in notes:
                    if note not in seen_notes:
                        corrections.append(note)
                        seen_notes.add(note)

            next_value, note = self._apply_window_correction(current)
            if next_value != current:
                current = next_value
                changed = True
                if note and note not in seen_notes:
                    corrections.append(note)
                    seen_notes.add(note)

            if not changed:
                break

        return current, tuple(corrections)

    def _apply_form_based_token_corrections(self, segment: str) -> tuple[str, tuple[str, ...]]:
        tokens = self._tokenize(segment)
        if not tokens:
            return segment, ()

        corrected_tokens: list[str] = []
        corrections: list[str] = []
        changed = False

        for token in tokens:
            candidate = self._token_form_candidate(token)
            if candidate is None:
                corrected_tokens.append(token.surface)
                continue

            corrected_tokens.append(candidate)
            corrections.append(f"{token.surface} -> {candidate}")
            changed = True

        if not changed:
            return segment, ()

        return "".join(corrected_tokens), tuple(corrections)

    def _apply_window_correction(self, segment: str) -> tuple[str, Optional[str]]:
        tokens = self._tokenize(segment)
        if len(tokens) < 2:
            return segment, None

        best_replacement: Optional[tuple[int, int, str, str, int]] = None
        prefix_lengths = [0]
        for token in tokens:
            prefix_lengths.append(prefix_lengths[-1] + len(token.surface))

        for start in range(len(tokens)):
            max_end = min(len(tokens), start + self.MAX_WINDOW_TOKENS)
            for end in range(start + 2, max_end + 1):
                window_tokens = tokens[start:end]
                span = "".join(token.surface for token in window_tokens)
                if len(span) > self.MAX_WINDOW_CHARS or not _is_kana_text(span):
                    continue

                candidates = self._generate_confusion_candidates(span)
                if not candidates:
                    continue

                original_analysis = self._analyze_tokens(window_tokens, span)
                for candidate in candidates:
                    if self._should_block_window_replacement(span, candidate):
                        continue
                    candidate_tokens = self._tokenize(candidate)
                    candidate_analysis = self._analyze_tokens(candidate_tokens, candidate)
                    improvement = candidate_analysis.score - original_analysis.score
                    if not self._is_strong_upgrade(original_analysis, candidate_analysis):
                        continue

                    note = f"{span} -> {candidate}"
                    if best_replacement is None or improvement > best_replacement[4]:
                        best_replacement = (start, end, candidate, note, improvement)

        if best_replacement is None:
            return segment, None

        start, end, candidate, note, _ = best_replacement
        start_offset = prefix_lengths[start]
        end_offset = prefix_lengths[end]
        updated = f"{segment[:start_offset]}{candidate}{segment[end_offset:]}"
        return updated, note

    def _apply_high_confidence_replacements(self, segment: str) -> tuple[str, tuple[str, ...]]:
        updated = segment
        corrections: list[str] = []
        for source, target in _HIGH_CONFIDENCE_DIRECT_REPLACEMENTS:
            if source not in updated:
                continue
            updated = updated.replace(source, target)
            corrections.append(f"{source} -> {target}")
        return updated, tuple(corrections)

    def _should_block_window_replacement(self, original: str, candidate: str) -> bool:
        for phrase in _PROTECTED_PHRASES:
            if phrase in original and phrase not in candidate:
                return True
        return False

    def _token_form_candidate(self, token) -> Optional[str]:
        surface = token.surface
        if not _is_kana_text(surface):
            return None

        script = _script_name(surface)
        if script is None:
            return None

        form_candidate = self._get_token_form_text(token, script)
        if not form_candidate or form_candidate == surface:
            return None

        if not _is_confusion_variant(surface, form_candidate):
            return None

        return form_candidate

    def _get_token_form_text(self, token, script: str) -> Optional[str]:
        feature = token.feature
        form = getattr(feature, "formBase", None) or getattr(feature, "form", None) or ""
        if not form or form == "*":
            return None

        if script == "hiragana":
            return _katakana_to_hiragana(form)
        if script == "katakana":
            return form
        return None

    def _generate_confusion_candidates(self, text: str) -> tuple[str, ...]:
        eligible: list[tuple[int, str]] = []
        chars = list(text)

        for index, _ in enumerate(chars):
            replacement = _confusion_replacement(chars, index)
            if replacement is not None:
                eligible.append((index, replacement))

        if not eligible:
            return ()

        candidates: set[str] = set()
        max_edit_count = min(2, len(eligible))
        for edit_count in range(1, max_edit_count + 1):
            for combo in itertools.combinations(eligible, edit_count):
                candidate_chars = chars[:]
                for index, replacement in combo:
                    candidate_chars[index] = replacement
                candidate = "".join(candidate_chars)
                if candidate != text and _is_confusion_variant(text, candidate):
                    candidates.add(candidate)

        return tuple(sorted(candidates))

    def _is_strong_upgrade(self, original: _SpanAnalysis, candidate: _SpanAnalysis) -> bool:
        if candidate.score - original.score < self.MIN_IMPROVEMENT_SCORE:
            return False

        return (
            candidate.token_count < original.token_count
            or candidate.symbol_token_count < original.symbol_token_count
            or candidate.single_char_kana_count < original.single_char_kana_count
            or candidate.helper_token_count < original.helper_token_count
        )

    def _analyze_tokens(self, tokens: Iterable, text: str) -> _SpanAnalysis:
        token_list = list(tokens)
        content = 0
        symbols = 0
        helpers = 0
        single_char_kana = 0

        for token in token_list:
            pos1 = getattr(token.feature, "pos1", "")
            if pos1 in _CONTENT_POS:
                content += 1
            if pos1 == "記号":
                symbols += 1
            if pos1 in {"助詞", "助動詞"}:
                helpers += 1
            if len(token.surface) == 1 and _is_kana_text(token.surface):
                single_char_kana += 1

        score = 0
        if len(token_list) == 1:
            score += 6
        score += content * 2
        score -= max(0, len(token_list) - 1) * 2
        score -= symbols * 4
        score -= helpers
        score -= single_char_kana * 2

        return _SpanAnalysis(
            text=text,
            token_count=len(token_list),
            content_token_count=content,
            symbol_token_count=symbols,
            helper_token_count=helpers,
            single_char_kana_count=single_char_kana,
            score=score,
        )

    def _tokenize(self, text: str) -> list:
        if self._tagger is None:
            return []
        try:
            return list(self._tagger(text))
        except Exception as exc:
            log_warning(f"Post-correction tokenization failed: {exc}")
            return []


def _confusion_replacement(chars: list[str], index: int) -> Optional[str]:
    char = chars[index]
    replacement = _LARGE_TO_SMALL.get(char)
    if replacement is None:
        return None

    if char in {"つ", "ツ"}:
        if index == 0 or index >= len(chars) - 1:
            return None
        prev_char = chars[index - 1]
        next_char = chars[index + 1]
        if char == "つ":
            if prev_char not in _HIRAGANA_CHARS or next_char not in _SOKUON_FOLLOW_HIRAGANA:
                return None
        else:
            if prev_char not in _KATAKANA_CHARS or next_char not in _SOKUON_FOLLOW_KATAKANA:
                return None
        return replacement

    if index == 0:
        return None

    prev_char = chars[index - 1]
    if char in {"や", "ゆ", "よ"} and prev_char in _YOON_BASE_HIRAGANA:
        return replacement
    if char in {"ヤ", "ユ", "ヨ"} and prev_char in _YOON_BASE_KATAKANA:
        return replacement
    return None


def _is_confusion_variant(original: str, candidate: str) -> bool:
    if len(original) != len(candidate):
        return False

    changed = False
    for orig_char, cand_char in zip(original, candidate):
        if orig_char == cand_char:
            continue
        if _LARGE_TO_SMALL.get(orig_char) != cand_char:
            return False
        changed = True
    return changed


def _contains_kana(text: str) -> bool:
    return any(_is_hiragana_char(ch) or _is_katakana_char(ch) for ch in text)


def _is_kana_text(text: str) -> bool:
    return bool(text) and all(_is_hiragana_char(ch) or _is_katakana_char(ch) for ch in text)


def _script_name(text: str) -> Optional[str]:
    if text and all(_is_hiragana_char(ch) for ch in text):
        return "hiragana"
    if text and all(_is_katakana_char(ch) for ch in text):
        return "katakana"
    return None


def _katakana_to_hiragana(text: str) -> str:
    converted: list[str] = []
    for char in text:
        codepoint = ord(char)
        if codepoint in _KATAKANA_RANGE:
            converted.append(chr(codepoint - 0x60))
        else:
            converted.append(char)
    return "".join(converted)


def _is_hiragana_char(char: str) -> bool:
    return ord(char) in _HIRAGANA_RANGE


def _is_katakana_char(char: str) -> bool:
    return ord(char) in _KATAKANA_RANGE or char in _KATAKANA_EXTRA


_HIRAGANA_CHARS = {chr(codepoint) for codepoint in _HIRAGANA_RANGE}
_KATAKANA_CHARS = {chr(codepoint) for codepoint in _KATAKANA_RANGE}.union(_KATAKANA_EXTRA)

_corrector: Optional[JapaneseTextCorrector] = None


def get_text_corrector() -> JapaneseTextCorrector:
    """Return the process-wide Japanese text corrector instance."""
    global _corrector
    if _corrector is None:
        _corrector = JapaneseTextCorrector()
    return _corrector
