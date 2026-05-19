from __future__ import annotations

import sys as _sys
from pathlib import Path

# Ensure source is importable BEFORE any parser imports
_SRC = Path(__file__).resolve().parent.parent.parent / "src"
if str(_SRC) not in _sys.path:
    _sys.path.insert(0, str(_SRC))

# Now discover parser pipelines
from parsers.registry import ParserRegistry  # noqa: E402

ParserRegistry.discover(force=True)

SAMPLES_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent / "samples"
