"""Every class in audioeffects builds a chain, and that chain renders.

This is the first time the library has had offline coverage at all. Half of it
is built on Dynamics and Splitter, which used to exist only inside a VST
plug-in's engine, so the only way to run those classes was to load the plug-in
in a host. Now they are ordinary audioif nodes and the whole catalogue renders
here.
"""

import os
import sys
import unittest
from array import array

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (ROOT, os.path.join(ROOT, "lib")):
    if path not in sys.path:
        sys.path.insert(0, path)

import audiocore
import audioeffects
import audioinstruments

SAMPLE_RATE = 48000
audioeffects.configure(SAMPLE_RATE)

#: Every name the package exports as an effect.
CLASSES = tuple(sorted(
    name for name in dir(audioeffects)
    if not name.startswith("_") and isinstance(getattr(audioeffects, name), type)
))


#: The one class that cannot be built from a source alone.
EXTRA_ARGUMENTS = {"GraphicEQ": {"gains_db": (3.0, -2.0, 4.0, -1.0, 2.0)}}


def source(frames=4096, level=11000, rate=SAMPLE_RATE):
    """A stereo signal with content across the spectrum, loud enough to trip
    every threshold the library's defaults use."""
    values = array("h")
    for frame in range(frames):
        for channel in range(2):
            shape = ((frame * (61 + channel * 17)) % 401) - 200
            values.append(shape * level // 200)
    return audiocore.RawSample(values, sample_rate=rate, channel_count=2)


def build(name, **overrides):
    arguments = dict(EXTRA_ARGUMENTS.get(name, ()))
    arguments.update(overrides)
    return getattr(audioeffects, name)(source(), **arguments)


def peak(sample, blocks, skip=0):
    """Loudest sample over `blocks` buffers, after discarding `skip` of them.

    Skipping matters for anything with an envelope follower: the frames before
    its detector has risen pass through untouched, so a peak taken from the
    very start measures the attack transient rather than the effect.
    """
    loudest = 0
    for _ in range(skip):
        audiocore.get_buffer(sample)
    for _ in range(blocks):
        data = memoryview(bytes(audiocore.get_buffer(sample)[1])).cast("h")
        for value in data:
            loudest = max(loudest, -value if value < 0 else value)
    return loudest / 32768.0


class EffectsLibraryTest(unittest.TestCase):
    def test_the_catalogue_is_all_there(self):
        self.assertEqual(len(CLASSES), 39, CLASSES)

    def test_every_effect_builds_and_renders(self):
        for name in CLASSES:
            effect = build(name)
            self.assertIsNotNone(effect.output, name)
            level = peak(effect.output, 8)
            self.assertGreater(level, 0.001, "%s renders silence" % name)

    def test_effects_chain_into_each_other(self):
        # The `.output` of one is the `source` of the next; that is the whole
        # composition rule, and the three here cover all three node kinds
        # (a plain effect, one built on a Splitter, one built on Dynamics).
        drive = audioeffects.Exciter(source(), frequency=2500.0, amount=0.4)
        comp = audioeffects.Compressor(drive.output, threshold_db=-30.0,
                                       ratio=6.0, character="optical")
        verb = audioeffects.Reverb(comp.output, preset="hall", mix=0.35)
        self.assertGreater(peak(verb.output, 12), 0.001)

    def test_an_instrument_feeds_an_effect(self):
        instrument = audioinstruments.create("tr909", SAMPLE_RATE)
        for note, _ in audioinstruments.load("tr909").NOTE_MAP[:4]:
            instrument.note_on(note)
        chain = audioeffects.TapeDelay(instrument.output, time_ms=220.0,
                                       feedback=0.4, mix=0.4)
        self.assertGreater(peak(chain.output, 12), 0.001)

    def test_configure_sets_the_rate_the_nodes_are_built_at(self):
        try:
            audioeffects.configure(22050)
            self.assertEqual(audioeffects.sample_rate(), 22050)
            slow = audioeffects.LowPass(source(rate=22050))
            self.assertEqual(slow.output.sample_rate, 22050)
        finally:
            audioeffects.configure(SAMPLE_RATE)
        self.assertEqual(audioeffects.LowPass(source()).output.sample_rate,
                         SAMPLE_RATE)

    def test_the_compressor_actually_compresses(self):
        # Not just "it renders". The comparison is against a Compressor whose
        # threshold sits above the signal, so both sides are the same node
        # pulling the same blocks and only the gain computer differs.
        idle = audioeffects.Compressor(source(), threshold_db=6.0, ratio=12.0)
        working = audioeffects.Compressor(source(), threshold_db=-36.0,
                                          ratio=12.0, character="fet")
        self.assertLess(peak(working.output, 8, skip=4),
                        peak(idle.output, 8, skip=4) * 0.75)


if __name__ == "__main__":
    unittest.main()
