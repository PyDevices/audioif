"""Drive, distortion, and saturation over the engine's Distortion node
(CLIP, OVERDRIVE, LOFI, WAVESHAPE modes)."""

import audiofilters
import audiomixer
import audioroute
import synthio

from . import _core

_DM = audiofilters.DistortionMode


class Overdrive(_core.Effect):
    """Soft clipping with a tone control - tube breakup territory."""

    def __init__(self, source, drive=0.4, tone_hz=4500.0, mix=1.0):
        self.node = audiofilters.Distortion(
            drive=drive, mode=_DM.OVERDRIVE, soft_clip=True,
            post_gain=-3.0, mix=mix, **_core.pcm())
        self.node.play(source)
        self.tone = audiofilters.Filter(
            filter=synthio.Biquad(synthio.FilterMode.LOW_PASS,
                                  _core.filter_hz(tone_hz), Q=0.707),
            **_core.pcm())
        self.tone.play(self.node)
        self.output = self.tone


class Distortion(_core.Effect):
    """Hard clipping."""

    def __init__(self, source, drive=0.7, mix=1.0):
        self.node = audiofilters.Distortion(
            drive=drive, mode=_DM.CLIP, soft_clip=False,
            pre_gain=6.0, post_gain=-6.0, mix=mix, **_core.pcm())
        self.node.play(source)
        self.output = self.node


class Fuzz(_core.Effect):
    """Everything into the ceiling: the waveform leaves as a square."""

    def __init__(self, source, drive=0.95, mix=1.0):
        self.node = audiofilters.Distortion(
            drive=drive, mode=_DM.CLIP, soft_clip=False,
            pre_gain=18.0, post_gain=-9.0, mix=mix, **_core.pcm())
        self.node.play(source)
        self.output = self.node


class Saturation(_core.Effect):
    """Subtle harmonic thickening: soft clip blended mostly dry."""

    def __init__(self, source, amount=0.25):
        self.node = audiofilters.Distortion(
            drive=0.35, mode=_DM.OVERDRIVE, soft_clip=True,
            mix=amount, **_core.pcm())
        self.node.play(source)
        self.output = self.node


class Bitcrusher(_core.Effect):
    def __init__(self, source, crush=0.6, mix=1.0):
        self.node = audiofilters.Distortion(
            drive=crush, mode=_DM.LOFI, mix=mix, **_core.pcm())
        self.node.play(source)
        self.output = self.node


class Exciter(_core.Effect):
    """New highs synthesized from the source: a high-passed branch is
    overdriven (generating harmonics) and blended back in under the dry."""

    def __init__(self, source, frequency=3000.0, amount=0.3):
        split = audioroute.Splitter(source, taps=2)
        self.highs = audiofilters.Filter(
            filter=synthio.Biquad(synthio.FilterMode.HIGH_PASS,
                                  _core.filter_hz(frequency), Q=0.707),
            **_core.pcm())
        self.highs.play(split.tap(1))
        self.harmonics = audiofilters.Distortion(
            drive=0.6, mode=_DM.OVERDRIVE, soft_clip=True, **_core.pcm())
        self.harmonics.play(self.highs)
        self.mixer = audiomixer.Mixer(voice_count=2, **_core.pcm(1024))
        self.mixer.voice[0].play(split.tap(0))
        self.mixer.voice[0].level = 1.0
        self.mixer.voice[1].play(self.harmonics)
        self.mixer.voice[1].level = amount
        self.splitter = split
        self.output = self.mixer
