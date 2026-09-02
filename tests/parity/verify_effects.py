#!/usr/bin/env python3
"""Verify deterministic effect PCM against committed oracle metadata."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
fixture_path = Path(__file__).parent / "golden" / "effects_component.json"
fixture = json.loads(fixture_path.read_text())
environment = os.environ.copy()
result = subprocess.run(
    [sys.executable, str(Path(__file__).parent / "effects_component_probe.py")],
    cwd=ROOT, env=environment, capture_output=True, check=False,
)
if result.returncode:
    sys.stderr.buffer.write(result.stdout)
    sys.stderr.buffer.write(result.stderr)
    raise SystemExit(result.returncode)
# Windows CPython writes CRLF from the probe subprocesses, so normalise line
# endings before hashing. Without this every Windows job fails on a hash
# mismatch even though the PCM is byte-identical.
actual = hashlib.sha256(result.stdout.replace(b"\r\n", b"\n")).hexdigest()
expected = fixture["cpython_stdout_sha256"]
if actual != expected:
    raise SystemExit(
        "effect PCM does not match the CircuitPython oracle metadata: "
        f"expected {expected}, got {actual}"
    )
print("CPython effect parity matches", actual)
