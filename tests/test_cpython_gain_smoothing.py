"""`Dynamics(gain_smooth_ms=…)`: a one-pole on the computed gain (audioif#61).

Why it exists. With a short release the per-sample gain follows the waveform on
low-frequency material, so the node intermodulates rather than compresses.
Measured at 10 dB of gain reduction on a 50 Hz tone, five of
`audioeffects.Compressor`'s fourteen shipped patches were over their 0.5 % THD
bar — the constructor's own defaults among them — while at 1 kHz only the patch
that is meant to be dirty was. Nothing downstream of `Dynamics` can remove that
ripple without also removing the compression.

Two properties are load-bearing and each is the other's fault:

* **Off is the default and off is an identity.** Everything measured against
  this node before the option existed has to stay where it is, so the first
  test renders with and without the keyword and requires the bytes to be
  equal. If that ever fails, every golden in the repository is suspect.
* **On actually reduces the ripple**, monotonically in the setting. An option
  that changed nothing would pass the first test perfectly.

The material matters and is why the numbers here are trustworthy: 48000/50 is
960 samples exactly, so a buffer of whole cycles loops seamlessly. The first
draft of this measurement used 4096 frames, whose wrap discontinuity read as
1360 % THD on the *bare source* — the control that caught it.
"""

from array import array
import math
import unittest

import audiocore
import audiodynamics

RATE = 48000
CHANNELS = 2
TONE_HZ = 50.0
SETTINGS = {"threshold_db": -30.0, "ratio": 6.0, "knee_db": 0.0,
            "attack_ms": 1.0, "release_ms": 10.0}


def tone(hz=TONE_HZ, dbfs=-6.0, cycles=25):
    period = RATE / hz
    assert period == int(period), "choose a frequency that divides the rate"
    amplitude = 32767.0 * (10.0 ** (dbfs / 20.0))
    values = array("h")
    for frame in range(int(period) * cycles):
        sample = int(amplitude * math.sin(2.0 * math.pi * hz * frame / RATE))
        values.append(sample)
        values.append(sample)
    return audiocore.RawSample(values, sample_rate=RATE,
                               channel_count=CHANNELS)


def render(blocks=40, hz=TONE_HZ, **extra):
    node = audiodynamics.Dynamics(audiodynamics.DYN_COMPRESS, sample_rate=RATE,
                                  channel_count=CHANNELS)
    node.set(**SETTINGS)
    if extra:
        node.set(**extra)
    node.play(tone(hz))
    return b"".join(bytes(audiocore.get_buffer(node)[1])
                    for _ in range(blocks))


def left_channel(pcm):
    out = []
    for index in range(0, len(pcm) - 3, 4):
        value = pcm[index] | (pcm[index + 1] << 8)
        out.append(value - 65536 if value >= 32768 else value)
    return out


def thd_percent(samples, hz=TONE_HZ):
    """Total harmonic distortion, harmonics 2..8, on a Hann window."""
    count = len(samples)
    window = [0.5 - 0.5 * math.cos(2.0 * math.pi * i / (count - 1))
              for i in range(count)]
    shaped = [samples[i] * window[i] for i in range(count)]

    def magnitude(frequency):
        real = sum(shaped[i] * math.cos(2.0 * math.pi * frequency * i / RATE)
                   for i in range(count))
        imaginary = sum(shaped[i] * math.sin(2.0 * math.pi * frequency * i
                                             / RATE) for i in range(count))
        return math.hypot(real, imaginary)

    fundamental = magnitude(hz)
    if not fundamental:
        return 0.0
    harmonics = math.sqrt(sum(magnitude(hz * k) ** 2 for k in range(2, 9)))
    return 100.0 * harmonics / fundamental


def ripple(hz=TONE_HZ, **extra):
    """THD of the second half of the render, so the attack is excluded.

    `hz` is passed to **both** the source and the analysis. Not doing that was
    the second bug in this file's first draft: a 1 kHz render measured for
    50 Hz harmonics read 300 %, which looks like a catastrophic node and is a
    catastrophic test.
    """
    samples = left_channel(render(hz=hz, **extra))
    return thd_percent(samples[len(samples) // 2:], hz)


class TheDefaultIsAnIdentity(unittest.TestCase):

    def test_the_material_itself_is_clean(self):
        """The control the first draft of this file lacked. Without it, a
        distorted source would make every reading below meaningless."""
        source = tone()
        pcm = b"".join(bytes(audiocore.get_buffer(source)[1])
                       for _ in range(40))
        samples = left_channel(pcm)
        self.assertLess(thd_percent(samples[len(samples) // 2:]), 0.01)

    def test_omitting_the_keyword_and_passing_zero_render_the_same_bytes(self):
        self.assertEqual(render(), render(gain_smooth_ms=0.0))

    def test_a_negative_time_is_off_too(self):
        self.assertEqual(render(), render(gain_smooth_ms=-5.0))


class TheSmootherReducesTheRipple(unittest.TestCase):

    def test_a_short_release_on_a_low_tone_ripples_without_it(self):
        """The defect, restated as a number so the test below has a baseline
        it cannot silently lose."""
        self.assertGreater(ripple(), 5.0)

    def test_it_falls_monotonically_with_the_setting(self):
        readings = [ripple(gain_smooth_ms=ms)
                    for ms in (0.0, 1.0, 10.0, 30.0)]
        for earlier, later in zip(readings, readings[1:]):
            self.assertLess(later, earlier,
                            "not monotonic: %s" % (readings,))
        # And it reaches the bar the class's trait sets, which is the point.
        self.assertLess(readings[-1], 0.5)

    def test_it_helps_at_1_kHz_as_well_but_matters_less(self):
        """The ripple is a low-frequency problem: at 1 kHz the un-smoothed
        node is already inside the bar, so the option is an improvement rather
        than a rescue. Stated so nobody reads the 50 Hz figures as general."""
        without = ripple(hz=1000.0)
        with_it = ripple(hz=1000.0, gain_smooth_ms=10.0)
        self.assertLess(without, 0.5)
        self.assertLess(with_it, without)


if __name__ == "__main__":
    unittest.main()
