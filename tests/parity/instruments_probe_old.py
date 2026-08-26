"""Render an original vstaudio instrument script and print reduced PCM stats.

    instruments_probe_old.py <name> <script_dir>

The script is imported with a `vstaudio` stand-in in place, its patch 0 is
applied as explicit parameter events on the 7-bit grid, and then the shared
sequence is replayed. Runs unmodified on CPython, MicroPython and
CircuitPython so each interpreter can be compared against its own future self.
"""

import sys

import audiocore

_filename = __file__.replace("\\", "/")
_here = _filename.rsplit("/", 1)[0] if "/" in _filename else "."
if _here not in sys.path:
    sys.path.insert(0, _here)

import instrument_sequences as sequences
import _vstaudio_shim as shim

SAMPLE_RATE = 48000


def checksum(data):
    value = 2166136261
    for byte in data:
        value = ((value ^ byte) * 16777619) & 0xffffffff
    return value


def main():
    name = sys.argv[1]
    script_dir = sys.argv[2]
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)

    sys.modules["vstaudio"] = shim
    shim._reset(SAMPLE_RATE)
    __import__(name)
    module = sys.modules[name]

    handler = shim._handler
    output = shim._output
    if handler is None or output is None:
        raise SystemExit("%s registered no handler/output" % name)

    macro_count = len(module.PATCHES[0][1])

    def select_patch(index):
        """Apply a patch on the 7-bit grid, as parameter events.

        The ported module stores its patches as MIDI integers, so this is the
        comparison that answers the question the gate is asking: did moving
        the script change what it sounds like? Rounding the patch tables to
        7 bits is a separate decision, taken deliberately, and it moves a
        macro by at most half a step - not something to rediscover here as a
        hash mismatch. This is also why the old side never sends a real
        program change: the script would answer one from its own unrounded
        float tables.
        """
        for macro, value in enumerate(module.PATCHES[index][1]):
            handler(shim.EVENT_PARAMETER, 0, -1, macro,
                    int(value * 127.0 + 0.5) / 127.0, 0.0, 0)

    select_patch(0)

    pulls = 0
    for op in sequences.build(name, macro_count, module.PATCHES):
        shim._transport = sequences.transport_at(pulls)
        kind = op[0]
        if kind == "on":
            detune = op[3] if len(op) > 3 else 0.0
            handler(shim.EVENT_NOTE_ON, 0, -1, op[1], op[2] / 127.0, detune, 0)
        elif kind == "off":
            handler(shim.EVENT_NOTE_OFF, 0, -1, op[1], 0.0, 0.0, 0)
        elif kind == "macro":
            handler(shim.EVENT_PARAMETER, 0, -1, op[1], op[2] / 127.0, 0.0, 0)
        elif kind == "pc":
            select_patch(op[1])
        elif kind == "cpress":
            handler(shim.EVENT_CHANNEL_PRESSURE, 0, -1, 0, op[1] / 127.0, 0.0, 0)
        elif kind == "ppress":
            handler(shim.EVENT_POLY_PRESSURE, 0, -1, op[1], op[2] / 127.0, 0.0, 0)
        elif kind == "pull":
            for _ in range(op[1]):
                shim._transport = sequences.transport_at(pulls)
                data = bytes(audiocore.get_buffer(output)[1])
                print("pcm", pulls, len(data), sum(data), checksum(data))
                pulls += 1
        else:
            raise SystemExit("unknown op %r" % (op,))
    print("done", name, macro_count, pulls)


main()
