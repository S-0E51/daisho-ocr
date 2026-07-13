"""
Shared helpers for script-style tests.
"""

from __future__ import annotations

import sys
from pathlib import Path


def bootstrap() -> Path:
    """Configure UTF-8 console output and add the project root to sys.path."""
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    return project_root
