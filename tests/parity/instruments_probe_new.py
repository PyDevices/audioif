"""Render a ported instrument module and print reduced PCM stats.

    instruments_probe_new.py <name> [<module_dir>]

Mirror image of `instruments_probe_old.py`: same sequence, same output format,
driven through the `Instrument` MIDI surface with integer arguments. With no
module directory the instrument comes from the `audioinstruments` package;
with one, the module is imported from that directory by bare name (how the
soundtrack's piece-private instruments are laid out).
"""

import sys

import audiocore

_filename = __file__.replace("\\", "/")
_here = _filename.rsplit("/", 1)[0] if "/" in _filename else "."
if _here not in sys.path:
    sys.path.insert(0, _here)

import instrument_sequences as sequences

SAMPLE_RATE = 48000


def checksum(data):
    value = 2166136261
    for byte in data:
        value = ((value ^ byte) * 16777619) & 0xffffffff
    return value


def main():
    name = sys.argv[1]
    module_dir = sys.argv[2] if len(sys.argv) > 2 else None
    if module_dir:
        if module_dir not in sys.path:
            sys.path.insert(0, module_dir)
        __import__(name)
        module = sys.modules[name]
    else:
        import audioinstruments
        module = audioinstruments.load(name)

    # Matches the stand-in's idle reading, so patch 0 is applied under the same
    # transport the original script saw at import time.
    reading = [(False, 0.0, 120.0, 4, 4)]

    instrument = module.create(SAMPLE_RATE, transport=lambda: reading[0])
    macro_count = len(module.MACRO_LABELS)
    output = instrument.output

    note_map = getattr(module, "NOTE_MAP", None)
    if note_map is not None:
        mapped = tuple(entry[0] for entry in note_map)
        for note in mapped:
            if note not in sequences.DRUM_NOTES:
                raise SystemExit(
                    "%s NOTE_MAP note %d is outside the parity sequence"
                    % (name, note))

    pulls = 0
    for op in sequences.build(name, macro_count):
        reading[0] = sequences.transport_at(pulls)
        kind = op[0]
        if kind == "on":
            detune = op[3] if len(op) > 3 else 0.0
            instrument.note_on(op[1], op[2], detune=detune)
        elif kind == "off":
            instrument.note_off(op[1])
        elif kind == "macro":
            instrument.set_macro(op[1], op[2])
        elif kind == "pc":
            instrument.program_change(op[1])
        elif kind == "cpress":
            instrument.channel_pressure(op[1])
        elif kind == "ppress":
            instrument.poly_pressure(op[1], op[2])
        elif kind == "pull":
            for _ in range(op[1]):
                reading[0] = sequences.transport_at(pulls)
                data = bytes(audiocore.get_buffer(output)[1])
                print("pcm", pulls, len(data), sum(data), checksum(data))
                pulls += 1
        else:
            raise SystemExit("unknown op %r" % (op,))
    print("done", name, macro_count, pulls)


main()
