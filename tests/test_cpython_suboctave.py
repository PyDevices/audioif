"""audiomath.SubOctave: that it is actually an octave down, and the surface.

What the node *renders* is pinned byte-for-byte across the three interpreters
by tests/parity/suboctave_probe.py through verify_dsp.py. A digest says the
builds agree; it does not say the thing is a divider. What is here is the
claim itself -- a tone in, its own frequency halved coming out -- plus the
errors and the source behaviours only a Python-defined audiosample produces.
"""

import math
import unittest
from array import array

import audiocore
import audiomath

SAMPLE_RATE = 8000


def tone(frequency, seconds=0.5, level=20000, channel_count=2):
    values = array("h")
    for frame in range(int(SAMPLE_RATE * seconds)):
        value = int(level * math.sin(2 * math.pi * frequency * frame
                                     / SAMPLE_RATE))
        for _ in range(channel_count):
            values.append(value)
    return audiocore.RawSample(values, sample_rate=SAMPLE_RATE,
                               channel_count=channel_count)


def render(node, blocks, channel_count=2):
    values = array("h")
    for _ in range(blocks):
        values.frombytes(bytes(audiocore.get_buffer(node)[1]))
    return values[::channel_count]


def magnitude(samples, frequency):
    """Goertzel, so a tolerance-free comparison of one bin against another
    needs no numpy in the wheel's own test suite."""
    real = 0.0
    imaginary = 0.0
    for index, value in enumerate(samples):
        angle = 2.0 * math.pi * frequency * index / SAMPLE_RATE
        real += value * math.cos(angle)
        imaginary -= value * math.sin(angle)
    return math.hypot(real, imaginary) / len(samples)


class OctaveTest(unittest.TestCase):
    def test_order_one_halves_the_frequency(self):
        node = audiomath.SubOctave(tone(400.0), order=1, mix=1.0,
                                   sample_rate=SAMPLE_RATE)
        rendered = render(node, 8)[256:1856]
        self.assertGreater(magnitude(rendered, 200.0),
                           20 * magnitude(rendered, 400.0))

    def test_order_two_quarters_it(self):
        node = audiomath.SubOctave(tone(400.0), order=2, mix=1.0,
                                   sample_rate=SAMPLE_RATE)
        rendered = render(node, 8)[256:1856]
        self.assertGreater(magnitude(rendered, 100.0),
                           10 * magnitude(rendered, 400.0))
        self.assertGreater(magnitude(rendered, 100.0),
                           10 * magnitude(rendered, 200.0))

    def test_it_tracks_a_different_note(self):
        node = audiomath.SubOctave(tone(300.0), order=1, mix=1.0,
                                   sample_rate=SAMPLE_RATE)
        rendered = render(node, 8)[256:1856]
        self.assertGreater(magnitude(rendered, 150.0),
                           20 * magnitude(rendered, 300.0))

    def test_a_mix_of_zero_is_a_bypass(self):
        values = array("h")
        for frame in range(1024):
            value = int(20000 * math.sin(2 * math.pi * 400.0 * frame
                                         / SAMPLE_RATE))
            values.append(value)
            values.append(value)
        source = audiocore.RawSample(values, sample_rate=SAMPLE_RATE,
                                     channel_count=2)
        node = audiomath.SubOctave(source, order=1, mix=0.0,
                                   sample_rate=SAMPLE_RATE)
        rendered = array("h")
        for _ in range(4):
            rendered.frombytes(bytes(audiocore.get_buffer(node)[1]))
        self.assertEqual(list(rendered), list(values))

    def test_a_half_mix_cancels_on_the_inverted_half(self):
        # A signal blended 50/50 with its own inverse is exactly zero, which
        # is the arithmetic the Q15 blend has to get right rather than
        # approximately right.
        node = audiomath.SubOctave(tone(50.0), order=1, mix=0.5,
                                   sample_rate=SAMPLE_RATE)
        rendered = render(node, 8)[256:1856]
        self.assertIn(0, rendered)
        self.assertNotEqual(min(rendered), max(rendered))

    def test_it_is_zero_latency(self):
        # Every output sample is the input sample at the same index, give or
        # take its sign: nothing is buffered ahead and nothing is
        # interpolated, which is the whole difference from a granular
        # shifter. A -32768 input is the one exception, since negating it
        # clamps to 32767.
        values = array("h")
        for frame in range(1024):
            value = int(20000 * math.sin(2 * math.pi * 400.0 * frame
                                         / SAMPLE_RATE))
            values.append(value)
            values.append(value)
        source = audiocore.RawSample(values, sample_rate=SAMPLE_RATE,
                                     channel_count=2)
        node = audiomath.SubOctave(source, order=1, mix=1.0,
                                   sample_rate=SAMPLE_RATE)
        rendered = render(node, 4)
        original = values[::2]
        self.assertEqual([abs(x) for x in rendered],
                         [abs(x) for x in original])
        # and it really did invert somewhere, or the claim above is vacuous
        self.assertNotEqual(list(rendered), list(original))


