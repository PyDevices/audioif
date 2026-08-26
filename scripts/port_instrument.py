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
            replacements=(), into_create=(), labels_comment=False, tail=None,
            steal=None):
    """Draft a ported module. ``labels_comment`` keeps the original's
    ``# mpvst-macro-labels:`` line, and ``tail`` is appended verbatim -
    both for the soundtrack's piece-private instruments, which stay whole
    scripts loaded by the plug-in rather than becoming package modules."""
    src = Path(path).read_text()
    lines = src.split("\n")
    tree = ast.parse(src)

    labels = [s.strip() for s in
              lines[0].split(":", 1)[1].split("|")]

    # Whatever the script imported, minus the host module it is being freed
    # from. The soundtrack's instruments reach for audiofreeverb, audiodelays
    # and audiofilters; the library's only ever wanted array/math/synthio.
    imports = sorted({alias.name for node in tree.body
                      if isinstance(node, ast.Import)
                      for alias in node.names} - {"vstaudio"})

    # `vstaudio.output(x)` names the chain tail. When it is not the
    # synthesizer itself, the Instrument has to be told.
    chain_tail = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "output"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "vstaudio"
                and node.args and isinstance(node.args[0], ast.Name)):
            chain_tail = node.args[0].id
    if chain_tail == "synth":
        chain_tail = None

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

    def span(node, with_comments=True):
        start = node.lineno
        if with_comments:
            while start > 1 and lines[start - 2].lstrip().startswith("#"):
                start -= 1
        return range(start, node.end_lineno + 1)

    def drop_node(node, with_comments=True):
        drop.update(span(node, with_comments))

    # The block of comments under the macro-labels line describes the
    # instrument. It becomes the module docstring, so drop it here rather
    # than let it survive as a floating comment below the imports.
    header = []
    for number in range(2, len(lines) + 1):
        text = lines[number - 1].strip()
        if text and not text.startswith("#"):
            break
        drop.add(number)
        header.append(text[1:].lstrip() if text.startswith("#") else "")

    # Anything a handler declares `global` is per-instance state, whatever
    # scope it was assigned in. `global` becomes `nonlocal` below, so its
    # assignment has to be inside create() for that binding to exist.
    mutated = {name for node in ast.walk(tree)
               if isinstance(node, ast.Global) for name in node.names}

    for index, node in enumerate(tree.body):
        if isinstance(node, ast.FunctionDef) and node.name in HOISTED:
            drop_node(node)
        elif isinstance(node, ast.FunctionDef) and node.name in into_create:
            # A builder that reads the sample rate when it is called, not when
            # the module is imported, has to be built per instance too.
            sr_lines.update(span(node))
        elif (isinstance(node, ast.FunctionDef)
              and "vstaudio.transport(" in ast.unparse(node)):
            # The host's playback position is a per-instance callable now,
            # so anything reading it has to live where that callable is.
            sr_lines.update(span(node))
        elif isinstance(node, ast.Try):
            # the ulab import guard
            drop_node(node, with_comments=False)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            drop_node(node, with_comments=False)
        elif isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if any(n in ("SR", "TAU", "FALL", "PATCHES") for n in names):
                drop_node(node, with_comments=("PATCHES" in names))
            elif (re.search(r"\bSR\b", ast.unparse(node.value))
                  or (index < synth_index and any(n in mutated for n in names))):
                # Anything derived from the sample rate, or that a handler
                # reassigns from above the synthesizer, has to be built per
                # instance rather than once at import. (Below the
                # synthesizer everything already moves into create().)
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
    # The host's playback position arrives as a callable now, not a module
    # function, so a tempo-syncing instrument reads whatever its caller
    # gave it. Same reading, same shape, one indirection.
    uses_transport = "vstaudio.transport(" in body
    body = body.replace("vstaudio.transport(", "transport(")

    # release_voice / steal_oldest / trigger_voice keep their call sites but
    # delegate. Every instrument releases through _support.release_voice; the
    # handful that do more at key-off act on the voice it hands back, so their
    # release still reads the same way as everyone else's.
    # "keep" leaves a definition alone: an instrument that holds one note
    # per voice rather than a tuple of them, or one whose voice stealing
    # inlines the release because it has no release_voice at all.
    if release != "keep":
        replacement = RELEASE.get(release, release) if release else RELEASE_PLAIN
        body, count = re.subn(
            r"def release_voice\(k\):\n(?:[ \t]+.*\n)+?(?=\n|def |\S)",
            lambda _: replacement, body)
        if count != 1:
            raise SystemExit("%s: rewrote %d release_voice definitions, wanted 1"
                             % (Path(path).stem, count))
    if steal != "keep":
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
    if labels_comment:
        # The plug-in reads its macro names straight out of the embedded
        # script source, so a script it loads directly has to keep this
        # line. Generated from the same labels as MACRO_LABELS below.
        out.append("# mpvst-macro-labels: " + " | ".join(labels))
    description = docstring or "\n".join(header).strip() or Path(path).stem
    out.append('"""%s"""' % description if "\n" not in description
               else '"""%s\n"""' % description)
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
        # A one-macro instrument keeps its trailing comma, or ("Init", (56))
        # is a bare int rather than a tuple of one.
        out.append(chunk if len(ints) == 1 else chunk.rstrip(","))
        out[-1] += ")),"
    out.append("}")
    out.append("")
    if note_map:
        out.append("NOTE_MAP = (")
        for note, label in note_map:
            out.append('    (%d, "%s"),' % (note, label))
        out.append(")")
        out.append("")
    # Whatever the original imported and the converted module still uses.
    # `math` also survives a script that only wanted it for TAU, which is
    # provided here instead.
    for name in imports:
        if name == "synthio":
            continue
        if name == "math" and re.search(r"\bTAU\b", whole):
            out.append("import math")
        elif re.search(r"\b%s\." % name, whole):
            out.append("import %s" % name)
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
    if uses_transport:
        out.append("from audioinstruments._support import static_transport")
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
    if uses_transport:
        out.append("    if transport is None:")
        out.append("        transport = static_transport")
    out.append(body)
    out.append("")
    extras = ""
    if chain_tail:
        extras += ", output=%s" % chain_tail
    if note_map:
        extras += ", note_map=NOTE_MAP"
    out.append("    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,")
    out.append("                            transport=transport%s)" % extras)
    out.append("    instrument.program_change(0)")
    out.append("    return instrument")
    if tail:
        out.append("")
        out.append("")
        out.append(tail.rstrip("\n"))
    text = "\n".join(out) + "\n"

    # The escape hatch for what no rule can infer: dead code to drop, a table
    # builder that has to opt out of the cache because its argument follows a
    # macro. Matched against the finished module - indentation included, so a
    # body-level replacement is written as it will appear inside create().
    # Each one has to match, so a stale spec fails loudly.
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
