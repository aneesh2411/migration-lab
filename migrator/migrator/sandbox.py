"""Run a client repo against a given library version in an isolated venv.

Each run copies the client repo into a temp dir, creates a fresh venv,
installs the specified library build from a local path, and executes
pytest plus the behavior snapshot script. Nothing touches the original
repo or the ambient environment.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RunResult:
    tests_passed: bool
    test_output: str
    snapshot: str
    error: str | None = None


def run_in_sandbox(client_src: Path, lib: str | Path,
                   apply: dict[str, str] | None = None) -> RunResult:
    """Copy client_src, overlay apply={relpath: new content}, run tests.

    lib is a local path to a library build or a pip requirement string
    like "pydantic==1.10.13". NOTE: this is dependency isolation, not a
    security sandbox - only run client code you have reviewed.
    """
    tmp = Path(tempfile.mkdtemp(prefix="migration-sandbox-"))
    try:
        work = tmp / "client"
        shutil.copytree(client_src, work)
        for rel, content in (apply or {}).items():
            (work / rel).write_text(content)
        venv = tmp / "venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv)],
                       check=True, capture_output=True)
        py = venv / "bin" / "python"
        subprocess.run([str(py), "-m", "pip", "install", "-q",
                        str(lib), "pytest"],
                       check=True, capture_output=True)
        env_path = f"{work}:{venv}/lib/python3.10/site-packages"
        test = subprocess.run(
            [str(py), "-m", "pytest", "tests", "-q"],
            cwd=work, capture_output=True, text=True,
            env={"PYTHONPATH": env_path, "PATH": "/usr/bin:/bin"})
        snap = subprocess.run(
            [str(py), "snapshot.py"], cwd=work,
            capture_output=True, text=True,
            env={"PYTHONPATH": env_path, "PATH": "/usr/bin:/bin"})
        if snap.returncode != 0:
            return RunResult(False, test.stdout + test.stderr, "",
                             error=f"snapshot failed: {snap.stderr.strip()[:400]}")
        return RunResult(test.returncode == 0,
                         (test.stdout + test.stderr).strip()[-800:],
                         snap.stdout)
    except subprocess.CalledProcessError as e:
        return RunResult(False, "", "", error=str(e)[:400])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
