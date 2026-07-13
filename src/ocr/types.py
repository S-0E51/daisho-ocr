"""
Shared OCR result types.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class OCRAnalysisResult:
    """Structured OCR output with optional confidence metadata."""

    text: str
    average_confidence: Optional[float] = None
    used_retry: bool = False
