"""`Dynamics(feedback_gain_corrected=True)`: a feedback loop that lands on the
ratio it was asked for (audioif#62).

A feedback compressor's detector reads its own **output**, which is what gives
the design its program-dependent character. It also means the loop reduces its
own detector input, so it settles at its own fixed point rather than at the
ratio on the knob: measured against a 20 dB overshoot, 4:1 through 20:1 all
land between 8.57 and 9.74 dB of reduction — about 2:1 whatever is asked. A
character that has to make 4:1 through 20:1 therefore could not use it.

The correction is algebraic, and which algebra matters. With the detector
reading the output, the slope that settles on the input-referred curve is
`(R - 1)`, not `(1 - 1/R)`:

    g = -(R-1)(y - T)  and  y = x + g   =>   g = -(1 - 1/R)(x - T)

so the static curve is the feed-forward one while the detector still follows
the output.

**What this is deliberately not.** Dividing the fed-back sample by the gain
that produced it also reaches the right steady state — and it recovers the
input exactly, which cancels the loop. Measured, that version tracked
feed-forward to within **0.026 dB over a whole step response**: the right
number with none of the character, an option nobody would have a reason to
switch on. The test below that compares the transient against feed-forward is
there to keep it from being reintroduced.
"""

from array import array
import unittest

import audiocore
import audiodynamics

RATE = 48000
CHANNELS = 2
#: 20 dB of overshoot, which is what makes the settled reduction easy to read
#: against the algebra.
THRESHOLD_DB = -40.0
INPUT_DBFS = -20.0
BASE = {"threshold_db": THRESHOLD_DB, "knee_db": 0.0, "attack_ms": 5.0,
        "release_ms": 80.0}


def steady(dbfs=INPUT_DBFS, frames=4096):
    value = int(32767.0 * (10.0 ** (dbfs / 20.0)))
    return audiocore.RawSample(array("h", [value] * (frames * CHANNELS)),
                               sample_rate=RATE, channel_count=CHANNELS)


def settled_reduction(ratio, blocks=40, **extra):
    node = audiodynamics.Dynamics(audiodynamics.DYN_COMPRESS, sample_rate=RATE,
                                  channel_count=CHANNELS)
    node.set(ratio=ratio, **BASE)
    if extra:
        node.set(**extra)
    node.play(steady())
    for _ in range(blocks):
        audiocore.get_buffer(node)
    return -node.gain_reduction_db()


def wanted(ratio, over=20.0):
    """What the ratio asks for: the overshoot times the feed-forward slope."""
    return over * (1.0 - 1.0 / ratio)


def step_trace(ratio=8.0, blocks=24, loud_frames=3000, loud_dbfs=-20.0,
               **extra):
    """A quiet lead, a held loud passage, then quiet again.

    `loud_frames` matters and is why it is a parameter: the node renders 256
    frames per block, so 3000 loud frames is about eleven blocks and the
    passage is over by block fourteen. The ringing test below reads blocks 8-16
    as "while the input is held", which is only true with a longer passage -
    reading them against the short one measured the *release* and called it a
    wobble."""
    values = array("h")
    for dbfs, count in ((-40.0, 600), (loud_dbfs, loud_frames), (-40.0, 3000)):
        sample = int(32767.0 * (10.0 ** (dbfs / 20.0)))
        for _ in range(count):
            values.append(sample)
            values.append(sample)
    node = audiodynamics.Dynamics(audiodynamics.DYN_COMPRESS, sample_rate=RATE,
                                  channel_count=CHANNELS)
    node.set(ratio=ratio, **BASE)
    if extra:
        node.set(**extra)
    node.play(audiocore.RawSample(values, sample_rate=RATE,
                                  channel_count=CHANNELS))
    trace = []
    for _ in range(blocks):
        audiocore.get_buffer(node)
        trace.append(-node.gain_reduction_db())
    return trace


RATIOS = (4.0, 8.0, 12.0, 20.0)


