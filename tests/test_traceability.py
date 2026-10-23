"""Traceability table cannot silently omit a requirement."""

import subprocess
import sys
from pathlib import Path


def test_traceability_is_complete() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "check_traceability.py")],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
