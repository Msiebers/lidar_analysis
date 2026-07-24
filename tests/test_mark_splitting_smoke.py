#!/usr/bin/env python3
"""
Compatibility wrapper for the canonical splitting-style smoke test.

Historically this file duplicated `test_splitting_style_smoke.py` exactly.
Keep the filename for anyone running it directly, but delegate to the
canonical test body so the assertions stay in one place.
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from tests.test_splitting_style_smoke import (
        test_splitting_style_resolution_smoke as _run_splitting_style_resolution_smoke,
    )
except ModuleNotFoundError as exc:
    if exc.name != "tests":
        raise
    from test_splitting_style_smoke import (
        test_splitting_style_resolution_smoke as _run_splitting_style_resolution_smoke,
    )


def test_mark_splitting_resolution_smoke() -> None:
    _run_splitting_style_resolution_smoke()


if __name__ == "__main__":
    test_mark_splitting_resolution_smoke()
    print("PASS")
