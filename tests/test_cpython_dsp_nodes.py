"""audiodynamics and audioroute: the surface the parity gate cannot check.

What these nodes *render* is pinned byte-for-byte against the original
`vstaudio` implementation by tests/parity/verify_dsp.py. What is left for here
is everything that comparison cannot reach: the argument forms the original
never accepted, the errors, and the source behaviours only a Python-defined
audiosample can produce.
"""

import os
import sys
import unittest
from array import array

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import audiocore
import audiodynamics
import audioroute

SAMPLE_RATE = 48000


def source(frames=800, level=9000):
    values = array("h")
    for frame in range(frames):
        for channel in range(2):
            values.append(((frame * (61 + channel * 13)) % 2001 - 1000)
                          * level // 1000)
    return audiocore.RawSample(values, sample_rate=SAMPLE_RATE,
                               channel_count=2)


class Dry:
    """An audiosample that yields one buffer and is then finished."""

    def __init__(self, blocks=1):
        self.sample_rate = SAMPLE_RATE
        self.bits_per_sample = 16
        self.channel_count = 2
        self.samples_signed = True
        self.single_buffer = False
        self.max_buffer_length = 1024
        self._left = blocks

    def _reset_buffer(self, single_channel_output=False, audio_channel=0):
        pass

    def _get_buffer(self, single_channel_output=False, audio_channel=0):
        if self._left <= 0:
            return audiocore.GET_BUFFER_DONE, memoryview(b"")
        self._left -= 1
        block = array("h", (((index * 37) % 2001) - 1000 for index in range(512)))
        return audiocore.GET_BUFFER_MORE_DATA, memoryview(block)


class DynamicsTest(unittest.TestCase):
    def test_it_presents_itself_as_a_stereo_sample(self):
        node = audiodynamics.Dynamics(audiodynamics.DYN_LIMIT,
                                      sample_rate=SAMPLE_RATE)
        self.assertEqual(node.sample_rate, SAMPLE_RATE)
        self.assertEqual(node.channel_count, 2)
        self.assertEqual(node.bits_per_sample, 16)
        self.assertTrue(node.samples_signed)
        self.assertFalse(node.single_buffer)

    def test_an_unknown_option_is_refused(self):
        # A silently ignored typo would be a patch that quietly does nothing.
        with self.assertRaises(TypeError):
            audiodynamics.Dynamics(audiodynamics.DYN_COMPRESS, thresh_db=-12)
        node = audiodynamics.Dynamics(audiodynamics.DYN_COMPRESS)
        with self.assertRaises(TypeError):
            node.set(squash=1.0)

    def test_keyword_order_does_not_change_the_coefficients(self):
        # attack_ms is converted against the sample rate, so a sample_rate
        # written after it still has to win.
        first = audiodynamics.Dynamics(audiodynamics.DYN_COMPRESS,
                                       sample_rate=8000, attack_ms=25.0)
        second = audiodynamics.Dynamics(audiodynamics.DYN_COMPRESS,
                                        attack_ms=25.0, sample_rate=8000)
        first.play(source())
        second.play(source())
        self.assertEqual(bytes(audiocore.get_buffer(first)[1]),
                         bytes(audiocore.get_buffer(second)[1]))

    def test_a_source_that_finishes_leaves_silence_behind(self):
        node = audiodynamics.Dynamics(audiodynamics.DYN_COMPRESS,
                                      sample_rate=SAMPLE_RATE)
        node.play(Dry(blocks=1))
        result, data = audiocore.get_buffer(node)
        self.assertEqual(result, audiocore.GET_BUFFER_MORE_DATA)
        self.assertEqual(len(bytes(data)), 512 * 2)   # the one block it got
        # And then it keeps answering, because the graph around it is running.
        for _ in range(2):
            result, data = audiocore.get_buffer(node)
            self.assertEqual(result, audiocore.GET_BUFFER_MORE_DATA)
            self.assertEqual(bytes(data), bytes(audiodynamics.FRAMES * 4))

    def test_gain_reduction_follows_the_signal(self):
        node = audiodynamics.Dynamics(audiodynamics.DYN_COMPRESS,
                                      sample_rate=SAMPLE_RATE,
                                      threshold_db=-40.0, ratio=8.0)
        self.assertEqual(node.gain_reduction_db(), 0.0)
        node.play(source())
        audiocore.get_buffer(node)
        self.assertLess(node.gain_reduction_db(), -1.0)

    def test_stop_and_play_are_symmetric(self):
        node = audiodynamics.Dynamics(audiodynamics.DYN_GATE)
        self.assertFalse(node.playing)
        node.play(source())
        self.assertTrue(node.playing)
        node.stop()
        self.assertFalse(node.playing)

    def test_a_dynamics_can_feed_another(self):
        first = audiodynamics.Dynamics(audiodynamics.DYN_COMPRESS,
                                       sample_rate=SAMPLE_RATE,
                                       threshold_db=-30.0)
        first.play(source())
        second = audiodynamics.Dynamics(audiodynamics.DYN_LIMIT,
                                        sample_rate=SAMPLE_RATE,
                                        threshold_db=-12.0)
        second.play(first)
        data = bytes(audiocore.get_buffer(second)[1])
        self.assertEqual(len(data), audiodynamics.FRAMES * 4)
        self.assertNotEqual(data, bytes(len(data)))


class SplitterTest(unittest.TestCase):
    def test_taps_may_be_named(self):
        # The original took the count positionally only; a keyword reads far
        # better at the call sites in the effects library.
        splitter = audioroute.Splitter(source(), taps=3)
        self.assertIsNot(splitter.tap(0), splitter.tap(2))
        self.assertIs(splitter.tap(1), splitter.tap(1))

    def test_the_tap_count_is_bounded(self):
        for count in (0, -1, 5):
            with self.assertRaises(ValueError):
                audioroute.Splitter(source(), count)

    def test_tap_indices_are_bounded(self):
        splitter = audioroute.Splitter(source(), 2)
        for index in (-1, 2, 99):
            with self.assertRaises(ValueError):
                splitter.tap(index)

    def test_every_tap_reads_the_same_stream(self):
        splitter = audioroute.Splitter(source(), 4)
        blocks = []
        for index in range(4):
            blocks.append(bytes(audiocore.get_buffer(splitter.tap(index))[1]))
        self.assertEqual(len(set(blocks)), 1)
        self.assertNotEqual(blocks[0], bytes(len(blocks[0])))

    def test_a_tap_keeps_its_splitter_alive(self):
        # Handing a tap to a Mixer and dropping every other name for the
        # Splitter is the ordinary case, not an unusual one: the tap has to
        # own the ring it reads from.
        import gc
        tap = audioroute.Splitter(source(), 2).tap(0)
        gc.collect()
        self.assertNotEqual(bytes(audiocore.get_buffer(tap)[1]), b"")

    def test_a_dry_source_yields_silence_not_an_end(self):
        splitter = audioroute.Splitter(Dry(blocks=1), 2)
        first = splitter.tap(0)
        self.assertNotEqual(bytes(audiocore.get_buffer(first)[1]),
                            bytes(audioroute.CHUNK_FRAMES * 4))
        for _ in range(2):
            result, data = audiocore.get_buffer(first)
            self.assertEqual(result, audiocore.GET_BUFFER_MORE_DATA)
            self.assertEqual(bytes(data), bytes(audioroute.CHUNK_FRAMES * 4))

    def test_a_tap_can_feed_a_dynamics(self):
        splitter = audioroute.Splitter(source(), 2)
        node = audiodynamics.Dynamics(audiodynamics.DYN_COMPRESS,
                                      sample_rate=SAMPLE_RATE,
                                      threshold_db=-30.0)
        node.play(splitter.tap(1))
        data = bytes(audiocore.get_buffer(node)[1])
        self.assertEqual(len(data), audiodynamics.FRAMES * 4)
        self.assertNotEqual(data, bytes(len(data)))


if __name__ == "__main__":
    unittest.main()
