"""Run the organizers' envelopes/unseal.py safely on any OS.

On Windows, pandas' to_csv writes '\\r\\n' line endings (it defaults to os.linesep), so files that
unseal.py rebuilds fail their fingerprint check. We run unseal.py unchanged, with os.linesep set to
'\\n' (what it was written for) and UTF-8 output so its check marks print on Windows consoles.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

SHIM = ("import os, runpy, sys; os.linesep = '\\n'; "
        "sys.argv = ['unseal.py'] + sys.argv[1:]; "
        "runpy.run_path('envelopes/unseal.py', run_name='__main__')")


def unseal(challenge: pathlib.Path, number: str, words: list[str], capture: bool = False):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    cmd = [sys.executable, "-c", SHIM, number, *words]
    if capture:
        return subprocess.run(cmd, cwd=challenge, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return subprocess.run(cmd, cwd=challenge, env=env)


def opened_dir(challenge: pathlib.Path, number: str) -> pathlib.Path:
    n = number.strip()
    tag = "practice" if n.lower() == "practice" else f"E{int(n.upper().lstrip('E')):02d}"
    return challenge / "envelopes/opened" / tag
