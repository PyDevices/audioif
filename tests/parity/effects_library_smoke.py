"""Every audioeffects class builds and renders, on whichever interpreter runs
this.

    <interpreter> tests/parity/effects_library_smoke.py

tests/test_cpython_effects_library.py measures what the classes *do*, but only
under CPython -- it wants an FFT and unittest. This is the coarse half of that
check, in the subset of Python MicroPython and CircuitPython both have, so the
same catalogue can be walked on all three. It is what catches a class that
reaches for something only CPython has.

Exit status is non-zero if any class fails to build or renders silence, and
every failure is printed rather than only the first.
"""

import sys
from array import array

import audiocore
import audioeffects

SAMPLE_RATE = 48000
audioeffects.configure(SAMPLE_RATE)

#: Arguments a class needs beyond a source. GraphicEQ cannot be built without
#: its gains; ConvolutionReverb can, but its default second of stereo impulse
#: is 1.5 MB and this walks it once per patch -- a quarter second proves the
#: same thing on a board with a small heap.
EXTRA_ARGUMENTS = {
    "GraphicEQ": {"gains_db": (3.0, -2.0, 4.0, -1.0, 2.0)},
    "ConvolutionReverb": {"seconds": 0.25},
}


def source(frames=4096, level=11000):
    values = array("h")
    for frame in range(frames):
        for channel in range(2):
            shape = ((frame * (61 + channel * 17)) % 401) - 200
            values.append(shape * level // 200)
    return audiocore.RawSample(values, sample_rate=SAMPLE_RATE,
                               channel_count=2)


def peak(sample, blocks=8):
    loudest = 0
    for _ in range(blocks):
        data = bytes(audiocore.get_buffer(sample)[1])
        for index in range(0, len(data) - 1, 2):
            value = data[index] | (data[index + 1] << 8)
            if value >= 32768:
                value -= 65536
            if value < 0:
                value = -value
            if value > loudest:
                loudest = value
    return loudest


names = sorted(name for name in dir(audioeffects)
               if not name.startswith("_") and
               isinstance(getattr(audioeffects, name), type))

failures = []
patches = 0
for name in names:
    cls = getattr(audioeffects, name)
    arguments = EXTRA_ARGUMENTS.get(name, {})
    indices = sorted(cls.PATCHES) if cls.MACRO_LABELS else [None]
    for index in indices:
        label = name if index is None else "%s patch %d" % (name, index)
        settings = dict(arguments)
        if index is not None:
            settings["patch"] = index
            patches += 1
        try:
            effect = cls(source(), **settings)
            level = peak(effect.output)
        except Exception as error:  # noqa: BLE001 - the point is to report it
            failures.append("%s: %s: %s" % (label, type(error).__name__, error))
            print("FAIL %s" % label)
            continue
        if level < 32:
            failures.append("%s: renders silence" % label)
            print("FAIL %s (silent)" % label)
        else:
            print("ok   %-28s peak %d" % (label, level))

print("\n%d classes, %d patches, %d failures"
      % (len(names), patches, len(failures)))
for line in failures:
    print("  %s" % line)
sys.exit(1 if failures else 0)
