"""Convert the soundtrack's piece-private instruments, in place.

Companion to port_instrument_specs.py, which does the same for the 53
public ones. These 40 stay where they are: the scripts *are* the patches,
a generated REAPER project embeds their bytes, and each piece owns its
own so a tweak made for a new piece cannot silently change how an old one
renders. What changes is the shape - `create(sample_rate, transport=None)`
returning an Instrument, on top of `audioinstruments._support` - so they
stop needing a VST host to run and can be held to the same parity gate as
the library.

They keep their `# mpvst-macro-labels:` line, because the plug-in parses
its macro names out of the embedded source, and gain a `__main__` guard
that hands `create` to the adapter.

    port_private_instruments.py [name ...]

Delete this alongside port_instrument_specs.py once the cutover lands;
audioif/tests/parity/run_instruments_parity.py is what says whether the
result is right.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from port_instrument import convert

_ROOT = Path(__file__).resolve().parents[1]
VST3 = _ROOT.parent / "micropython-vst3"
PIECES = ("Automata", "Perihelion")

TAIL = '''\
if __name__ == "__main__":
    import mpvst_adapter

    mpvst_adapter.attach(create)
'''

# Not one of these builds its wavetables with ulab, so every make_table
# call has to stay on the pure-Python path or its samples would move on
# any interpreter that ships ulab - and both of ours do.
COMMON = dict(fast=False, labels_comment=True, tail=TAIL)

#: Only what the converter cannot read off the script itself.
SPECS = {
    # No release_voice at all: these release inline, or hold a single
    # voice they release by name.
    "Automata/acid": dict(release="keep"),
    "Automata/supersaw": dict(release="keep"),
    "Automata/texture": dict(release="keep"),
    "Perihelion/lead": dict(release="keep"),
    # ...and this one also inlines the release inside steal_oldest.
    "Perihelion/sub_drone": dict(release="keep", steal="keep"),
    # One note per voice rather than a tuple of them, so the shared
    # release - which iterates voice[0] - does not fit.
    "Perihelion/arp": dict(release="keep"),
    "Perihelion/shimmer": dict(release="keep"),
}

#: Prose fixes for docstrings that named the host module. Applied to the
#: docstring alone - the code's own `vstaudio.transport()` calls are the
#: converter's business, and it rewrites them to the callable.
PROSE = [
    ("vstaudio.transport()", "the host transport"),
]


def fix_prose(text):
    opening = text.index('"""')
    closing = text.index('"""', opening + 3) + 3
    docstring = text[opening:closing]
    for old, new in PROSE:
        docstring = docstring.replace(old, new)
    return text[:opening] + docstring + text[closing:]


def instruments():
    for piece in PIECES:
        directory = VST3 / "soundtrack" / piece / "instruments"
        for path in sorted(directory.glob("*.py")):
            yield "%s/%s" % (piece, path.stem), path


def main():
    wanted = set(sys.argv[1:])
    count = 0
    for key, path in instruments():
        if wanted and key not in wanted and path.stem not in wanted:
            continue
        spec = dict(COMMON, **SPECS.get(key, {}))
        text = fix_prose(convert(path, **spec))
        path.write_text(text)
        count += 1
        print("wrote %-28s (%d lines)" % (key, text.count("\n")))
    print("\n%d instruments" % count)


if __name__ == "__main__":
    main()
