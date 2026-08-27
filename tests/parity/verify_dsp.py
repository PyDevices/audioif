#!/usr/bin/env python3
"""audiodynamics, audioroute, audiomath and audioecho parity: what the
originals rendered, and what the ports render now.

    verify_dsp.py --capture-old     record the goldens from the original nodes
    verify_dsp.py                    hold the ports to them

The old side is micropython-vst3's own `vstaudio_dsp.c`, compiled unmodified
into a throwaway interpreter by build_vstaudio_oracle.sh. Nothing else can
reach it: the usermod that publishes those types is the plugin sidecar, and it
wants a shared memory mapping a VST host created.

One hash per probe covers every interpreter, unlike the instrument goldens.
The arithmetic here is entirely inside shared/audioif_dynamics.c,
shared/audioif_splitter.c and shared/audioif_multiply.c -- the same C the
CPython extension links -- so a disagreement between two interpreters would
itself be the finding.

`audiomath` and `audioecho` have no oracle at all: they are audioif's own
modules, and neither do `Dynamics`' lookahead and true-peak options, which is
why those get a fixture of their own rather than joining dynamics_probe.py --
that one is held against `vstaudio_dsp.c` compiled unmodified, so it may only
use forms the original accepts. The modules with no ancestor in CircuitPython or in the engine. Their goldens are
captured from the port under CPython, and what they prove is cross-interpreter
agreement and no accidental change over time, not fidelity to something older.
The delay is the strictest of the three: its loop is recursive and runs in
`float`, so a one-ulp disagreement between two builds would not stay one ulp.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORKSPACE = ROOT.parent
GOLDEN = HERE / "golden" / "dsp_nodes.json"

#: (probe, module the port provides it as, module the oracle provides it as
#:  or None where there is no oracle, {interpreter: why it is skipped there})
PROBES = (
    ("dynamics_probe.py", "audiodynamics", "vstaudio_oracle", {}),
    ("route_probe.py", "audioroute", "vstaudio_oracle", {}),
    ("route_dry_probe.py", "audioroute", "vstaudio_oracle",
     {"circuitpython": "its coverage variant does not compile audiospeed"}),
    ("multiply_probe.py", "audiomath", None, {}),
    ("feedback_delay_probe.py", "audioecho", None, {}),
    ("dynamics_extras_probe.py", "audiodynamics", None, {}),
    ("convolve_probe.py", "audioconvolve", None, {}),
)

DEFAULT_MICROPYTHON = WORKSPACE / "cmods" / "bin" / "micropython"
DEFAULT_CIRCUITPYTHON = WORKSPACE / "cmods" / "bin" / "circuitpython"
DEFAULT_ORACLE = (WORKSPACE / "cmods" / "micropython" / "ports" / "unix" /
                  "build-vstaudio-oracle" / "micropython")


def run_probe(argv_prefix, probe, module):
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT)
    environment["MICROPYPATH"] = str(ROOT)
    result = subprocess.run(
        argv_prefix + [str(HERE / probe), module],
        cwd=str(ROOT), env=environment, capture_output=True, check=False)
    if result.returncode:
        sys.stderr.buffer.write(result.stdout)
        sys.stderr.buffer.write(result.stderr)
        raise SystemExit("probe failed: %s %s" % (probe, module))
    return hashlib.sha256(
        result.stdout.replace(b"\r\n", b"\n")).hexdigest()


def interpreter_table(args):
    found = {}
    if "cpython" in args.interpreters:
        found["cpython"] = [sys.executable]
    for name, path in (("micropython", args.micropython),
                       ("circuitpython", args.circuitpython)):
        if name not in args.interpreters:
            continue
        if path and Path(path).exists():
            found[name] = [str(path)]
        else:
            print("skipping %s (not built at %s)" % (name, path))
    return found


def capture(args):
    oracle = Path(args.oracle)
    if not oracle.exists() and any(old for _, _, old, _ in PROBES):
        raise SystemExit(
            "the oracle interpreter is not built at %s\n"
            "build it with tests/parity/build_vstaudio_oracle.sh" % oracle)
    fixture = {
        "oracle": "micropython-vst3 usermods/vstaudio/vstaudio_dsp.c, "
                  "compiled unmodified (see build_vstaudio_oracle.sh)",
        "no_oracle": "audiomath and audioecho are audioif's own; their "
                     "probes are captured from the port under CPython",
        "probes": {},
    }
    for probe, module, old_module, _skips in PROBES:
        if old_module is None:
            digest = run_probe([sys.executable], probe, module)
        else:
            digest = run_probe([str(oracle)], probe, old_module)
        fixture["probes"][probe] = digest
        print("captured %-20s %s" % (probe, digest[:16]))
    GOLDEN.parent.mkdir(exist_ok=True)
    GOLDEN.write_text(json.dumps(fixture, indent=2, sort_keys=True) + "\n")
    print("wrote %s" % GOLDEN)


def verify(args):
    if not GOLDEN.exists():
        raise SystemExit("nothing captured yet: run with --capture-old")
    fixture = json.loads(GOLDEN.read_text())
    interpreters = interpreter_table(args)
    if not interpreters:
        raise SystemExit("no interpreters available")
    print("interpreters: %s\n" % ", ".join(sorted(interpreters)))
    failures = []
    checked = 0
    for probe, module, _old, skips in PROBES:
        expected = fixture["probes"].get(probe)
        if expected is None:
            failures.append("%s: nothing captured for it" % probe)
            continue
        for name, prefix in sorted(interpreters.items()):
            if name in skips:
                print("skipping %-20s %-14s (%s)"
                      % (probe, name, skips[name]))
                continue
            actual = run_probe(prefix, probe, module)
            checked += 1
            if actual == expected:
                print("ok       %-20s %-14s %s"
                      % (probe, name, actual[:16]))
            else:
                print("FAIL     %-20s %-14s %s != %s"
                      % (probe, name, actual[:16], expected[:16]))
                failures.append("%s on %s" % (probe, name))
    print("\n%d comparisons, %d failures" % (checked, len(failures)))
    if failures:
        for line in failures:
            print("  %s" % line)
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-old", action="store_true")
    parser.add_argument("--interpreters", default="cpython,micropython")
    parser.add_argument("--micropython", default=str(DEFAULT_MICROPYTHON))
    parser.add_argument("--circuitpython", default=str(DEFAULT_CIRCUITPYTHON))
    parser.add_argument("--oracle", default=str(DEFAULT_ORACLE))
    args = parser.parse_args()
    args.interpreters = [s.strip()
                         for s in args.interpreters.split(",") if s.strip()]
    if args.capture_old:
        capture(args)
    else:
        verify(args)


main()
