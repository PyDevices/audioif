#!/usr/bin/env python3
"""Verify mixer, delay, and MIDI PCM against committed oracle metadata."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
PARITY = Path(__file__).parent
fixture = json.loads(
    (PARITY / "golden" / "streaming_component.json").read_text())
environment = os.environ.copy()
environment["PYTHONPATH"] = str(ROOT)

for name in ("streaming", "midi"):
    result = subprocess.run(
        [sys.executable, str(PARITY / f"{name}_component_probe.py")],
        cwd=ROOT, env=environment, capture_output=True, check=False,
    )
    if result.returncode:
        sys.stderr.buffer.write(result.stdout)
        sys.stderr.buffer.write(result.stderr)
        raise SystemExit(result.returncode)
    actual = hashlib.sha256(result.stdout).hexdigest()
    expected = fixture[f"{name}_stdout_sha256"]
    if actual != expected:
        raise SystemExit(
            f"{name} PCM does not match the CircuitPython oracle metadata: "
            f"expected {expected}, got {actual}")
    print(f"CPython {name} parity matches", actual)
