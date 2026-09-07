"""audioshaper.Waveshaper: the claims the parity golden cannot carry.

tests/parity/waveshaper_probe.py pins what this node *renders*, byte for
byte, on every interpreter. What it cannot say is whether the bytes are the
right ones. These are the measurements the node was asked for -- does
oversampling actually lower the alias floor, does the hysteresis option
actually enclose an area and does that area grow with drive -- each with the
control that would go red if the mechanism were absent.
"""

import math
import unittest
from array import array

import audiocore
import audioshaper

SAMPLE_RATE = 48000
POINTS = 1024
Q15 = 32768


def clamp15(value):
    return max(-32768, min(32767, value))


def positions():
    last = POINTS - 1
    return [(2 * index - last) * Q15 // last for index in range(POINTS)]


def cubic_curve():
    """y = 1.5x - 0.5x^3, in integers so every interpreter builds it alike."""
    return array("h", [clamp15((3 * x * Q15 * Q15 - x * x * x) //
                               (2 * Q15 * Q15)) for x in positions()])


CUBIC = cubic_curve()


def render(values, **options):
    """Push one array of interleaved frames through a node and take it back."""
    node = audioshaper.Waveshaper(sample_rate=SAMPLE_RATE, curve=CUBIC,
                                 **options)
    node.play(audiocore.RawSample(
        values, sample_rate=SAMPLE_RATE,
        channel_count=options.get("channel_count", 2)))
    channels = options.get("channel_count", 2)
    out = bytearray()
    frames = len(values) // channels
    while len(out) < frames * 2 * channels:
        out += bytes(audiocore.get_buffer(node)[1])
    taken = array("h")
    taken.frombytes(bytes(out[:frames * 2 * channels]))
    return taken


def sine(cycles, frames, level):
    values = array("h")
    for index in range(frames):
        sample = int(round(level *
                           math.sin(2.0 * math.pi * cycles * index / frames)))
        values.append(clamp15(sample))
        values.append(clamp15(sample))
    return values


def bin_energy(samples, cycles, frames):
    """|X[k]|^2 by Goertzel, k = cycles, exactly on a bin."""
    angle = 2.0 * math.pi * cycles / frames
    coefficient = 2.0 * math.cos(angle)
    first = second = 0.0
    for value in samples:
        current = value + coefficient * first - second
        second = first
        first = current
    real = first - second * math.cos(angle)
    imaginary = second * math.sin(angle)
    return real * real + imaginary * imaginary


def alias_floor_db(oversample, cycles=173, frames=8192, level=16000,
                   **options):
    """Non-harmonic energy relative to the fundamental, in dB.

    `cycles` is a whole number of cycles in the window, so every harmonic and
    every alias lands on its own bin and a rectangular window leaks nothing.
    Harmonics are h*cycles while that is still under Nyquist; everything
    above folds, and where it lands is an alias, which is the distinction the
    measurement exists to make.
    """
    settle = frames
    total = settle + frames
    values = array("h")
    for index in range(total):
        sample = int(round(level * math.sin(
            2.0 * math.pi * cycles * index / frames)))
        values.append(clamp15(sample))
        values.append(clamp15(sample))
    rendered = render(values, oversample=oversample, **options)
    left = [float(rendered[index * 2]) for index in range(settle, total)]
    mean = sum(left) / len(left)
    left = [value - mean for value in left]
    energy = sum(value * value for value in left)
    harmonics = 0.0
    fundamental = 0.0
    harmonic = 1
    while harmonic * cycles < frames // 2:
        power = 2.0 * bin_energy(left, harmonic * cycles, frames) / frames
        if harmonic == 1:
            fundamental = power
        harmonics += power
        harmonic += 1
    alias = max(energy - harmonics, 1e-12)
    return 10.0 * math.log10(alias / fundamental)


def loop_area(oversample, pre_gain, cycles=4, frames=9600, level=20000,
              **options):
    """Normalised area the input/output trajectory encloses, by shoelace.

    A static table's trajectory retraces itself, so it encloses exactly
    nothing -- which is what makes this the measurement that separates a
    curve with memory from one without.
    """
    values = array("h")
    period = frames // cycles
    for index in range(frames):
        phase = (index % period) / float(period)
        triangle = 4.0 * phase - 1.0 if phase < 0.5 else 3.0 - 4.0 * phase
        sample = clamp15(int(round(level * triangle)))
        values.append(sample)
        values.append(sample)
    rendered = render(values, oversample=oversample, pre_gain=pre_gain,
                      **options)
    start = frames - period
    x = [float(values[index * 2]) for index in range(start, frames)]
    y = [float(rendered[index * 2]) for index in range(start, frames)]
    area = 0.0
    for index in range(len(x)):
        nxt = (index + 1) % len(x)
        area += x[index] * y[nxt] - x[nxt] * y[index]
    area = abs(area) * 0.5
    span_x = max(x) - min(x)
    span_y = max(y) - min(y)
    if span_x <= 0.0 or span_y <= 0.0:
        return 0.0
    return area / (span_x * span_y)


class SurfaceTest(unittest.TestCase):
    def test_it_presents_itself_as_a_stereo_sample(self):
        node = audioshaper.Waveshaper(sample_rate=SAMPLE_RATE, curve=CUBIC)
        self.assertEqual(node.sample_rate, SAMPLE_RATE)
        self.assertEqual(node.channel_count, 2)
        self.assertEqual(node.bits_per_sample, 16)
        self.assertTrue(node.samples_signed)
        self.assertEqual(node.oversample, 4)

    def test_a_curve_is_required(self):
        with self.assertRaises(ValueError):
            audioshaper.Waveshaper(sample_rate=SAMPLE_RATE)

    def test_oversample_is_a_power_of_two_up_to_eight(self):
        for factor in (0, 3, 5, 16):
            with self.assertRaises(ValueError):
                audioshaper.Waveshaper(sample_rate=SAMPLE_RATE, curve=CUBIC,
                                       oversample=factor)

    def test_an_unknown_option_is_refused(self):
        with self.assertRaises(TypeError):
            audioshaper.Waveshaper(sample_rate=SAMPLE_RATE, curve=CUBIC,
                                   drive=3.0)

    def test_a_starved_chain_gets_silence_not_a_short_block(self):
        node = audioshaper.Waveshaper(sample_rate=SAMPLE_RATE, curve=CUBIC)
        result, block = audiocore.get_buffer(node)
        self.assertEqual(result, audiocore.GET_BUFFER_MORE_DATA)
        self.assertEqual(len(bytes(block)), audioshaper.FRAMES * 4)
        self.assertEqual(sum(bytes(block)), 0)

    def test_mix_zero_is_the_untouched_input(self):
        values = sine(37, 2048, 12000)
        rendered = render(values, oversample=8, pre_gain=40.0, mix=0.0)
        self.assertEqual(list(rendered), list(values))


class AliasFloorTest(unittest.TestCase):
    """Oversampling lowers the alias floor, and the base rate is the control.

    Everything here is one measurement at four settings of one argument. If
    the interpolate/shape/decimate path were not doing what it says, x4 and
    x8 would read the same as x1, which is exactly what the palette's
    audiofilters.Distortion does read.
    """

    def test_the_floor_falls_as_the_factor_rises(self):
        floors = [alias_floor_db(factor, pre_gain=6.0, post_gain=0.4)
                  for factor in (1, 2, 4, 8)]
        self.assertLess(floors[1], floors[0] - 10.0,
                        "x2 bought less than 10 dB over x1: %r" % (floors,))
        self.assertLess(floors[2], floors[0] - 15.0,
                        "x4 bought less than 15 dB over x1: %r" % (floors,))
        # x8 is where this curve's floor bottoms out -- what is left is the
        # shaping's own in-band aliasing and the int16 output's quantisation,
        # neither of which another doubling touches. It must not get worse.
        self.assertLess(floors[3], floors[2] + 0.5,
                        "x8 was worse than x4: %r" % (floors,))


class HysteresisTest(unittest.TestCase):
    """The option encloses an area, the area grows with drive, and off is off.

    Saturation TP3 asks for a loop that *grows*: at maximum drive the engaged
    trajectory's enclosed area has to beat the disengaged control by at least
    6 dB, and that excess has to grow monotonically over three drive
    settings. A static table meets TP3's disconfirmation condition a priori --
    its trajectory retraces itself and encloses exactly nothing -- so the
    control here is not a formality, it is the thing the option exists to
    stop being true.
    """

    def test_a_static_table_encloses_nothing(self):
        self.assertEqual(loop_area(1, 4.0), 0.0)

    def test_the_planted_fault_collapses_the_loop(self):
        """Width zero is the fault: the operator runs, and does nothing.

        This is the run that has to go red for the growth test above to mean
        anything -- an area that is there whatever the option says would be
        measuring the filters, not the operator.
        """
        self.assertEqual(loop_area(1, 4.0, hysteresis=0.9,
                                   hysteresis_width=0.0), 0.0)

    def test_the_area_grows_with_the_knob(self):
        """Three settings of `hysteresis`, one drive: the mechanism itself.

        TP3's own three drive settings are the class's to sweep -- a drive
        macro maps to these two floats (the Phase 0 sketch says so in as many
        words) -- and what has to be true of the node underneath is that the
        knob the macro turns is monotone and clears the control by 6 dB.
        """
        control = loop_area(4, 4.0, post_gain=0.5)
        areas = [loop_area(4, 4.0, hysteresis=amount, hysteresis_width=0.12,
                           post_gain=0.5)
                 for amount in (0.3, 0.6, 0.9)]
        for previous, following in zip(areas, areas[1:]):
            self.assertGreater(following, previous,
                               "area did not grow: %r" % (areas,))
        excess = 20.0 * math.log10(areas[-1] / control)
        self.assertGreater(excess, 6.0,
                           "excess over the control is under 6 dB: %.2f"
                           % (excess,))

    def test_drive_does_not_smear_the_loop(self):
        """The half-width is in input units, so the drive knob leaves it be.

        Without the |pre_gain| factor config_finish applies, the same
        absolute half-width would cover less of the input's swing at every
        turn of the drive knob and the enclosed area would *fall* as drive
        rose -- which is exactly the direction audioecho.FeedbackDelay and
        audiodynamics.Dynamics fail TP3 in. Measured without it: 0.163,
        0.084, 0.045 over pre_gain 1, 2, 4.
        """
        areas = [loop_area(4, drive, hysteresis=0.8, hysteresis_width=0.12,
                           post_gain=0.5 / drive)
                 for drive in (1.0, 2.0, 4.0)]
        # The x4 half-bands have a group delay of their own, so even a static
        # table encloses a little area here. It has to be small beside the
        # operator's, or this test would pass with the operator torn out.
        control = loop_area(4, 1.0, post_gain=0.5)
        self.assertGreater(areas[0], control * 4.0,
                           "the loop is the filters, not the operator: "
                           "%r against %r" % (areas, control))
        for area in areas[1:]:
            self.assertGreater(area, areas[0] * 0.75,
                               "drive shrank the loop: %r" % (areas,))
            self.assertLess(area, areas[0] * 1.35,
                            "drive grew the loop by itself: %r" % (areas,))


if __name__ == "__main__":
    unittest.main()
