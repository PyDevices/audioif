"""Pitch and stereo-field manipulation.

Pitch correction (Auto-Tune-style) is deliberately absent: it needs
pitch detection, which the DSP palette does not provide.
"""

import audiodelays
import audiomixer
import audioroute

from . import _core


class PitchShifter(_core.Effect):
    def __init__(self, source, semitones=0.0, mix=1.0):
        self.node = audiodelays.PitchShift(
            semitones=semitones, mix=mix, window=2048, **_core.pcm())
        self.node.play(source)
        self.output = self.node

    def set_semitones(self, semitones):
        self.node.semitones = semitones


class Harmonizer(_core.Effect):
    """Dry plus up to three fixed-interval shifted copies."""

    def __init__(self, source, intervals=(4.0, 7.0), level=0.5):
        intervals = tuple(intervals)[:3]
        split = audioroute.Splitter(source, taps=len(intervals) + 1)
        self.shifters = []
        self.mixer = audiomixer.Mixer(voice_count=len(intervals) + 1,
                                      **_core.pcm(1024))
        self.mixer.voice[0].play(split.tap(0))
        self.mixer.voice[0].level = 1.0
        for index, semitones in enumerate(intervals):
            shifter = audiodelays.PitchShift(
                semitones=semitones, mix=1.0, window=2048, **_core.pcm())
            shifter.play(split.tap(index + 1))
            self.shifters.append(shifter)
            self.mixer.voice[index + 1].play(shifter)
            self.mixer.voice[index + 1].level = level
        self.splitter = split
        self.output = self.mixer


class Octaver(_core.Effect):
    def __init__(self, source, down=0.5, up=0.0):
        split = audioroute.Splitter(source, taps=3)
        self.mixer = audiomixer.Mixer(voice_count=3, **_core.pcm(1024))
        self.mixer.voice[0].play(split.tap(0))
        self.mixer.voice[0].level = 1.0
        self.down = audiodelays.PitchShift(
            semitones=-12.0, mix=1.0, window=2048, **_core.pcm())
        self.down.play(split.tap(1))
        self.mixer.voice[1].play(self.down)
        self.mixer.voice[1].level = down
        self.up = audiodelays.PitchShift(
            semitones=12.0, mix=1.0, window=1024, **_core.pcm())
        self.up.play(split.tap(2))
        self.mixer.voice[2].play(self.up)
        self.mixer.voice[2].level = up
        self.splitter = split
        self.output = self.mixer


class StereoWidener(_core.Effect):
    """Haas-effect width: the dry center plus a short-delayed copy pushed
    to one side and its source-panned opposite."""

    def __init__(self, source, delay_ms=14.0, width=0.7):
        split = audioroute.Splitter(source, taps=2)
        self.side = audiodelays.Echo(
            max_delay_ms=int(delay_ms) + 20, delay_ms=delay_ms, decay=0.0,
            mix=1.0, freq_shift=False, **_core.pcm())
        self.side.play(split.tap(1))
        self.mixer = audiomixer.Mixer(voice_count=2, **_core.pcm(1024))
        self.mixer.voice[0].play(split.tap(0))
        self.mixer.voice[0].level = 1.0
        self.mixer.voice[0].panning = -0.3 * width
        self.mixer.voice[1].play(self.side)
        self.mixer.voice[1].level = 0.8
        self.mixer.voice[1].panning = 0.9 * width
        self.splitter = split
        self.output = self.mixer
