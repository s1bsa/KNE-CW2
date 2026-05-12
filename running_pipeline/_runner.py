"""
_runner.py — shared subprocess helper used by all running_pipeline wrappers.

Provides:
  REPO_ROOT      — absolute path to the repo root (parent of running_pipeline/)
  run_python(p)  — run a Python script from the repo root with the current interpreter
  run_command(...) — run an arbitrary command from the repo root, optionally
                     redirecting stdout to a file
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent


def run_python(script_path: str) -> None:
    """Run a python script from the repo root using the current interpreter."""
    full = REPO_ROOT / script_path
    if not full.exists():
        raise FileNotFoundError(f"Script not found: {full}")

    print(f"\n>>> python3 {script_path}")
    result = subprocess.run(
        [sys.executable, str(full)],
        cwd=REPO_ROOT,
        env=os.environ.copy(),
    )
    if result.returncode != 0:
        raise RuntimeError(f"Step failed: {script_path} (exit {result.returncode})")


def run_command(
    cmd: Sequence[str],
    *,
    stdout_path: Path | None = None,
) -> None:
    """Run an arbitrary command from the repo root, optionally redirecting stdout."""
    print(f"\n>>> {' '.join(str(c) for c in cmd)}")
    if stdout_path is not None:
        stdout_path = Path(stdout_path)
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        with open(stdout_path, "w") as out:
            result = subprocess.run(cmd, cwd=REPO_ROOT, stdout=out)
    else:
        result = subprocess.run(cmd, cwd=REPO_ROOT)

    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(str(c) for c in cmd)} (exit {result.returncode})"
        )
