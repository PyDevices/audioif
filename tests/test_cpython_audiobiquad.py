"""audiobiquad: the claims the parity golden cannot make on its own.

`tests/parity/filter_f32_probe.py` pins what this module renders, and prints
the two invariants as integers so a hash covers them. What it deliberately
does not do is compare the module with the ported kernels it was added
because of -- that needs decibels, and a probe whose output has to be
integer-exact on three interpreters should not be computing logarithms.

So the comparisons live here:

- the float biquad agrees with `audiofilters.Filter` mid-band, which is what
  says it is the same filter and not merely a filter;
- one all-pass stage's phase really does pass -90 degrees at `frequency`,
  where the ported phaser's lands high enough that its class has to pre-warp;
- `feedback=0.0` nulls, and the ported node's 0.1..0.9 clamp cannot get near
  it however its frequency is trimmed;
- and the frozen `synthio.Biquad` kernel has fixed points it parks on, which
  is the measurement audioif#23 is about, reproduced here at the kernel so
  the contrast is a fact in the tree rather than a link.
"""

import math
import unittest
from array import array

import _audioif
import audiobiquad
import audiocore
import audiofilters
import synthio

SAMPLE_RATE = 8000

#: One period of a sine at 28000 peak. Stepping by 1/2/4/8/16 gives
#: 125/250/500/1000/2000 Hz at 8 kHz with no rounding anywhere.
SINE64 = tuple(int(round(28000 * math.sin(2 * math.pi * k / 64)))
               for k in range(64))


