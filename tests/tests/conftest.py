"""Ensure the toy fixture tree exists before tests run."""
import subprocess
import sys
from pathlib import Path

FIX = Path(__file__).resolve().parents[1] / "fixtures"
if not (FIX / "client_app" / "client_app" / "titles.py").exists():
    subprocess.run([sys.executable, str(FIX / "make_fixtures.py")],
                   check=True)
