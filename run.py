#!/usr/bin/env python3
"""Cross-platform launcher: creates .venv and installs requirements on first use, then runs reel.py inside it.

    python run.py examples/en.txt --handle @you          (Windows: py run.py ...)
    python run.py --setup
    python run.py long project.md --meta project.json        (long-form videos, minutes to hours)
Works the same on Windows, macOS and Linux.
"""
import os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
MARK = VENV / ".deps_installed"


def main():
    if sys.version_info < (3, 10):
        sys.exit("Python 3.10 or newer is required (you have %d.%d)." % sys.version_info[:2])
    if not PY.exists():
        print("First run: creating virtual environment ...", flush=True)
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
    if not MARK.exists():
        print("First run: installing requirements (a few minutes) ...", flush=True)
        subprocess.check_call([str(PY), "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements.txt")])
        MARK.write_text("ok")
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    args = sys.argv[1:]
    target = "reel.py"
    if args and args[0] in ("long", "video"):       # python run.py long project.md ...
        target, args = "long.py", args[1:]
    sys.exit(subprocess.call([str(PY), str(ROOT / target), *args], env=env, cwd=ROOT))


if __name__ == "__main__":
    main()
