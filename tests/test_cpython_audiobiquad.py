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

## The traits, with their bars

`docs/correctness-standard.md` is what this file implements for `audiobiquad`:
the module is ours, upstream CircuitPython has no counterpart, so it is held to
three-target agreement (`tests/parity/filter_f32_probe.py`, run by `verify_dsp`)
plus the numeric traits below. Each has an ID so an issue or an evidence pack
can cite one, and each names its bar so nobody has to read the assertion to
learn what is being promised.

| ID | Trait | Bar |
|---|---|---|
| B1 | The float kernel is the same filter as `audiofilters.Filter` mid-band | 1.5 dB across the band |
| B2 | A shelf reaches the gain it was asked for | 0.5 dB |
| B3 | `mix=0` is a bit-exact wire | exact |
| B4 | Every mode's tail reaches exact zero and stays there | exact, inside 600 blocks |
| B5 | An all-pass tail reaches exact zero at every feedback | exact |
| B6 | One all-pass stage passes −90° at `frequency` | 12° |
| B7 | `feedback=0.0` nulls, which the ported clamp cannot reach | 0 against ≥ 1 LSB |
| B8 | Silence in gives exactly zero out, every mode | exact |
| B9 | Full-scale DC passes a low-pass at unity | exact, 0 LSB |
| B10 | `clear()` leaves the node as a freshly built one, every mode | exact |
| B11 | A band-pass peaks at 0 dB at its own centre | 0.05 dB at and above 100 Hz |
| B12 | Presents as a sample; a starved node yields silence, not a short block | exact |

**B11 has a recorded departure.** Below 100 Hz at high Q the direct-form I
recursion in `float` loses peak gain — measured **−1.0906 dB** at 20 Hz / Q 32
on a 48 kHz graph, against RBJ's 0 dB, while 100 Hz / Q 16 reads +0.0009 dB and
1 kHz / Q 2 reads −0.0004 dB. That is audioif#64. The trait therefore carries
two bars: a real one where the property holds, and a looser one at the low
corner that records the departure so a *worsening* fails while a fix does not.

**Where a trait has a control that fails it**, the control is named in the test
rather than left implied: a trait no implementation can fail is not a
measurement. B9's control is `audiofilters.Filter`, which settles a full-scale
DC step at 28520 rather than 32767 - not a defect, but upstream's two-voice
mix-down knee, `(32767 - 28000) * 7151 >> 16 + 28000`, which this module does
not apply. B4's control is the frozen `synthio.Biquad` kernel, whose fixed
points are the subject of audioif#23 and are reproduced here.
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
        """B1."""
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
        """B2."""
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
        """B3."""
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
        """B4."""
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
        """B5."""
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

        **The numbers here were 1 and 4 until 2026-09-09, and that was this
        test measuring the wrong kernel.** `BiquadState.process_s16` ran
        audioif's widened fixed point at the time, which does park but only on
        a negligible value; audioif#77 pointed it at CircuitPython's actual Q15
        arithmetic, which is what the name always claimed. The defect is far
        larger than 1 LSB:

            40 Hz   parks at 16143      100 Hz  parks at 2631
            400 Hz  parks at 160       1000 Hz  parks at 22

        16143 is half of full scale, held forever, from a filter asked for a
        40 Hz low-pass. Measured identically on the CPython extension, desktop
        MicroPython and CircuitPython 10.3.0 (2026-09-09), so it is a fact
        about CircuitPython's kernel and not about one binding. `audiobiquad`,
        whose float state is the point of it, reaches exact zero at every one of
        these -- that is B4 above.

        This is the measurement `docs/upstream-reports/biquad-band-edges.md`
        exists to carry, and it is the cost of holding `synthio.Biquad` to
        CircuitPython's bytes.
        """
        parked = []
        for frequency, expected in ((100.0, 2631), (40.0, 16143)):
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
        """B6 - one stage's phase passes -90 degrees at `frequency`.

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
        """B7."""
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
        """B12."""
        node = audiobiquad.Biquad(sample_rate=SAMPLE_RATE)
        self.assertEqual(node.sample_rate, SAMPLE_RATE)
        self.assertEqual(node.channel_count, 2)
        self.assertEqual(node.bits_per_sample, 16)
        self.assertTrue(node.samples_signed)
        self.assertFalse(node.playing)

    def test_a_starved_node_hands_out_silence_not_a_short_block(self):
        """B12."""
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


def dc(level, frames=4096, channels=1):
    return audiocore.RawSample(array("h", [level] * (frames * channels)),
                               sample_rate=SAMPLE_RATE,
                               channel_count=channels)