class SurfaceTest(unittest.TestCase):
    def test_it_presents_itself_as_a_stereo_sample(self):
        node = audiomath.SubOctave(sample_rate=SAMPLE_RATE)
        self.assertEqual(node.sample_rate, SAMPLE_RATE)
        self.assertEqual(node.channel_count, 2)
        self.assertEqual(node.bits_per_sample, 16)
        self.assertTrue(node.samples_signed)

    def test_mono_is_accepted(self):
        node = audiomath.SubOctave(tone(400.0, channel_count=1), order=1,
                                   mix=1.0, channel_count=1,
                                   sample_rate=SAMPLE_RATE)
        rendered = render(node, 8, channel_count=1)[256:1856]
        self.assertGreater(magnitude(rendered, 200.0),
                           20 * magnitude(rendered, 400.0))

    def test_an_unknown_option_is_refused(self):
        node = audiomath.SubOctave(sample_rate=SAMPLE_RATE)
        with self.assertRaises(TypeError):
            node.set(depth=0.5)

    def test_a_bad_channel_count_is_refused(self):
        with self.assertRaises(ValueError):
            audiomath.SubOctave(channel_count=3)

    def test_silence_in_is_silence_out(self):
        source = audiocore.RawSample(array("h", [0] * 2048),
                                     sample_rate=SAMPLE_RATE,
                                     channel_count=2)
        node = audiomath.SubOctave(source, order=2, mix=1.0,
                                   sample_rate=SAMPLE_RATE)
        self.assertEqual(set(render(node, 4)), {0})

    def test_a_starved_node_yields_silence_not_an_end(self):
        node = audiomath.SubOctave()
        result, buffer = audiocore.get_buffer(node)
        self.assertEqual(result, 1)
        self.assertEqual(len(buffer), 256 * 2 * 2)
        self.assertEqual(set(bytes(buffer)), {0})

    def test_stop_and_play_are_symmetric(self):
        node = audiomath.SubOctave(tone(400.0), order=1, mix=1.0,
                                   sample_rate=SAMPLE_RATE)
        self.assertTrue(node.playing)
        node.stop()
        self.assertFalse(node.playing)
        node.play(tone(400.0))
        self.assertTrue(node.playing)

    def test_set_does_not_restart_the_count_but_clear_does(self):
        first = audiomath.SubOctave(tone(400.0), order=1, mix=1.0,
                                    sample_rate=SAMPLE_RATE)
        render(first, 4)
        before = list(render(first, 1))
        second = audiomath.SubOctave(tone(400.0), order=1, mix=1.0,
                                     sample_rate=SAMPLE_RATE)
        render(second, 4)
        second.set(threshold=0.02)
        self.assertEqual(list(render(second, 1)), before)
        third = audiomath.SubOctave(tone(400.0), order=1, mix=1.0,
                                    sample_rate=SAMPLE_RATE)
        render(third, 4)
        third.clear()
        self.assertNotEqual(list(render(third, 1)), before)


if __name__ == "__main__":
    unittest.main()
