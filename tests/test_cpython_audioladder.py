"""audioladder: the three things the parity gate cannot see.

`verify_dsp.py` pins what this node *renders*, byte for byte, on every
interpreter. What it cannot say is whether those bytes are a ladder. The
golden would be just as green if the loop had been wired backwards, so the
traits the module exists for are asserted here, in numbers rather than in
hashes: that the loop sustains at a feedback of 4 and not before, that the
tone it sustains sits at the cutoff and stops growing, that the curve
bounding it is odd, and that how hard the input hits it changes what comes
out.

No numpy: this runs wherever the wheel is installed, and the wheel's numpy is
an extra.
"""

import math
import unittest
from array import array

import audiocore
import audioladder

RATE = 12000
BLOCK = 256


def impulse(frames, level=30000):
    values = array("h", [0] * (frames * 2))
    values[0] = values[1] = level
    return audiocore.RawSample(values, sample_rate=RATE, channel_count=2)


def tone(frames, hz, level):
    values = array("h", [0] * (frames * 2))
    for frame in range(frames):
        value = int(level * 32767 *
                    math.sin(2 * math.pi * hz * frame / RATE))
        values[2 * frame] = values[2 * frame + 1] = value
    return values


def render(node, source, frames):
    node.play(source)
    left = []
    for _ in range(frames // BLOCK):
        data = bytes(audiocore.get_buffer(node)[1])
        block = array("h")
        block.frombytes(data)
        left.extend(block[0::2])
    return left


def peak(samples):
    return max(abs(value) for value in samples) / 32768.0


def amplitude_at(samples, hz):
    """One bin of a Hann-windowed DFT, by hand."""
    count = len(samples)
    real = imaginary = 0.0
    weight = 0.0
    for index, value in enumerate(samples):
        window = 0.5 - 0.5 * math.cos(2 * math.pi * index / count)
        weight += window
        angle = 2 * math.pi * hz * index / RATE
        real += value * window * math.cos(angle)
        imaginary -= value * window * math.sin(angle)
    return 2.0 * math.hypot(real, imaginary) / weight / 32768.0


def decibels(value, reference):
    return 20 * math.log10(max(value, 1e-15) / max(reference, 1e-15))


def crossing_rate(samples, seconds):
    crossings = sum(1 for index in range(1, len(samples))
                    if (samples[index - 1] < 0) != (samples[index] < 0))
    return crossings / 2.0 / seconds


def envelope(resonance, cutoff=600.0):
    """Peak over the second half-second after an impulse, and over the
    fourth: decaying, holding, or gone."""
    node = audioladder.Ladder(sample_rate=RATE, cutoff_hz=cutoff,
                              resonance=resonance)
    samples = render(node, impulse(RATE * 2), RATE * 2)
    return (peak(samples[RATE // 2:RATE]),
            peak(samples[3 * RATE // 2:RATE * 2]))


class SelfOscillationTest(unittest.TestCase):
    """The trait a linear filter cannot have at any setting."""

    def test_it_does_not_sustain_below_a_feedback_of_four(self):
        # Not "is silent": at 3.99 the ring is very long, which is what a
        # filter approaching its threshold should do. What is asserted is
        # that it is on its way down.
        for resonance in (3.5, 3.9, 3.95, 3.99):
            early, late = envelope(resonance)
            self.assertTrue(late == 0.0 or decibels(late, early) < -6.0,
                            "resonance %.2f held: %g -> %g"
                            % (resonance, early, late))

    def test_it_sustains_from_a_feedback_of_four(self):
        # At exactly 4 the loop is marginal - the pole pair sits on the unit
        # circle and float rounding decides the last fraction of a decibel -
        # so what is asserted there is that it is still ringing two seconds
        # after the impulse, with nothing driving it. A hair above, it holds
        # its level, because the saturator inside the loop is what sets it.
        early, late = envelope(4.0)
        self.assertGreater(late, 1e-3, "at 4 it fell silent: %g" % late)
        for resonance in (4.05, 4.2):
            early, late = envelope(resonance)
            self.assertGreater(late, 0.05,
                               "resonance %.2f fell silent" % resonance)
            self.assertLess(abs(decibels(late, early)), 1.0,
                            "resonance %.2f drifted: %g -> %g"
                            % (resonance, early, late))

    def test_the_tone_it_sustains_sits_at_the_cutoff(self):
        for cutoff in (300.0, 600.0, 1500.0):
            node = audioladder.Ladder(sample_rate=RATE, cutoff_hz=cutoff,
                                      resonance=4.2)
            tail = render(node, impulse(RATE * 2), RATE * 2)[RATE:]
            measured = crossing_rate(tail, len(tail) / RATE)
            self.assertAlmostEqual(measured / cutoff, 1.0, delta=0.02,
                                   msg="cutoff %.0f gave %.1f Hz"
                                       % (cutoff, measured))

    def test_the_nonlinearity_bounds_it(self):
        node = audioladder.Ladder(sample_rate=RATE, cutoff_hz=600.0,
                                  resonance=4.2)
        samples = render(node, impulse(RATE * 3), RATE * 3)
        windows = [peak(samples[start:start + RATE // 4])
                   for start in range(RATE, len(samples) - RATE // 4,
                                      RATE // 4)]
        self.assertLess(abs(decibels(max(windows), min(windows))), 1.0)

    def test_clear_stops_it(self):
        node = audioladder.Ladder(sample_rate=RATE, cutoff_hz=600.0,
                                  resonance=4.2)
        render(node, impulse(RATE), RATE)
        node.clear()
        node.stop()
        after = bytes(audiocore.get_buffer(node)[1])
        self.assertEqual(after, bytes(len(after)))


class NonlinearityTest(unittest.TestCase):
    def test_the_curve_in_the_loop_is_odd(self):
        # Well off the int16 rails, where the only asymmetry left is two's
        # complement's own (+32767 against -32768).
        rendered = []
        for sign in (1, -1):
            values = tone(4096, 400.0, 0.3)
            if sign < 0:
                values = array("h", [-value for value in values])
            source = audiocore.RawSample(values, sample_rate=RATE,
                                         channel_count=2)
            node = audioladder.Ladder(sample_rate=RATE, cutoff_hz=700.0,
                                      resonance=3.9, drive=2.0)
            rendered.append(render(node, source, 4096))
        self.assertLess(peak(rendered[0]), 0.9)
        self.assertEqual(rendered[0], [-value for value in rendered[1]])

    def test_drive_raises_the_third_harmonic(self):
        ratios = []
        for drive_db in (0.0, 8.0, 16.0, 24.0):
            source = audiocore.RawSample(tone(RATE, 150.0, 0.5),
                                         sample_rate=RATE, channel_count=2)
            node = audioladder.Ladder(sample_rate=RATE, cutoff_hz=600.0,
                                      resonance=3.9,
                                      drive=10 ** (drive_db / 20))
            body = render(node, source, RATE)[RATE // 4:]
            ratios.append(decibels(amplitude_at(body, 450.0),
                                   amplitude_at(body, 150.0)))
        self.assertEqual(ratios, sorted(ratios), "h3/h1 did not rise: %s"
                         % (ratios,))
        self.assertGreater(ratios[-1] - ratios[0], 10.0)


class SurfaceTest(unittest.TestCase):
    def test_mix_zero_is_a_wire(self):
        values = tone(2048, 350.0, 0.7)
        source = audiocore.RawSample(values, sample_rate=RATE,
                                     channel_count=2)
        node = audioladder.Ladder(sample_rate=RATE, cutoff_hz=200.0,
                                  resonance=4.0, drive=8.0, mix=0.0)
        node.play(source)
        rendered = b"".join(bytes(audiocore.get_buffer(node)[1])
                            for _ in range(2048 // BLOCK))
        self.assertEqual(rendered, bytes(memoryview(values).cast("B")))

    def test_it_presents_itself_as_a_stereo_sample(self):
        node = audioladder.Ladder(sample_rate=RATE)
        self.assertEqual(node.sample_rate, RATE)
        self.assertEqual(node.channel_count, 2)
        self.assertEqual(node.bits_per_sample, 16)
        self.assertTrue(node.samples_signed)

    def test_a_mono_ladder_hands_back_mono_blocks(self):
        values = array("h", [(index * 37) % 2001 - 1000
                             for index in range(1024)])
        source = audiocore.RawSample(values, sample_rate=RATE,
                                     channel_count=1)
        node = audioladder.Ladder(sample_rate=RATE, channel_count=1,
                                  cutoff_hz=800.0, resonance=3.0)
        node.play(source)
        data = bytes(audiocore.get_buffer(node)[1])
        self.assertEqual(len(data), audioladder.FRAMES * 2)
        self.assertNotEqual(data, bytes(len(data)))

    def test_a_starved_chain_gets_silence_not_a_short_block(self):
        node = audioladder.Ladder(sample_rate=RATE, resonance=4.2)
        for _ in range(2):
            data = bytes(audiocore.get_buffer(node)[1])
            self.assertEqual(len(data), audioladder.FRAMES * 4)
            self.assertEqual(data, bytes(len(data)))

    def test_it_refuses_what_it_cannot_do(self):
        with self.assertRaises(ValueError):
            audioladder.Ladder(sample_rate=RATE, channel_count=3)
        with self.assertRaises(TypeError):
            audioladder.Ladder(sample_rate=RATE, cutoff=600.0)
        node = audioladder.Ladder(sample_rate=RATE)
        with self.assertRaises(TypeError):
            node.set(resonanc=4.0)

    def test_options_clamp_rather_than_raise(self):
        node = audioladder.Ladder(sample_rate=RATE, cutoff_hz=1e6,
                                  resonance=99.0, drive=1e6, poles=9,
                                  passband_comp=4.0, oversample=5, mix=5.0)
        node.play(audiocore.RawSample(tone(1024, 300.0, 0.5),
                                      sample_rate=RATE, channel_count=2))
        data = bytes(audiocore.get_buffer(node)[1])
        self.assertEqual(len(data), audioladder.FRAMES * 4)


if __name__ == "__main__":
    unittest.main()