def settled_words(node, blocks=16, skip=10):
    """Every sample of the last `blocks - skip` blocks, signed."""
    out = []
    for index in range(blocks):
        data = bytes(audiocore.get_buffer(node)[1])
        if index < skip:
            continue
        for position in range(0, len(data), 2):
            word = data[position] | (data[position + 1] << 8)
            out.append(word - 65536 if word >= 32768 else word)
    return out


class UniversalTraitTest(unittest.TestCase):
    """The traits every node of ours carries, on this one.

    B8, B9 and B10 are the shape `docs/correctness-standard.md` asks of every
    audioif-own module. They are here first because `audiobiquad` is what ten
    of the Phase 2 `audioeffects` classes are built on, so a defect here is a
    defect in all of them.
    """

    def _low_pass(self, frequency=200.0, q=0.7071067811865475, **extra):
        return audiobiquad.Biquad(mode=audiobiquad.LOW_PASS,
                                  frequency=frequency, Q=q, mix=1.0,
                                  sample_rate=SAMPLE_RATE, channel_count=1,
                                  **extra)

    def test_silence_in_is_exactly_zero_out_in_every_mode(self):
        """B8. Not the same claim as B4: that one is about a tail draining,
        this one is about a node that was never given anything."""
        for mode in audiobiquad.MODES:
            with self.subTest(mode=mode):
                node = audiobiquad.Biquad(mode=mode, frequency=100.0, Q=8.0,
                                          gain_db=12.0,
                                          sample_rate=SAMPLE_RATE,
                                          channel_count=1)
                node.play(silence())
                for _block in range(8):
                    data = bytes(audiocore.get_buffer(node)[1])
                    self.assertEqual(data, bytes(len(data)))

    def test_B8_reads_real_output_and_not_an_empty_one(self):
        """B8's control. "Every block was zero" is also what a probe that
        pulled nothing would report, so the same read on a signal must not be
        zero. Absence reading as agreement is the failure mode this exists
        against."""
        node = audiobiquad.Biquad(mode=audiobiquad.LOW_PASS, frequency=2000.0,
                                  Q=0.7071067811865475, mix=1.0,
                                  sample_rate=SAMPLE_RATE, channel_count=1)
        node.play(tone(8))
        heard = False
        for _block in range(8):
            data = bytes(audiocore.get_buffer(node)[1])
            self.assertTrue(len(data) > 0)
            heard = heard or data != bytes(len(data))
        self.assertTrue(heard, "the same read that B8 calls silence reports "
                        "silence on a tone as well, so it measures nothing")

    def test_full_scale_dc_passes_a_low_pass_at_unity(self):
        """B9, and it is the trait that catches an overflow.

        A low-pass has unity gain at DC, so a full-scale step must come back
        as itself - exactly, at both rails. "Stays inside int16" would not do
        as a check: an overflowed value wraps to something *in* range, which
        is how the MicroPython flanger's int32 product went unnoticed by a
        matching golden. This is analytic, and any wrap in the recursion
        destroys it by thousands of LSB.
        """
        for level in (32767, -32768, 20000):
            with self.subTest(level=level):
                node = self._low_pass()
                node.play(dc(level))
                words = settled_words(node)
                self.assertEqual(max(abs(word - level) for word in words), 0)

    def test_the_ported_kernel_cannot_hold_B9(self):
        """B9's control: a trait no implementation can fail is not a
        measurement.

        `audiofilters.Filter` settles the same step at 28520, not 32767 -
        4247 LSB out. That is not a defect in it: it applies synthio's
        two-voice mix-down, whose knee is at +/-28000, and
        `(32767 - 28000) * 7151 >> 16 + 28000` is exactly 28520. This module
        does not apply that knee, which is the difference B9 pins.
        """
        ported = audiofilters.Filter(
            filter=synthio.Biquad(synthio.FilterMode.LOW_PASS, 200.0,
                                  Q=0.7071067811865475),
            sample_rate=SAMPLE_RATE, channel_count=1, buffer_size=512)
        ported.play(dc(32767))
        words = settled_words(ported)
        self.assertEqual(words[-1], 28520)
        self.assertGreater(max(abs(word - 32767) for word in words), 4000)

    def test_clear_leaves_the_node_as_a_freshly_built_one(self):
        """B10. A reset that leaves anything behind is a reset that does not
        mean what it says - audioif#56 is that defect in `audiodynamics`, and
        this is the trait that would have caught it there."""
        for mode in audiobiquad.MODES:
            with self.subTest(mode=mode):
                used = audiobiquad.Biquad(mode=mode, frequency=100.0, Q=8.0,
                                          sample_rate=SAMPLE_RATE,
                                          channel_count=1)
                used.play(dc(30000))
                for _block in range(6):
                    audiocore.get_buffer(used)
                used.clear()
                used.play(silence())

                fresh = audiobiquad.Biquad(mode=mode, frequency=100.0, Q=8.0,
                                           sample_rate=SAMPLE_RATE,
                                           channel_count=1)
                fresh.play(silence())
                for _block in range(6):
                    self.assertEqual(
                        bytes(audiocore.get_buffer(used)[1]),
                        bytes(audiocore.get_buffer(fresh)[1]))


    def test_B10_discriminates_a_node_that_was_not_cleared(self):
        """B10's control: without `clear()` the two must differ, or the
        comparison would pass for a node that keeps everything."""
        used = audiobiquad.Biquad(mode=audiobiquad.LOW_PASS, frequency=100.0,
                                  Q=8.0, sample_rate=SAMPLE_RATE,
                                  channel_count=1)
        used.play(dc(30000))
        for _block in range(6):
            audiocore.get_buffer(used)
        used.play(silence())          # deliberately NOT cleared

        fresh = audiobiquad.Biquad(mode=audiobiquad.LOW_PASS, frequency=100.0,
                                   Q=8.0, sample_rate=SAMPLE_RATE,
                                   channel_count=1)
        fresh.play(silence())
        differed = any(bytes(audiocore.get_buffer(used)[1])
                       != bytes(audiocore.get_buffer(fresh)[1])
                       for _block in range(6))
        self.assertTrue(differed, "an uncleared node already matches a fresh "
                        "one, so B10 cannot fail and measures nothing")


