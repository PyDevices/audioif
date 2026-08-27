"""Pitch and stereo-field manipulation.

Pitch correction (Auto-Tune-style) is deliberately absent: it needs
pitch detection, which the DSP palette does not provide.
"""

VENDOR = "PyDevices"

import audiodelays
import audiomixer
import audioroute

from . import _core


class PitchShifter(_core.Effect):

    NAME = 'Pitch Shifter'
    CATEGORIES = ('Pitch Shift',)
    VERSION = '0.0.1'
    def __init__(self, source, semitones=0.0, mix=1.0):
        self.node = audiodelays.PitchShift(
            semitones=semitones, mix=mix, window=2048, **_core.pcm())
        self.node.play(source)
        self.output = self.node

    def set_semitones(self, semitones):
        self.node.semitones = semitones


class Harmonizer(_core.Effect):
    """Dry plus up to three fixed-interval shifted copies."""

    NAME = 'Harmonizer'
    CATEGORIES = ('Pitch Shift',)
    VERSION = '0.0.1'

    def __init__(self, source, intervals=(4.0, 7.0), level=0.5):
        intervals = tuple(intervals)[:_core.SPLITTER_TAPS - 1]
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
    """The dry signal plus octaves above and below it, one or two of each.

    Each level is how loud that octave sits under the dry; a level of zero
    builds no branch at all, so the common one-octave-down setting costs
    one shifter rather than four. A Splitter fans out to at most four taps,
    which leaves room for the dry plus any three octaves - ask for all four
    and it says so rather than dropping one quietly.
    """

    NAME = 'Octaver'
    CATEGORIES = ('Pitch Shift',)
    VERSION = '0.0.1'

    #: (attribute, semitones, window) per octave, in the order they mix.
    #: Shorter windows track faster, which matters more the further up the
    #: shift goes and not at all going down.
    OCTAVES = (("down", -12.0, 2048), ("down2", -24.0, 2048),
               ("up", 12.0, 1024), ("up2", 24.0, 512))

    def __init__(self, source, down=0.5, up=0.0, down2=0.0, up2=0.0):
        levels = {"down": down, "up": up, "down2": down2, "up2": up2}
        wanted = [octave for octave in self.OCTAVES if levels[octave[0]] > 0.0]
        if len(wanted) > _core.SPLITTER_TAPS - 1:
            raise ValueError(
                "an Octaver can carry %d octaves beside the dry signal, and "
                "%d were asked for"
                % (_core.SPLITTER_TAPS - 1, len(wanted)))
        for name, _, _ in self.OCTAVES:
            setattr(self, name, None)
        split = audioroute.Splitter(source, taps=len(wanted) + 1)
        self.mixer = audiomixer.Mixer(voice_count=len(wanted) + 1,
                                      **_core.pcm(1024))
        self.mixer.voice[0].play(split.tap(0))
        self.mixer.voice[0].level = 1.0
        for index, (name, semitones, window) in enumerate(wanted):
            shifter = audiodelays.PitchShift(
                semitones=semitones, mix=1.0, window=window, **_core.pcm())
            shifter.play(split.tap(index + 1))
            setattr(self, name, shifter)
            self.mixer.voice[index + 1].play(shifter)
            self.mixer.voice[index + 1].level = levels[name]
        self.splitter = split
        self.output = self.mixer


class StereoWidener(_core.Effect):
    """Haas-effect width: the dry center plus a short-delayed copy pushed
    to one side and its source-panned opposite."""

    NAME = 'Stereo Widener'
    CATEGORIES = ('Spatial',)
    VERSION = '0.0.1'

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
