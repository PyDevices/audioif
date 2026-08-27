#!/usr/bin/env python3
"""Require CPython acceptance stdout to match what this port should produce.

This one used to be a straight byte-for-byte match against CircuitPython
10.2.1, and for tiers 0-5 it was. It is not any more: the biquads here carry
three deliberate deviations (the peaking-EQ sign, per-channel filter state,
and the widened coefficients this file's `circuitpython_stdout` predates), and
this script drives a resonant low-pass sweeping down from 300 Hz at 22050 Hz -
the exact case those deviations exist to fix. See docs/upstream-diff.md.

So the fixture now carries both: `stdout` is what this port produces and is
what gets enforced, and `circuitpython_stdout` is the oracle's own answer, kept
so the size and shape of the divergence stays reviewable rather than being
quietly dropped. Pass --capture to re-record `stdout` after an intended change;
`circuitpython_stdout` is only re-recorded by running this against
`bin/circuitpython` by hand.
"""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
fixture_path = Path(__file__).parent / "golden" / "synthtools_acceptance.json"
fixture = json.loads(fixture_path.read_text())
environment = os.environ.copy()
# tests/support (the ulab shim) and tests/vendor (synthtools) are test-only and
# ship in no wheel, so they still come from the tree. audioif itself is imported
# from the installed package.
environment["PYTHONPATH"] = os.pathsep.join(
    (str(ROOT / "tests" / "support"), str(ROOT / "tests" / "vendor"))
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
digest = hashlib.sha256(result.stdout.replace("\r\n", "\n").encode()).hexdigest()

if "--capture" in sys.argv:
    fixture["stdout"] = actual
    fixture["sha256"] = digest
    fixture_path.write_text(json.dumps(fixture, indent=1, sort_keys=True) + "\n")
    print("captured", digest)
    raise SystemExit(0)

expected = fixture["stdout"]
if actual != expected:
    sys.stderr.write("CPython PCM acceptance does not match this port's "
                     "committed output\n")
    sys.stderr.write("expected:\n" + "\n".join(expected) + "\nactual:\n"
                     + "\n".join(actual) + "\n")
    raise SystemExit(1)
print("CPython acceptance matches", fixture["sha256"])