def tone(step, frames=4096, channels=1, level=28000):
    values = array("h")
    index = 0
    for _frame in range(frames):
        for _channel in range(channels):
            values.append(SINE64[index % 64] * level // 28000)
        index += step
    return audiocore.RawSample(values, sample_rate=SAMPLE_RATE,
                               channel_count=channels)


def silence(frames=2048, channels=1):
    return audiocore.RawSample(array("h", bytes(frames * channels * 2)),
                               sample_rate=SAMPLE_RATE,
                               channel_count=channels)


def peak(node, blocks=16, skip=8):
    """Settled peak absolute sample, the first `skip` blocks discarded."""
    top = 0
    for index in range(blocks):
        data = bytes(audiocore.get_buffer(node)[1])
        if index < skip:
            continue
        for position in range(0, len(data), 2):
            word = data[position] | (data[position + 1] << 8)
            if word >= 32768:
                word -= 65536
            top = max(top, abs(word))
    return top


def db(value, reference=28000.0):
    return 20.0 * math.log10(max(value, 1) / reference)


class BiquadLevelTest(unittest.TestCase):
    """The float kernel is the same filter the frozen one is."""

    def _level(self, node):
        return peak(node)

    def test_it_matches_the_ported_filter_across_the_band(self):
        for step, hertz in ((1, 125.0), (2, 250.0), (4, 500.0),
                            (8, 1000.0), (16, 2000.0)):
            for cutoff in (300.0, 900.0, 2500.0):
                mine = audiobiquad.Biquad(mode=audiobiquad.LOW_PASS,
                                          frequency=cutoff, Q=0.7071067811865475,
                                          sample_rate=SAMPLE_RATE,
                                          channel_count=1)
                mine.play(tone(step))
                theirs = audiofilters.Filter(
                    filter=synthio.Biquad(synthio.FilterMode.LOW_PASS,
                                          frequency=cutoff,
                                          Q=0.7071067811865475),
                    buffer_size=512, sample_rate=SAMPLE_RATE,
                    channel_count=1)
                theirs.play(tone(step))
                difference = db(self._level(mine)) - db(self._level(theirs))
                self.assertLess(
                    abs(difference), 0.5,
                    "%g Hz through a %g Hz low-pass: float %+0.2f dB against "
                    "the ported kernel" % (hertz, cutoff, difference))

    def test_a_shelf_reaches_its_asked_for_gain(self):
        # 6000 rather than full scale: +9 dB on a 28000 peak is 78,000, and
        # what that would measure is the clamp, not the shelf.
        flat = audiobiquad.Biquad(mode=audiobiquad.LOW_SHELF, frequency=1000.0,
                                  gain_db=0.0, sample_rate=SAMPLE_RATE,
                                  channel_count=1)
        flat.play(tone(1, level=6000))
        lifted = audiobiquad.Biquad(mode=audiobiquad.LOW_SHELF,
                                    frequency=1000.0, gain_db=9.0,
                                    sample_rate=SAMPLE_RATE, channel_count=1)
        lifted.play(tone(1, level=6000))
        gain = db(peak(lifted)) - db(peak(flat))
        self.assertAlmostEqual(gain, 9.0, delta=0.5)

    def test_mix_zero_is_a_wire(self):
        node = audiobiquad.Biquad(mode=audiobiquad.LOW_PASS, frequency=100.0,
                                  mix=0.0, sample_rate=SAMPLE_RATE,
                                  channel_count=1)
        node.play(tone(8))
        self.assertEqual(peak(node), 28000)


class TailTest(unittest.TestCase):
    """Tier 1: a decaying tail reaches exact zero, and stays there."""

    def _tail(self, node):
        node.play(tone(4, frames=512))
        audiocore.get_buffer(node)
        node.play(silence())
        for index in range(600):
            data = bytes(audiocore.get_buffer(node)[1])
            if data == bytes(len(data)):
                # And it must stay zero, not cross zero on the way past.
                for _again in range(40):
                    more = bytes(audiocore.get_buffer(node)[1])
                    self.assertEqual(more, bytes(len(more)))
                return index
        return None

    def test_every_biquad_mode_reaches_exact_zero(self):
        for mode in audiobiquad.MODES:
            for frequency, q in ((31.25, 0.7071067811865475), (62.5, 8.0),
                                 (900.0, 2.0)):
                node = audiobiquad.Biquad(mode=mode, frequency=frequency, Q=q,
                                          gain_db=12.0,
                                          sample_rate=SAMPLE_RATE,
                                          channel_count=1)
                self.assertIsNotNone(
                    self._tail(node),
                    "mode %d at %g Hz Q %g never reached zero" % (
                        mode, frequency, q))

    def test_the_all_pass_reaches_exact_zero_at_every_feedback(self):
        for feedback in (0.0, 0.5, -0.5, 0.95, -0.95):
            node = audiobiquad.AllPass(stages=4, frequency=1139.6,
                                       feedback=feedback, mix=0.5,
                                       sample_rate=SAMPLE_RATE,
                                       channel_count=1)
            self.assertIsNotNone(
                self._tail(node),
                "feedback %g never reached zero" % (feedback,))

    def test_the_frozen_kernel_has_fixed_points_this_one_does_not(self):
        """audioif#23, reproduced at the kernel rather than cited.

        Not every trajectory lands on one -- which is why the defect went
        unnoticed -- but a plain DC burst into a low-pass does, and the state
        it lands on reproduces itself for as long as anyone cares to look.
        """
        parked = []
        for frequency, expected in ((100.0, 1), (40.0, 4)):
            state = _audioif.BiquadState()
            state.process_s16(array("h", [30000] * 256).tobytes(), 0,
                              frequency, 0.7071067811865475, 1.0, 48000, 1.0,
                              1)
            zeros = bytes(512)
            for _block in range(3000):
                out = state.process_s16(zeros, 0, frequency,
                                        0.7071067811865475, 1.0, 48000, 1.0, 1)
            word = int.from_bytes(out[0:2], "little")
            if word >= 32768:
                word -= 65536
            parked.append((frequency, word))
            self.assertEqual(abs(word), expected)
        self.assertEqual(len(parked), 2)


class AllPassTest(unittest.TestCase):
    def test_the_break_frequency_is_the_break_frequency(self):
        """One stage's phase passes -90 degrees at `frequency`.

        `audiofilters.Phaser`'s does not: its coefficient is the small-angle
        form, so its class pre-warps in Python before handing the number over
        (audiocomponents Phaser seed section 4).
        """
        for hertz in (500.0, 1000.0, 2000.0):
            node = audiobiquad.AllPass(stages=1, frequency=hertz,
                                       sample_rate=SAMPLE_RATE,
                                       channel_count=1)
            c = node.coefficient
            omega = 2 * math.pi * hertz / SAMPLE_RATE
            numerator = complex(c + math.cos(omega), -math.sin(omega))
            denominator = complex(1 + c * math.cos(omega),
                                  -c * math.sin(omega))
            phase = math.degrees(math.atan2(
                (numerator / denominator).imag,
                (numerator / denominator).real))
            self.assertAlmostEqual(phase, -90.0, delta=0.2)

    def test_zero_feedback_nulls_and_the_ported_clamp_cannot(self):
        mine = audiobiquad.AllPass(stages=4, frequency=1139.6, feedback=0.0,
                                   mix=0.5, sample_rate=SAMPLE_RATE,
                                   channel_count=1)
        mine.play(tone(4))
        mine_db = db(peak(mine))
        self.assertLess(mine_db, -40.0)

        # The ported node cannot be asked for zero, so give it every chance:
        # sweep its frequency and take its own best null at its floor.
        best = 1 << 20
        for index in range(60, 160):
            frequency = 1920.0 * index / 100.0
            theirs = audiofilters.Phaser(frequency=frequency, feedback=0.1,
                                         mix=1.0, stages=4, buffer_size=512,
                                         sample_rate=SAMPLE_RATE,
                                         channel_count=1)
            theirs.play(tone(4))
            best = min(best, peak(theirs))
        self.assertGreater(db(best), -30.0)
        self.assertGreater(db(best) - mine_db, 25.0)

    def test_zero_and_the_ported_floor_are_different_settings(self):
        """0.0 and 0.1 render identically on the ported node; not here."""
        levels = []
        for feedback in (0.0, 0.1):
            node = audiobiquad.AllPass(stages=4, frequency=1139.6,
                                       feedback=feedback, mix=0.5,
                                       sample_rate=SAMPLE_RATE,
                                       channel_count=1)
            node.play(tone(4))
            levels.append(peak(node))
        self.assertNotEqual(levels[0], levels[1])

        ported = []
        for feedback in (0.0, 0.1):
            node = audiofilters.Phaser(frequency=1920.0, feedback=feedback,
                                       mix=1.0, stages=4, buffer_size=512,
                                       sample_rate=SAMPLE_RATE,
                                       channel_count=1)
            node.play(tone(4))
            ported.append(peak(node))
        self.assertEqual(ported[0], ported[1])


class SurfaceTest(unittest.TestCase):
    def test_it_presents_itself_as_a_sample(self):
        node = audiobiquad.Biquad(sample_rate=SAMPLE_RATE)
        self.assertEqual(node.sample_rate, SAMPLE_RATE)
        self.assertEqual(node.channel_count, 2)
        self.assertEqual(node.bits_per_sample, 16)
        self.assertTrue(node.samples_signed)
        self.assertFalse(node.playing)

    def test_a_starved_node_hands_out_silence_not_a_short_block(self):
        for node in (audiobiquad.Biquad(sample_rate=SAMPLE_RATE),
                     audiobiquad.AllPass(sample_rate=SAMPLE_RATE)):
            result, data = audiocore.get_buffer(node)
            self.assertEqual(result, audiocore.GET_BUFFER_MORE_DATA)
            self.assertEqual(len(bytes(data)), audiobiquad.FRAMES * 4)
            self.assertEqual(bytes(data), bytes(len(bytes(data))))

    def test_bad_arguments_are_refused(self):
        with self.assertRaises(ValueError):
            audiobiquad.Biquad(mode=99, sample_rate=SAMPLE_RATE)
        with self.assertRaises(ValueError):
            audiobiquad.Biquad(channel_count=3, sample_rate=SAMPLE_RATE)
        with self.assertRaises(ValueError):
            audiobiquad.AllPass(stages=0, sample_rate=SAMPLE_RATE)
        with self.assertRaises(ValueError):
            audiobiquad.AllPass(stages=audiobiquad.MAX_STAGES + 1,
                                sample_rate=SAMPLE_RATE)

    def test_a_block_input_is_read_once_per_chunk(self):
        sweep = synthio.LFO(rate=3.0, scale=400.0, offset=900.0)
        node = audiobiquad.AllPass(stages=4, frequency=sweep, feedback=0.2,
                                   mix=0.5, sample_rate=SAMPLE_RATE,
                                   channel_count=1)
        node.play(tone(4))
        seen = set()
        for _block in range(12):
            audiocore.get_buffer(node)
            seen.add(round(node.coefficient, 6))
        self.assertGreater(len(seen), 3)


if __name__ == "__main__":
    unittest.main()
