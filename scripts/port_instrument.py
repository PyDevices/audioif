"""Draft a ported audioinstruments module from an original vstaudio script.

Migration tool for moving micropython-vst3's instrument scripts into this
package; delete it once the last one has moved. Run it via
scripts/port_instrument_specs.py, which carries the per-instrument details it
cannot infer (drum voice maps, and which scripts built their tables in pure
Python). The output is a draft: tests/parity/run_instruments_parity.py is what
says whether it is right.

Mechanical only: hoisted helpers dropped, module tables kept where they are,
everything from the Synthesizer onward folded into create(), global -> nonlocal,
vstaudio.EVENT_* -> EVENT_*, PATCHES quantized to MIDI integers. The parity
harness is the oracle for whether the result is right.
"""
import argparse
import ast
import re
import sys
from pathlib import Path

# Dropped outright; _support provides them. steal_oldest and trigger_voice are
# deliberately absent: they keep their definitions so their call sites stay
# untouched, and get rewritten in place to delegate.
HOISTED = {"make_table", "noise_table", "logmap", "key_of", "env_shape_table",
           "ring_depth_table", "pulse_table", "_apply_patch", "_dispatch"}
# Names that _support provides and a converted module may need to import.
SUPPORT_NAMES = ["EVENT_NOTE_ON", "EVENT_NOTE_OFF", "EVENT_PARAMETER",
                 "EVENT_POLY_PRESSURE", "EVENT_CHANNEL_PRESSURE",
                 "EVENT_PITCH_BEND", "EVENT_CONTROL_CHANGE",
                 "FALL", "env_shape_table", "key_of", "logmap", "make_table",
                 "noise_table", "pulse_table", "ring_depth_table"]


def quantize(value):
    return int(value * 127.0 + 0.5)


RELEASE_PLAIN = """def release_voice(k):
    _support.release_voice(voices, synth, k)
"""

# The three instruments whose filter envelope has a real release stage store
# it as voice[2] and the notes it applies to as voice[3].
RELEASE_FILTERED = """def release_voice(k):
    voice = _support.release_voice(voices, synth, k)
    if voice is not None and voice[2] is not None:
        rel_filter = _support.release_filter(voice[2])
        for note in voice[3]:
            note.filter = rel_filter
"""

RELEASE = {"plain": RELEASE_PLAIN, "filtered": RELEASE_FILTERED}