class BandPassPeakTest(unittest.TestCase):
    """B11, and the departure audioif#64 records."""

    #: RBJ's constant-0 dB-peak band-pass has unity gain at its own centre at
    #: every Q. Anything else is the arithmetic, not the design.
    WANTED_DB = 0.0

    def _peak_db(self, rate, hz, q, level=20000):
        node = audiobiquad.Biquad(mode=audiobiquad.BAND_PASS, frequency=hz,
                                  Q=q, mix=1.0, sample_rate=rate,
                                  channel_count=1)
        values = array("h")
        for frame in range(int(rate / hz) * 400):
            values.append(int(level * math.sin(2 * math.pi * hz * frame
                                               / rate)))
        node.play(audiocore.RawSample(values, sample_rate=rate,
                                      channel_count=1))
        top = 0
        for index in range(200):
            data = bytes(audiocore.get_buffer(node)[1])
            if index < 120:
                continue
            for position in range(0, len(data), 2):
                word = data[position] | (data[position + 1] << 8)
                if word >= 32768:
                    word -= 65536
                top = max(top, abs(word))
        return 20.0 * math.log10(max(top, 1) / level)

    def test_it_peaks_at_its_own_centre_from_100_hz_up(self):
        """B11 where the property holds, and the bar is tight because it does:
        measured +0.0009 dB at 100 Hz / Q 16 and -0.0004 dB at 1 kHz / Q 2."""
        for rate, hz, q in ((48000, 100.0, 16.0), (48000, 1000.0, 2.0),
                            (SAMPLE_RATE, 1000.0, 2.0)):
            with self.subTest(rate=rate, hz=hz, q=q):
                self.assertAlmostEqual(self._peak_db(rate, hz, q),
                                       self.WANTED_DB, delta=0.05)

    def test_the_low_corner_departs_and_the_departure_is_recorded(self):
        """B11's recorded departure: audioif#64.

        Direct-form I with `float` state loses peak gain where the two
        feedback terms nearly cancel. At 20 Hz / Q 32 on a 48 kHz graph the
        centre reads **-1.0906 dB** against RBJ's 0. The bar here is loose on
        purpose: it fails if the loss gets worse, and it does not stand in the
        way of a fix. Tighten it, or delete this test for the one above, when
        audioif#64 is closed.
        """
        measured = self._peak_db(48000, 20.0, 32.0)
        self.assertLess(measured, -0.2, "the departure is gone - #64 may be "
                        "fixed, in which case fold this into B11 proper")
        self.assertGreater(measured, -1.5,
                           "the loss at 20 Hz / Q 32 is worse than the "
                           "-1.0906 dB audioif#64 records")
