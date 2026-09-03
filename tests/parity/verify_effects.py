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

"Different" must not be allowed to become a synonym for "wrong", so an
architecture is not simply excused -- it is held to **its own exact hash**,
recorded in `cpython_stdout_sha256_by_arch` only after a human has read the
deviation report and accepted it. No numeric tolerance is configured
anywhere, deliberately: the gate stays exact on every architecture, which
is both a faithful reading of the rule above and a stronger regression
detector than any threshold. Accepting a new architecture is a deliberate
act with its evidence written down beside the hash; drifting through a
tolerance is not.

A tolerance would also have been measuring the wrong thing. **What this
gate hashes is the probe's stdout, and that stdout carries per-block
`sum(data)` values, not PCM** -- so two samples drifting in opposite
directions inside one block leave the sum, and therefore the hash,
unchanged. The gate is a sum-level check wearing a PCM-level name. That
predates this change and is tracked separately; strengthening it means
changing the probe's output format, which invalidates the committed
CircuitPython oracle capture and so is not a unilateral edit.
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

machine = platform.machine()
reference_expected = fixture["cpython_stdout_sha256"]
accepted = fixture.get("cpython_stdout_sha256_by_arch", {}).get(machine)
# The reference architecture is gated on the oracle hash. Another
# architecture is gated on its own accepted baseline if one has been
# recorded, and otherwise on the oracle hash -- which it will fail,
# printing the report a human needs in order to accept it.
expected = accepted["sha256"] if accepted else reference_expected

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

# The committed reference text and the committed hash describe the same
# run. If they ever drift, every number below is measured against the wrong
# baseline, so check it before trusting either.
reference_bytes = reference_path.read_bytes().replace(b"\r\n", b"\n")
reference_hash = hashlib.sha256(reference_bytes).hexdigest()
if reference_hash != reference_expected:
    raise SystemExit(
        f"{reference_path.name} does not match cpython_stdout_sha256 in "
        f"{fixture_path.name} ({reference_hash} vs {reference_expected}). One "
        "of the "
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

report = [
    "effect PCM does not match the expected hash for this architecture",
    f"  expected {expected}"
    + (f" (this architecture's accepted baseline, {accepted['accepted']})"
       if accepted else " (the x86_64 oracle hash)"),
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

report.append("")
if machine == REFERENCE_MACHINE:
    report.append(
        "  This is the REFERENCE architecture, where the hash IS the oracle "
        "agreement the accuracy program rests on. A deviation here is a real "
        "regression, however small. Do not record it as a baseline."
    )
elif accepted:
    report.append(
        f"  {machine} has an accepted baseline (recorded "
        f"{accepted['accepted']}) and no longer matches it. That is a "
        "regression on this architecture, not cross-architecture drift -- "
        "bit-identity IS required within one architecture."
    )
else:
    report.append(
        f"  {machine} has no accepted baseline yet, so it was compared "
        "against the x86_64 oracle hash, which it is not expected to match. "
        "Cross-architecture bit-identity is not required (Brad, 2026-09-02)."
    )
    report.append("")
    report.append(
        "  To accept this architecture: read the deviations above and judge "
        "whether they are last-bit floating-point divergence or a defect, "
        "then add an entry to cpython_stdout_sha256_by_arch in "
        f"{fixture_path.name} with the hash, the date, and the evidence you "
        "judged on. Note the limits of what you are reading: the sum "
        "fields are per-block sum(data) over unsigned bytes and bound nothing "
        "about sample magnitude (a +256/-1 pair passes them); the checksum "
        "fields differing means the bytes differ. Do not infer a dBFS figure "
        "from a sum delta. Accepting is a judgement, not a formality."
    )

raise SystemExit("\n".join(report))
