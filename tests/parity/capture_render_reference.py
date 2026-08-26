#!/usr/bin/env python3
"""What micropython-vst3's six pieces sound like today, before the cutover.

    capture_render_reference.py --capture
    capture_render_reference.py --verify [--tolerance-db 1.0]

Renders every piece through vst3's own `tools/render_preview.py` and records
the master WAV's hash, the analysis report, and the levels parsed out of it.
This is the acceptance baseline for the phase-5 cutover, when those scripts
start importing `audioinstruments` and `audioeffects` instead of running their
own copies - so it has to be captured while the old code is still what runs.

Verification is deliberately two-sided. An identical WAV hash says nothing
moved at all. When one does move, the levels are compared within a tolerance
and the report is diffed, because one shift is expected and bounded: patches
become 7-bit integers in the port, so any macro whose stored value was not
already on that grid moves by up to half a step. That is a decision taken in
the plan, not a regression to find here.

Needs numpy, which vst3's renderer imports; pass `--python` if the default
interpreter does not have it.
"""

import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORKSPACE = ROOT.parent
GOLDEN = HERE / "golden" / "vst3_render_reference.json"

DEFAULT_VST3 = WORKSPACE / "micropython-vst3"

#: The two things in the report that are not reproducible: how long the render
#: took, and where this script happened to put the WAV.
ELAPSED = re.compile(r"\((\d+\.\d+)s\)")
RENDER_SECONDS = re.compile(r"^(.*: [\d.]+ s song, )[\d.]+( s render.*)$",
                            re.MULTILINE)
WROTE = re.compile(r"^wrote .*$", re.MULTILINE)

# Read off the *normalized* report, so the elapsed time is already a placeholder.
TRACK_LINE = re.compile(
    r"^  (\S.*?)\s+raw_peak=([\d.]+) mixed_peak=([\d.]+) \(-\.-s\)",
    re.MULTILINE)
SECTION_LINE = re.compile(
    r"^  (\S.*?)\s+rms=\s*(-?[\d.]+) dBFS\s+hp150=\s*(-?[\d.]+) dBFS"
    r"\s+peak=\s*(-?[\d.]+) dBFS", re.MULTILINE)
MASTER_LINE = re.compile(r"^master peak [\d.]+ \((-?[\d.]+) dBFS\)",
                         re.MULTILINE)
SIMULTANEOUS = re.compile(r"^max simultaneous tracks: (\d+)", re.MULTILINE)


def pieces(vst3):
    """Every piece in the soundtrack - a directory with a composition.py."""
    soundtrack = Path(vst3) / "soundtrack"
    return sorted(entry.name for entry in soundtrack.iterdir()
                  if (entry / "composition.py").is_file())


def normalize(report):
    report = ELAPSED.sub("(-.-s)", report)
    report = RENDER_SECONDS.sub(r"\g<1>-.-\g<2>", report)
    return WROTE.sub("wrote <scratch>", report)


def levels(report):
    """The numbers worth comparing with a tolerance, by name."""
    found = {}
    for name, raw_peak, mixed_peak in TRACK_LINE.findall(report):
        found["track %s raw_peak" % name] = float(raw_peak)
        found["track %s mixed_peak" % name] = float(mixed_peak)
    for name, rms, hp150, peak in SECTION_LINE.findall(report):
        found["section %s rms" % name] = float(rms)
        found["section %s hp150" % name] = float(hp150)
        found["section %s peak" % name] = float(peak)
    master = MASTER_LINE.search(report)
    if master:
        found["master peak"] = float(master.group(1))
    return found


def render(args, piece, destination):
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT)
    result = subprocess.run(
        [args.python, str(Path(args.vst3) / "tools" / "render_preview.py"),
         "--piece", piece, str(destination)],
        cwd=str(Path(args.vst3)), env=environment, capture_output=True,
        check=False)
    report = result.stdout.decode("utf-8", "replace")
    if result.returncode:
        sys.stderr.write(report)
        sys.stderr.write(result.stderr.decode("utf-8", "replace"))
        raise SystemExit("render failed: %s" % piece)
    data = destination.read_bytes()
    return normalize(report), hashlib.sha256(data).hexdigest(), len(data)


def each_piece(args):
    with tempfile.TemporaryDirectory() as scratch:
        for piece in args.pieces:
            destination = Path(scratch) / ("%s.wav" % piece)
            yield (piece,) + render(args, piece, destination)


def capture(args):
    fixture = {
        "oracle": "micropython-vst3 tools/render_preview.py, before the "
                  "audioinstruments/audioeffects cutover",
        "pieces": {},
    }
    for piece, report, digest, size in each_piece(args):
        fixture["pieces"][piece] = {
            "wav_sha256": digest,
            "wav_bytes": size,
            "levels": levels(report),
            "report": report,
        }
        print("captured %-18s %s  %d bytes" % (piece, digest[:16], size))
    GOLDEN.parent.mkdir(exist_ok=True)
    GOLDEN.write_text(json.dumps(fixture, indent=2, sort_keys=True) + "\n")
    print("wrote %s" % GOLDEN)


def verify(args):
    if not GOLDEN.exists():
        raise SystemExit("nothing captured yet: run with --capture")
    fixture = json.loads(GOLDEN.read_text())
    failures = []
    for piece, report, digest, size in each_piece(args):
        record = fixture["pieces"].get(piece)
        if record is None:
            failures.append("%s: nothing captured for it" % piece)
            continue
        if digest == record["wav_sha256"]:
            print("ok       %-18s identical (%s)" % (piece, digest[:16]))
            continue
        print("moved    %-18s %s != %s"
              % (piece, digest[:16], record["wav_sha256"][:16]))
        now = levels(report)
        before = record["levels"]
        worst = 0.0
        for name, value in sorted(before.items()):
            if name not in now:
                failures.append("%s: %s is gone from the report"
                                % (piece, name))
                continue
            drift = abs(now[name] - value)
            if name.endswith("_peak"):
                # These two are linear, not dB - scale the comparison so one
                # tolerance means the same thing everywhere.
                drift = abs(dbfs(now[name]) - dbfs(value))
            worst = max(worst, drift)
            if drift > args.tolerance_db:
                failures.append("%s: %s moved %.2f dB (%.3f -> %.3f)"
                                % (piece, name, drift, value, now[name]))
        print("         worst level shift %.2f dB (tolerance %.2f)"
              % (worst, args.tolerance_db))
        for line in difflib.unified_diff(
                record["report"].splitlines(), report.splitlines(),
                "captured", "now", lineterm="", n=1):
            print("         %s" % line)
    if failures:
        print()
        for line in failures:
            print("  %s" % line)
        raise SystemExit(1)


def dbfs(linear):
    from math import log10
    return 20.0 * log10(max(abs(linear), 1e-9))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--vst3", default=str(DEFAULT_VST3))
    parser.add_argument("--python", default=sys.executable,
                        help="an interpreter with numpy (the renderer needs it)")
    parser.add_argument("--pieces", default=None,
                        help="comma-separated subset")
    parser.add_argument("--tolerance-db", type=float, default=1.0,
                        help="how far a level may move once the WAV has")
    args = parser.parse_args()
    if args.capture == args.verify:
        raise SystemExit("choose exactly one of --capture / --verify")
    args.pieces = ([name.strip() for name in args.pieces.split(",")
                    if name.strip()] if args.pieces else pieces(args.vst3))
    print("pieces: %s\n" % ", ".join(args.pieces))
    if args.capture:
        capture(args)
    else:
        verify(args)


main()
