"""audioverb.Tank: the surface the parity gate cannot check.

What the tank *renders* is pinned across every interpreter by
tests/parity/tank_probe.py through verify_dsp.py. What is left for here is
everything that comparison cannot reach: the argument forms, the errors, the
things a Python-defined audiosample can do to it, and the two behaviours the
module exists for -- a network whose topology comes from Python, and a tail
that reaches exact zero rather than sitting at one LSB forever.
"""

import unittest
from array import array

import audiocore
import audioverb

SAMPLE_RATE = 8000


def source(frames=3000, level=18000, burst=160, channels=2):
    values = array("h")
    for frame in range(frames):
        for channel in range(channels):
            if frame < burst:
                shape = ((frame * (97 + channel * 18)) % 2001) - 1000
                values.append(shape * level // 1000)
            else:
                values.append(0)
    return audiocore.RawSample(values, sample_rate=SAMPLE_RATE,
                               channel_count=channels)


def render(node, blocks, channels=2):
    return b"".join(bytes(audiocore.get_buffer(node)[1])
                    for _ in range(blocks))


def samples(data):
    values = array("h")
    values.frombytes(data)
    return values


class TankSurface(unittest.TestCase):
    def test_mix_zero_is_a_wire(self):
        """The whole network runs and the output is the input, sample for
        sample -- which is what makes `mix` safe to automate down to nothing."""
        node = audioverb.Tank(sample_rate=SAMPLE_RATE, max_predelay_ms=40.0,
                              mix=0.0, decay=0.9, mod_rate_hz=1.1,
                              mod_depth_ms=0.3)
        node.play(source(burst=3000))
        rendered = render(node, 6)
        reference = bytes(audiocore.get_buffer(source(burst=3000))[1])
        self.assertEqual(rendered, reference[:len(rendered)])

    def test_tail_reaches_exact_zero(self):
        """Every line write is a magnitude truncation, so a loop under unity
        gain strictly loses magnitude every pass. A rounding quantiser leaves
        the network humming at one LSB for as long as it is pulled."""
        node = audioverb.Tank(sample_rate=SAMPLE_RATE, max_predelay_ms=40.0,
                              mix=2.0, decay=0.4)
        node.play(source(frames=60000, burst=160))
        silent = None
        for index in range(200):
            data = bytes(audiocore.get_buffer(node)[1])
            if not any(data):
                silent = index
                break
        self.assertIsNotNone(silent, "the tail never reached exact zero")
        # And it stays there: nothing re-excites a network with no input.
        for _ in range(8):
            self.assertFalse(any(bytes(audiocore.get_buffer(node)[1])))

    def test_reverberates_and_decays(self):
        node = audioverb.Tank(sample_rate=SAMPLE_RATE, max_predelay_ms=40.0,
                              mix=2.0, decay=0.6)
        node.play(source())
        peaks = [max(abs(value) for value in samples(
            bytes(audiocore.get_buffer(node)[1]))) for _ in range(10)]
        # Something arrives after the 160-frame burst has gone by ...
        self.assertGreater(max(peaks[1:]), 0)
        # ... and the second half of the run is quieter than the first.
        self.assertLess(max(peaks[6:]), max(peaks[:4]))

    def test_predelay_moves_the_wet_onset(self):
        def onset(node):
            values = samples(render(node, 8))
            for index, value in enumerate(values):
                if abs(value) > 8:
                    return index // 2
            return None

        plain = audioverb.Tank(sample_rate=SAMPLE_RATE, max_predelay_ms=60.0,
                               mix=2.0, decay=0.3)
        plain.play(source())
        delayed = audioverb.Tank(sample_rate=SAMPLE_RATE, max_predelay_ms=60.0,
                                 mix=2.0, decay=0.3, predelay_ms=20.0)
        delayed.play(source())
        self.assertEqual(onset(delayed) - onset(plain),
                         int(0.020 * SAMPLE_RATE))

    def test_python_supplied_topology_renders(self):
        delays = [16, 12, 40, 28, 70, 460, 190, 380, 95, 430, 275, 330]
        taps = [0, 9, 27, 0.6, 0, 5, 200, -0.6, 1, 5, 36, 0.6, 1, 11, 12, -0.6]
        node = audioverb.Tank(sample_rate=SAMPLE_RATE, max_predelay_ms=20.0,
                              delays=delays, taps=taps, mix=2.0, decay=0.6)
        node.play(source())
        custom = render(node, 6)
        stock = audioverb.Tank(sample_rate=SAMPLE_RATE, max_predelay_ms=20.0,
                               mix=2.0, decay=0.6)
        stock.play(source())
        self.assertNotEqual(custom, render(stock, 6))
        self.assertTrue(any(custom))

    def test_set_changes_the_render_without_emptying_the_lines(self):
        node = audioverb.Tank(sample_rate=SAMPLE_RATE, max_predelay_ms=40.0,
                              mix=2.0, decay=0.75)
        node.play(source())
        before = render(node, 3)
        node.set(damping_hz=600.0, decay=0.3)
        after = render(node, 3)
        self.assertTrue(any(after), "the lines were emptied by set()")
        self.assertNotEqual(before, after)
        node.clear()
        self.assertFalse(any(render(node, 1)),
                         "clear() left something in the lines")

    def test_starved_gives_silence_not_a_short_block(self):
        node = audioverb.Tank(sample_rate=SAMPLE_RATE, max_predelay_ms=20.0)
        for _ in range(3):
            result, data = audiocore.get_buffer(node)
            data = bytes(data)
            self.assertEqual(result, audiocore.GET_BUFFER_MORE_DATA)
            self.assertEqual(len(data), audioverb.FRAMES * 4)
            self.assertFalse(any(data))

    def test_mono(self):
        node = audioverb.Tank(sample_rate=SAMPLE_RATE, max_predelay_ms=20.0,
                              channel_count=1, mix=2.0, decay=0.6)
        node.play(source(channels=1))
        data = render(node, 4)
        self.assertEqual(len(data), 4 * audioverb.FRAMES * 2)
        self.assertTrue(any(data))


class TankArguments(unittest.TestCase):
    def test_delays_must_be_twelve(self):
        with self.assertRaises(ValueError):
            audioverb.Tank(sample_rate=SAMPLE_RATE, delays=[100] * 11)

    def test_every_line_needs_room_for_the_interpolator(self):
        with self.assertRaises(ValueError):
            audioverb.Tank(sample_rate=SAMPLE_RATE, delays=[3] * 12)

    def test_taps_come_in_fours(self):
        with self.assertRaises(ValueError):
            audioverb.Tank(sample_rate=SAMPLE_RATE, taps=[0, 5, 10])

    def test_a_tap_cannot_name_a_line_that_does_not_exist(self):
        with self.assertRaises(ValueError):
            audioverb.Tank(sample_rate=SAMPLE_RATE, taps=[0, 99, 10, 0.5])

    def test_a_tap_cannot_name_a_third_channel(self):
        with self.assertRaises(ValueError):
            audioverb.Tank(sample_rate=SAMPLE_RATE, taps=[2, 5, 10, 0.5])

    def test_a_tap_cannot_reach_past_its_line(self):
        with self.assertRaises(ValueError):
            audioverb.Tank(sample_rate=SAMPLE_RATE, taps=[0, 5, 10 ** 9, 0.5])

    def test_channel_count(self):
        with self.assertRaises(ValueError):
            audioverb.Tank(sample_rate=SAMPLE_RATE, channel_count=3)

    def test_negative_predelay(self):
        with self.assertRaises(ValueError):
            audioverb.Tank(sample_rate=SAMPLE_RATE, max_predelay_ms=-1.0)

    def test_unknown_option(self):
        with self.assertRaises(TypeError):
            audioverb.Tank(sample_rate=SAMPLE_RATE, roomsize=0.5)

    def test_set_refuses_what_construction_fixed(self):
        node = audioverb.Tank(sample_rate=SAMPLE_RATE)
        for name in ("sample_rate", "channel_count", "max_predelay_ms",
                     "delays", "taps"):
            with self.assertRaises(TypeError):
                node.set(**{name: 1})

    def test_options_clamp_rather_than_raise(self):
        """A knob past its bound is held at the bound, the way every other
        node in the palette treats one."""
        node = audioverb.Tank(sample_rate=SAMPLE_RATE, max_predelay_ms=40.0,
                              decay=9.0, diffusion=9.0, mix=9.0, width=9.0,
                              drive=9.0, tone_db=900.0, predelay_ms=9e5,
                              mod_depth_ms=9e5, mod_rate_hz=9e5)
        node.play(source())
        self.assertEqual(len(render(node, 2)), 2 * audioverb.FRAMES * 4)


if __name__ == "__main__":
    unittest.main()
