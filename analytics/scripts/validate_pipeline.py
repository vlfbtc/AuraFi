"""Compatibility entrypoint for the canonical dependency-free validator."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


if __name__ == "__main__":
    validator = Path(__file__).resolve().parents[1] / "validate_pipeline.py"
    namespace = runpy.run_path(str(validator))
    sys.exit(namespace["main"]())