def convert(path, note_map=None, docstring=None, fast=None, release=None,
            replacements=()):
    src = Path(path).read_text()
    lines = src.split("\n")
    tree = ast.parse(src)

    labels = [s.strip() for s in
              lines[0].split(":", 1)[1].split("|")]

    patches_node = None
    synth_index = None
    for index, node in enumerate(tree.body):
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "PATCHES" in names:
                patches_node = node
            if "synth" in names and synth_index is None:
                synth_index = index
    if synth_index is None:
        raise SystemExit("%s: no synth assignment found" % path)

    patches = ast.literal_eval(ast.unparse(patches_node.value))

    drop = set()          # 1-based line numbers to remove entirely
    body_start = None     # first line that belongs inside create()
    sr_lines = set()      # module assignments that derive from the sample rate

    def drop_node(node, with_comments=True):
        start = node.lineno
        if with_comments:
            while start > 1 and lines[start - 2].lstrip().startswith("#"):
                start -= 1
        for n in range(start, node.end_lineno + 1):
            drop.add(n)

    for index, node in enumerate(tree.body):
        if isinstance(node, ast.FunctionDef) and node.name in HOISTED:
            drop_node(node)
        elif isinstance(node, ast.Try):
            # the ulab import guard
            drop_node(node, with_comments=False)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            drop_node(node, with_comments=False)
        elif isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if any(n in ("SR", "TAU", "FALL", "PATCHES") for n in names):
                drop_node(node, with_comments=("PATCHES" in names))
            elif re.search(r"\bSR\b", ast.unparse(node.value)):
                # Anything derived from the sample rate has to be built per
                # instance, not once at import.
                for n in range(node.lineno, node.end_lineno + 1):
                    sr_lines.add(n)
        elif isinstance(node, ast.Expr):
            text = ast.unparse(node)
            if text.startswith("vstaudio."):
                drop_node(node, with_comments=False)
        if index == synth_index and body_start is None:
            body_start = node.lineno

    module_lines, create_lines, sr_body = [], [], []
    for number, text in enumerate(lines, start=1):
        if number in drop:
            continue
        if number == 1:                       # the macro-labels comment
            continue
        if number in sr_lines:
            sr_body.append(text)
            continue
        target = create_lines if number >= body_start else module_lines
        target.append(text)
    create_lines = sr_body + create_lines

    def strip_blanks(block):
        while block and not block[0].strip():
            block.pop(0)
        while block and not block[-1].strip():
            block.pop()
        return block

    module_lines = strip_blanks(module_lines)
    create_lines = strip_blanks(create_lines)

    # The scripts do not agree on noise_table's default seed, and several call
    # it bare. Pin whatever this file's own definition meant.
    seed_default = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "noise_table":
            args = node.args
            for name, value in zip(args.args[-len(args.defaults):] if args.defaults else [],
                                   args.defaults):
                if name.arg == "seed":
                    seed_default = ast.literal_eval(value)
    if seed_default is not None:
        def pin(match):
            inner = match.group(1)
            if "seed" in inner:
                return match.group(0)
            joined = inner.strip()
            return "noise_table(%sseed=%d)" % (
                (joined + ", ") if joined else "", seed_default)
        module_lines = [re.sub(r"noise_table\(([^)]*)\)", pin, line)
                        for line in module_lines]

    body = "\n".join(create_lines)
    body = re.sub(r"\bglobal\b", "nonlocal", body)
    body = re.sub(r"\bvstaudio\.(EVENT_[A-Z_]+)", r"\1", body)

    # release_voice / steal_oldest / trigger_voice keep their call sites but
    # delegate. Every instrument releases through _support.release_voice; the
    # handful that do more at key-off act on the voice it hands back, so their
    # release still reads the same way as everyone else's.
    body = re.sub(
        r"def release_voice\(k\):\n(?:[ \t]+.*\n)+?(?=\n|def |\S)",
        (RELEASE.get(release, release) if release else RELEASE_PLAIN),
        body)
    body = re.sub(
        r"def steal_oldest\(\):\n(?:[ \t]+.*\n)+?(?=\n|def |\S)",
        "def steal_oldest():\n"
        "    _support.steal_oldest(voices, release_voice)\n",
        body)
    body = re.sub(
        r"def trigger_voice\(k, notes\):\n(?:[ \t]+.*\n)+?(?=\n|def |\S)",
        "def trigger_voice(k, notes):\n"
        "    nonlocal serial\n"
        "    serial = _support.trigger_voice(voices, synth, serial, MAX_VOICES,\n"
        "                                    release_voice, k, notes)\n",
        body)

    body = "\n".join(("    " + line) if line.strip() else ""
                     for line in body.split("\n"))
    module_text = "\n".join(module_lines)

    if fast is False:
        module_text = re.sub(r"make_table\(([^\n]*?)\)$",
                             lambda m: "make_table(%s, fast=False)" % m.group(1),
                             module_text, flags=re.M)

    whole = module_text + "\n" + body
    needed = [n for n in SUPPORT_NAMES if re.search(r"\b%s\b" % n, whole)]

    out = []
    out.append('"""%s"""' % (docstring or Path(path).stem))
    out.append("")
    out.append("MACRO_LABELS = (")
    line = "   "
    for label in labels:
        piece = ' "%s",' % label
        if len(line) + len(piece) > 76:
            out.append(line)
            line = "   "
        line += piece
    out.append(line)
    out.append(")")
    out.append("")
    out.append("# Patch 0 is the sound this instrument's defaults describe, so a fresh")
    out.append("# instance and patch 0 are the same thing - create() applies it. A macro")
    out.append("# a caller does not set resolves here rather than to the middle of its")
    out.append("# range.")
    out.append("PATCHES = {")
    for key in sorted(patches):
        name, values = patches[key]
        ints = [quantize(v) for v in values]
        rendered = "%d: (%r, (" % (key, name)
        pad = " " * (len(rendered) + 4)
        chunk = "    " + rendered
        first = True
        for value in ints:
            piece = ("%d," % value) if first else (" %d," % value)
            if len(chunk) + len(piece) > 76:
                out.append(chunk)
                chunk = pad + ("%d," % value)
            else:
                chunk += piece
            first = False
        out.append(chunk.rstrip(",") + ")),")
    out.append("}")
    out.append("")
    if note_map:
        out.append("NOTE_MAP = (")
        for note, label in note_map:
            out.append('    (%d, "%s"),' % (note, label))
        out.append(")")
        out.append("")
    # Per-file helpers that survived the move may still need these.
    if re.search(r"\barray\.", whole):
        out.append("import array")
    if re.search(r"\bmath\.", whole) or re.search(r"\bTAU\b", whole):
        out.append("import math")
    out.append("import synthio")
    out.append("")
    if needed:
        out.append("from audioinstruments._support import (")
        line = "   "
        for name in needed:
            piece = " %s," % name
            if len(line) + len(piece) > 76:
                out.append(line)
                line = "   "
            line += piece
        out.append(line)
        out.append(")")
    out.append("from audioinstruments._support import Instrument")
    if "_support." in body:
        out.append("from audioinstruments import _support")
    out.append("")
    if re.search(r"\bTAU\b", whole):
        out.append("TAU = 2.0 * math.pi")
        out.append("")
    out.append(module_text)
    out.append("")
    out.append("")
    out.append("def create(sample_rate, transport=None):")
    out.append("    SR = sample_rate")
    out.append(body)
    out.append("")
    out.append("    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,")
    out.append("                            transport=transport%s)"
               % (", note_map=NOTE_MAP" if note_map else ""))
    out.append("    instrument.program_change(0)")
    out.append("    return instrument")
    text = "\n".join(out) + "\n"

    # The escape hatch for what no rule can infer: dead code to drop, a table
    # builder that has to opt out of the cache because its argument follows a
    # macro. Each one has to match, so a stale spec fails loudly.
    for old, new in replacements:
        if old not in text:
            raise SystemExit("%s: replacement did not match: %r"
                             % (Path(path).stem, old))
        text = text.replace(old, new)
    return text


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("script")
    parser.add_argument("--out")
    parser.add_argument("--no-fast", action="store_true")
    args = parser.parse_args()
    text = convert(args.script, fast=False if args.no_fast else None)
    if args.out:
        Path(args.out).write_text(text)
    else:
        sys.stdout.write(text)
