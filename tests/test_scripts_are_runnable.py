"""Regression test for a real bug caught during Docker verification:
`python scripts/backup.py` (a plain script path, exactly how deploy/backup.sh
and the seed instructions invoke it) couldn't `import app...` because only
the script's own directory lands on sys.path, not the repo root — unlike
`python -m app.main`, which works differently. tests/test_backup_script.py
imports scripts.backup as a module and never hits this, so it slipped
through; this runs the scripts as real subprocesses with a clean env,
the way Docker/cron actually invoke them, mirroring the Dockerfile's
PYTHONPATH=/app fix.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def _run(args: list[str]) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    return subprocess.run(
        [sys.executable, *args], cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=15
    )


def test_seed_script_imports_app_package_without_module_not_found_error():
    result = _run(["scripts/seed.py"])
    assert "ModuleNotFoundError" not in result.stderr
    # it should fail for a *different* reason: missing ADMIN_USER_ID
    assert "ADMIN_USER_ID" in result.stderr or result.returncode != 0


def test_backup_script_imports_app_package_without_module_not_found_error(tmp_path):
    result = _run(["scripts/backup.py", str(tmp_path)])
    assert "ModuleNotFoundError" not in result.stderr
