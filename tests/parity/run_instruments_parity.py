#!/usr/bin/env python3
"""Instrument parity: capture what the original scripts sounded like, then hold
the ported modules to it.

    run_instruments_parity.py --capture-old --batch all
    run_instruments_parity.py --verify --batch drums

Capture renders each original vstaudio script under every interpreter it can
find and records a hash per interpreter. The originals are read out of
micropython-vst3's git history rather than its working tree: it imports
`audioinstruments` now, so its tree is no longer independent of what these
goldens check. Verify renders the ported module the same way and compares it
against that interpreter's own recorded hash.

Comparison is always within one interpreter. Two interpreters rendering the
same instrument are *expected* to agree and usually do, but nothing guarantees
it - `ulab`'s vectorized sine and libm's are different functions - so
cross-interpreter equality is recorded as an observation, never enforced.

CircuitPython is not in the default set. Its stock `synthio` still has the
out-of-bounds oscillator read described in docs/upstream-diff.md, so its
renders of boundary-hitting material depend on its heap layout and cannot be
held to a byte-exact gate. Pass it explicitly to collect advisory numbers.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORKSPACE = ROOT.parent
GOLDEN = HERE / "golden"

sys.path.insert(0, str(HERE))
import instrument_sequences as sequences  # noqa: E402

BATCHES = {
    "drums": ("instruments_drums", sequences.DRUMS, "lib/instruments", None),
    "melodic": ("instruments_melodic", sequences.MELODIC, "lib/instruments", None),
    "private-automata": (
        "instruments_private_automata", sequences.PRIVATE_AUTOMATA,
        "soundtrack/Automata/instruments", "soundtrack/Automata/instruments"),
    "private-perihelion": (
        "instruments_private_perihelion", sequences.PRIVATE_PERIHELION,
        "soundtrack/Perihelion/instruments", "soundtrack/Perihelion/instruments"),
}

DEFAULT_MICROPYTHON = WORKSPACE / "cmods" / "bin" / "micropython"
DEFAULT_CIRCUITPYTHON = WORKSPACE / "cmods" / "bin" / "circuitpython"
DEFAULT_OLD_ROOT = WORKSPACE / "micropython-vst3"

#: The last micropython-vst3 revision whose instruments were still whole
#: scripts of their own. It imports `audioinstruments` now, so its working
#: tree is no longer independent of what these goldens are meant to check -
#: the originals come out of its history instead, where they cannot drift.
DEFAULT_OLD_REV = "ac87f13"


def interpreter_table(args):
    """Map interpreter name -> argv prefix, keeping only the ones present."""
    found = {}
    if "cpython" in args.interpreters:
        found["cpython"] = [sys.executable]
    for name, path in (("micropython", args.micropython),
                       ("circuitpython", args.circuitpython)):
        if name not in args.interpreters:
            continue
        if path and Path(path).exists():
            found[name] = [str(path)]
        elif args.require_interpreters:
            raise SystemExit("%s not found at %s" % (name, path))
        else:
            print("skipping %s (not built at %s)" % (name, path))
    return found


def run_probe(argv_prefix, probe, probe_args):
    """Run a probe and return its normalized stdout, or raise with its output."""
    environment = os.environ.copy()
    search = "%s%s%s" % (ROOT, os.pathsep, ROOT / "lib")
    environment["PYTHONPATH"] = search
    # MicroPython and CircuitPython read their search path from MICROPYPATH,
    # which is always colon-separated regardless of platform.
    environment["MICROPYPATH"] = "%s:%s" % (ROOT, ROOT / "lib")
    result = subprocess.run(
        argv_prefix + [str(HERE / probe)] + probe_args,
        cwd=str(ROOT), env=environment, capture_output=True, check=False)
    if result.returncode:
        sys.stderr.buffer.write(result.stdout)
        sys.stderr.buffer.write(result.stderr)
        raise RuntimeError("probe failed: %s %s" % (probe, " ".join(probe_args)))
    return result.stdout.replace(b"\r\n", b"\n")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load_golden(key):
    path = GOLDEN / (key + ".json")
    if path.exists():
        return json.loads(path.read_text())
    return {"oracle": "micropython-vst3 instrument scripts via vstaudio",
            "modules": {}}


def save_golden(key, fixture):
    path = GOLDEN / (key + ".json")
    path.write_text(json.dumps(fixture, indent=2, sort_keys=True) + "\n")
    return path


def checkout(root, rev, relative, destination):
    """Write the original scripts at `rev` into `destination`."""
    listing = subprocess.run(
        ["git", "-C", str(root), "ls-tree", "--name-only", rev,
         relative.rstrip("/") + "/"],
        capture_output=True, text=True, check=False)
    paths = [line for line in listing.stdout.split("\n")
             if line.endswith(".py")]
    if listing.returncode or not paths:
        raise SystemExit(
            "no instrument scripts in %s at %s under %s\n"
            "Pass --old-rev with a revision that still has them."
            % (root, rev, relative))
    for path in paths:
        content = subprocess.run(
            ["git", "-C", str(root), "show", "%s:%s" % (rev, path)],
            capture_output=True, check=True).stdout
        (destination / path.rsplit("/", 1)[-1]).write_bytes(content)
    return destination


def capture(args, interpreters):
    for batch in args.batch:
        key, names, old_rel, _ = BATCHES[batch]
        old_dir = Path(tempfile.mkdtemp(prefix="parity-old-"))
        checkout(args.old_root, args.old_rev, old_rel, old_dir)
        fixture = load_golden(key)
        for name in select(names, args.modules):
            record = fixture["modules"].setdefault(name, {})
            hashes = record.setdefault("old", {})
            for interpreter, prefix in interpreters.items():
                output = run_probe(prefix, "instruments_probe_old.py",
                                   [name, str(old_dir)])
                hashes[interpreter] = digest(output)
                print("captured %-14s %-14s %s"
                      % (name, interpreter, hashes[interpreter][:16]))
            record["cross_interpreter_equal"] = len(set(hashes.values())) == 1
        shutil.rmtree(old_dir, ignore_errors=True)
        path = save_golden(key, fixture)
        print("wrote %s" % path)


def verify(args, interpreters):
    failures = []
    checked = 0
    for batch in args.batch:
        key, names, _, new_rel = BATCHES[batch]
        fixture = load_golden(key)
        module_dir = str(Path(args.old_root) / new_rel) if new_rel else None
        for name in select(names, args.modules):
            record = fixture["modules"].get(name)
            if record is None:
                failures.append("%s: nothing captured for it" % name)
                continue
            probe_args = [name] + ([module_dir] if module_dir else [])
            for interpreter, prefix in interpreters.items():
                expected = record["old"].get(interpreter)
                if expected is None:
                    print("skipping %-14s %-14s (never captured)"
                          % (name, interpreter))
                    continue
                actual = digest(run_probe(prefix, "instruments_probe_new.py",
                                          probe_args))
                checked += 1
                if actual == expected:
                    print("ok       %-14s %-14s %s"
                          % (name, interpreter, actual[:16]))
                else:
                    print("FAIL     %-14s %-14s %s != %s"
                          % (name, interpreter, actual[:16], expected[:16]))
                    failures.append("%s on %s" % (name, interpreter))
    print("\n%d comparisons, %d failures" % (checked, len(failures)))
    if failures:
        for line in failures:
            print("  %s" % line)
        raise SystemExit(1)
    if not checked:
        raise SystemExit("nothing was compared")


def select(names, wanted):
    if not wanted:
        return names
    missing = [n for n in wanted if n not in names]
    if missing:
        raise SystemExit("not in the selected batch: %s" % ", ".join(missing))
    return [n for n in names if n in wanted]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", action="append", default=None,
                        choices=sorted(BATCHES) + ["all"])
    parser.add_argument("--modules", default=None,
                        help="comma-separated subset of the batch")
    parser.add_argument("--interpreters", default="cpython,micropython",
                        help="comma-separated; add circuitpython for advisory "
                             "numbers (see the module docstring)")
    parser.add_argument("--micropython", default=str(DEFAULT_MICROPYTHON))
    parser.add_argument("--circuitpython", default=str(DEFAULT_CIRCUITPYTHON))
    parser.add_argument("--old-root", default=str(DEFAULT_OLD_ROOT))
    parser.add_argument("--old-rev", default=DEFAULT_OLD_REV,
                        help="the revision --capture-old reads the original "
                             "scripts from (default %s)" % DEFAULT_OLD_REV)
    parser.add_argument("--require-interpreters", action="store_true",
                        help="fail if a requested interpreter is missing")
    parser.add_argument("--capture-old", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()

    if args.capture_old == args.verify:
        raise SystemExit("choose exactly one of --capture-old / --verify")
    args.batch = args.batch or ["all"]
    if "all" in args.batch:
        args.batch = sorted(BATCHES)
    args.interpreters = [s.strip() for s in args.interpreters.split(",") if s.strip()]
    args.modules = ([s.strip() for s in args.modules.split(",") if s.strip()]
                    if args.modules else None)

    interpreters = interpreter_table(args)
    if not interpreters:
        raise SystemExit("no interpreters available")
    print("interpreters: %s\n" % ", ".join(sorted(interpreters)))

    GOLDEN.mkdir(exist_ok=True)
    if args.capture_old:
        capture(args, interpreters)
    else:
        verify(args, interpreters)


main()
