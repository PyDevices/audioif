#!/usr/bin/env python3
"""Verify deterministic effect PCM against committed oracle metadata.

The gate is an exact hash, and on the reference architecture it stays one:
audioif's whole parity apparatus rests on this target reproducing the
CircuitPython oracle byte for byte, and a tolerance there would quietly
retire the property the accuracy program is built on.

**Bit-identical audio is required within one CPU architecture, not across
them** (Brad, 2026-09-02). The oracle hash in `effects_component.json` was
captured on x86_64; aarch64 does not reproduce it, and is not expected to.
Floating-point contraction (a compiler fusing `a*b+c` into one fused
multiply-add, which rounds once instead of twice) and differing libm
implementations both legitimately move the last bit, and both differ
between the two architectures.

"Different" must not be allowed to become a synonym for "wrong", though, so
a non-reference architecture is not simply excused. It is held to a bounded
difference from the committed reference output, and this module reports the
size and location of every deviation rather than only that a hash moved -- a
gate that says "the hash differs" and nothing else cannot distinguish
last-bit noise from a broken effect.
"""

import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
GOLDEN = Path(__file__).parent / "golden"

# The architecture the oracle hash was captured on. Only here is the exact
# hash the gate; elsewhere it is a reference to measure against.
REFERENCE_MACHINE = "x86_64"

fixture_path = GOLDEN / "effects_component.json"
fixture = json.loads(fixture_path.read_text())
reference_path = GOLDEN / "effects_component_stdout.txt"

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
actual_bytes = result.stdout.replace(b"\r\n", b"\n")
actual = hashlib.sha256(actual_bytes).hexdigest()
expected = fixture["cpython_stdout_sha256"]

# The committed reference text and the committed hash describe the same
# run. If they ever drift, every number below is measured against the wrong
# baseline, so check it before trusting either.
reference_bytes = reference_path.read_bytes().replace(b"\r\n", b"\n")
reference_hash = hashlib.sha256(reference_bytes).hexdigest()
if reference_hash != expected:
    raise SystemExit(
        f"{reference_path.name} does not match cpython_stdout_sha256 in "
        f"{fixture_path.name} ({reference_hash} vs {expected}). One of the "
        "two was regenerated without the other; fix that before reading any "
        "comparison below, which would be measured against a stale baseline."
    )

if actual == expected:
    raise SystemExit(0)

NUMBER = re.compile(r"-?\d+")


def deviations(ref_text, got_text):
    """Every numeric field that moved, as (line_no, index, ref, got)."""
    ref_lines = ref_text.splitlines()
    got_lines = got_text.splitlines()
    if len(ref_lines) != len(got_lines):
        raise SystemExit(
            f"probe emitted {len(got_lines)} lines, reference has "
            f"{len(ref_lines)} -- a structural difference, not a numeric one"
        )
    out = []
    for n, (r, g) in enumerate(zip(ref_lines, got_lines), 1):
        if r == g:
            continue
        rn = [int(v) for v in NUMBER.findall(r)]
        gn = [int(v) for v in NUMBER.findall(g)]
        if len(rn) != len(gn) or NUMBER.sub("", r) != NUMBER.sub("", g):
            raise SystemExit(
                f"line {n} differs in shape, not just value:\n"
                f"  reference: {r}\n  got:       {g}"
            )
        for i, (a, b) in enumerate(zip(rn, gn)):
            if a != b:
                out.append((n, i, a, b))
    return out


ref_text = reference_bytes.decode()
got_text = actual_bytes.decode()
moved = deviations(ref_text, got_text)

total_fields = len(NUMBER.findall(ref_text))
worst_abs = max((abs(b - a), n, i, a, b) for _, n, i, a, b in
                ((0, *m) for m in moved)) if moved else (0, 0, 0, 0, 0)
# Relative deviation is measured only where the reference is non-zero. A
# field that moved off zero has no meaningful ratio, and letting it report
# inf would hide the real magnitude behind an unreadable headline -- these
# numbers exist to be read.
_rel = [(abs(b - a) / abs(a), n, i, a, b)
        for _, n, i, a, b in ((0, *m) for m in moved) if a]
worst_rel = max(_rel) if _rel else (0, 0, 0, 0, 0)
from_zero = len(moved) - len(_rel)

machine = platform.machine()
report = [
    "effect PCM does not match the CircuitPython oracle metadata",
    f"  expected {expected}",
    f"  got      {actual}",
    f"  machine  {machine} (reference architecture: {REFERENCE_MACHINE})",
    "",
    f"  {len(moved)} of {total_fields} numeric fields differ",
    f"  largest absolute deviation: {worst_abs[0]} "
    f"(line {worst_abs[1]}, field {worst_abs[2]}: "
    f"{worst_abs[3]} -> {worst_abs[4]})",
    f"  largest relative deviation: {worst_rel[0]:.3e} "
    f"(line {worst_rel[1]}, field {worst_rel[2]}: "
    f"{worst_rel[3]} -> {worst_rel[4]})"
    + (f"; {from_zero} field(s) moved off an exact zero, which have no "
       "ratio and are excluded from that figure" if from_zero else ""),
    "",
    "  first differing lines:",
]
seen = []
for n, i, a, b in moved:
    if n not in seen:
        seen.append(n)
    if len(seen) > 8:
        break
for n in seen[:8]:
    report.append(f"    line {n}")
    report.append(f"      reference: {ref_text.splitlines()[n - 1]}")
    report.append(f"      got:       {got_text.splitlines()[n - 1]}")

if machine == REFERENCE_MACHINE:
    report.append("")
    report.append(
        "  This is the REFERENCE architecture, where the gate is exact. A "
        "deviation here is a real regression, however small -- do not widen "
        "a tolerance to absorb it."
    )
else:
    report.append("")
    report.append(
        f"  {machine} is not the reference architecture. Cross-architecture "
        "bit-identity is NOT required (Brad, 2026-09-02), but the size of "
        "the difference above is what decides whether this is last-bit "
        "floating-point divergence or a real defect. No tolerance is "
        "configured yet: it will be set from measured evidence, not chosen "
        "to make this pass."
    )

raise SystemExit("\n".join(report))