class TheUncorrectedLoopMissesTheRatio(unittest.TestCase):
    """The defect, as a number, so the fix below has a baseline it cannot
    quietly lose."""

    def test_every_ratio_lands_near_two_to_one(self):
        for ratio in RATIOS:
            with self.subTest(ratio=ratio):
                reading = settled_reduction(ratio, feedback_detector=1)
                self.assertLess(reading, 10.0)
                self.assertLess(reading, wanted(ratio) - 4.0)


class TheCorrectedLoopLandsOnTheRatio(unittest.TestCase):

    def test_it_settles_where_the_algebra_says(self):
        for ratio in RATIOS:
            with self.subTest(ratio=ratio):
                self.assertAlmostEqual(
                    settled_reduction(ratio, feedback_detector=1,
                                      feedback_gain_corrected=1),
                    wanted(ratio), delta=0.01)

    def test_it_is_still_a_feedback_design(self):
        """The guard on the cancelling implementation. Same steady state as
        feed-forward, different path to it - if this ever falls to a fraction
        of a dB, the loop has been cancelled rather than inverted."""
        forward = step_trace()
        corrected = step_trace(feedback_detector=1,
                               feedback_gain_corrected=1)
        apart = max(abs(a - b) for a, b in zip(forward, corrected))
        self.assertGreater(apart, 1.0, "corrected feedback is tracking "
                           "feed-forward to %.4f dB, which means the loop was "
                           "cancelled, not inverted" % apart)

    def test_it_does_not_ring(self):
        """A slope of R-1 is steep. Overshoot past the settled value, or a
        wobble while the input is held, is what instability would look like."""
        for ratio in (4.0, 20.0, 100.0):
            with self.subTest(ratio=ratio):
                trace = step_trace(ratio=ratio, blocks=30,
                                   loud_frames=6000, loud_dbfs=-10.0,
                                   feedback_detector=1,
                                   feedback_gain_corrected=1)
                hold = trace[8:16]
                self.assertLess(max(hold) - min(hold), 0.01)
                self.assertLess(max(trace[:16]) - trace[14], 0.25)


class ItsScopeIsNarrow(unittest.TestCase):
    """Three claims the fixtures capture but cannot compare, asserted here."""

    def _render(self, mode, blocks=4, **options):
        node = audiodynamics.Dynamics(mode, sample_rate=RATE,
                                      channel_count=CHANNELS)
        node.set(**options)
        node.play(steady(dbfs=-12.0))
        return b"".join(bytes(audiocore.get_buffer(node)[1])
                        for _ in range(blocks))

    def test_it_is_inert_without_the_feedback_detector(self):
        self.assertEqual(
            self._render(audiodynamics.DYN_COMPRESS, ratio=8.0, **BASE),
            self._render(audiodynamics.DYN_COMPRESS, ratio=8.0,
                         feedback_gain_corrected=1, **BASE))

    def test_it_changes_nothing_outside_compress(self):
        for name, mode, extra in (
                ("limit", audiodynamics.DYN_LIMIT, {"threshold_db": -26.0}),
                ("expand", audiodynamics.DYN_EXPAND,
                 {"threshold_db": -20.0, "ratio": 3.0}),
                ("gate", audiodynamics.DYN_GATE, {"threshold_db": -22.0}),
                ("transient", audiodynamics.DYN_TRANSIENT,
                 {"attack_gain_db": 9.0, "sustain_gain_db": -7.0})):
            with self.subTest(mode=name):
                self.assertEqual(
                    self._render(mode, feedback_detector=1, **extra),
                    self._render(mode, feedback_detector=1,
                                 feedback_gain_corrected=1, **extra))

    def test_it_does_change_compress_with_the_detector_on(self):
        """The control for the two above: they would all pass if the option
        did nothing at all."""
        self.assertNotEqual(
            self._render(audiodynamics.DYN_COMPRESS, ratio=8.0,
                         feedback_detector=1, **BASE),
            self._render(audiodynamics.DYN_COMPRESS, ratio=8.0,
                         feedback_detector=1, feedback_gain_corrected=1,
                         **BASE))


if __name__ == "__main__":
    unittest.main()
