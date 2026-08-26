"""Delays. Echo's delay time is a block input, which is what makes the
tape variant wobble; MultiTapDelay provides the tap patterns."""

import audiodelays
import audiofilters
import audiomixer
import audioroute
import synthio

from . import _core


class DigitalDelay(_core.Effect):
    def __init__(self, source, time_ms=350.0, feedback=0.4, mix=0.3):
        self.node = audiodelays.Echo(
            max_delay_ms=int(time_ms) + 100, delay_ms=time_ms,
            decay=feedback, mix=mix, freq_shift=False, **_core.pcm())
        self.node.play(source)
        self.output = self.node

    def set_time(self, time_ms):
        self.node.delay_ms = time_ms

    def set_mix(self, mix):
        self.node.mix = mix


class SlapbackDelay(DigitalDelay):
    """One short, single repeat - the rockabilly vocal trick."""

    def __init__(self, source, time_ms=95.0, mix=0.4):
        DigitalDelay.__init__(self, source, time_ms=time_ms, feedback=0.0,
                              mix=mix)


class TapeDelay(_core.Effect):
    """Wow from a slow LFO on the delay time (with the doppler shift a
    moving tape head really has), and a darkening low-pass. The filter
    sits after the delay, so it darkens the whole wet+dry blend rather
    than each repeat progressively - the practical approximation."""

    def __init__(self, source, time_ms=320.0, feedback=0.45, mix=0.35,
                 wow=0.3, tone_hz=3800.0):
        self.wobble = synthio.LFO(rate=0.7, scale=2.5 * wow,
                                  offset=float(time_ms))
        self.echo = audiodelays.Echo(
            max_delay_ms=int(time_ms) + 100, delay_ms=self.wobble,
            decay=feedback, mix=mix, freq_shift=True, **_core.pcm())
        self.echo.play(source)
        self.tone = audiofilters.Filter(
            filter=synthio.Biquad(synthio.FilterMode.LOW_PASS,
                                  _core.filter_hz(tone_hz), Q=0.707),
            **_core.pcm())
        self.tone.play(self.echo)
        self.output = self.tone


class PingPongDelay(_core.Effect):
    """Left repeats at the base time, right at double it, panned hard to
    opposite sides - the bouncing pattern without true cross-feedback."""

    def __init__(self, source, time_ms=280.0, feedback=0.35, mix=0.35):
        split = audioroute.Splitter(source, taps=3)
        self.left = audiodelays.Echo(
            max_delay_ms=int(time_ms) + 100, delay_ms=time_ms,
            decay=feedback, mix=1.0, freq_shift=False, **_core.pcm())
        self.left.play(split.tap(0))
        self.right = audiodelays.Echo(
            max_delay_ms=int(time_ms) * 2 + 100, delay_ms=time_ms * 2.0,
            decay=feedback, mix=1.0, freq_shift=False, **_core.pcm())
        self.right.play(split.tap(1))
        self.mixer = audiomixer.Mixer(voice_count=3, **_core.pcm(1024))
        self.mixer.voice[0].play(split.tap(2))
        self.mixer.voice[0].level = 1.0
        self.mixer.voice[1].play(self.left)
        self.mixer.voice[1].level = mix
        self.mixer.voice[1].panning = -0.9
        self.mixer.voice[2].play(self.right)
        self.mixer.voice[2].level = mix
        self.mixer.voice[2].panning = 0.9
        self.splitter = split
        self.output = self.mixer


class MultiTapDelay(_core.Effect):
    """taps: (position 0..1 of time_ms, level) pairs."""

    def __init__(self, source, time_ms=500.0,
                 taps=((0.25, 0.8), (0.5, 0.6), (0.75, 0.4), (1.0, 0.3)),
                 mix=0.4):
        self.node = audiodelays.MultiTapDelay(
            max_delay_ms=int(time_ms) + 100, delay_ms=time_ms,
            decay=0.0, mix=mix, taps=tuple(taps), **_core.pcm())
        self.node.play(source)
        self.output = self.node
