from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def resolve_eval_python() -> str:
    override = os.environ.get("SWE_EVAL_PYTHON")
    if override:
        return override

    venv_python = ROOT / ".venv" / "bin" / "python3"
    swebench_roots = list((ROOT / ".venv" / "lib").glob("python*/site-packages/swebench"))
    if venv_python.exists() and swebench_roots:
        return str(venv_python)

    return sys.executable
