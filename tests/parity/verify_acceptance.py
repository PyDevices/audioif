#!/usr/bin/env python3
"""Require CPython acceptance stdout to match the committed oracle."""

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
fixture = json.loads((Path(__file__).parent / "golden" / "synthtools_acceptance.json").read_text())
environment = os.environ.copy()
environment["PYTHONPATH"] = os.pathsep.join(
    (str(ROOT / "tests" / "support"), str(ROOT / "tests" / "vendor"), str(ROOT))
)
result = subprocess.run(
    [sys.executable, str(Path(__file__).parent / "synthtools_acceptance.py")],
    cwd=ROOT,
    env=environment,
    capture_output=True,
    text=True,
    check=False,
)
if result.returncode:
    sys.stderr.write(result.stdout)
    sys.stderr.write(result.stderr)
    raise SystemExit(result.returncode)
actual = result.stdout.splitlines()
expected = fixture["stdout"]
if actual != expected:
    sys.stderr.write("CPython PCM acceptance does not match the CircuitPython 10.2.1 oracle\n")
    sys.stderr.write("expected:\n" + "\n".join(expected) + "\nactual:\n" + "\n".join(actual) + "\n")
    raise SystemExit(1)
print("CPython acceptance matches", fixture["sha256"])
