"""Modulation effects. LFOs tick at the engine's block rate (about 187 Hz
at 48 kHz), which is ample for musical sweep rates - and not nearly enough
for a ring modulator, which is why `RingMod` is built on a stream instead."""

import math
from array import array

import audiocore
import audiodelays
import audiofilters
import audiomath
import audiomixer
import synthio

from . import _core


class Chorus(_core.Effect):
    def __init__(self, source, rate=0.6, depth_ms=6.0, voices=3, mix=0.5):
        self.motion = synthio.LFO(rate=rate, scale=depth_ms * 0.5,
                                  offset=depth_ms + 8.0)
        self.node = audiodelays.Chorus(
            max_delay_ms=int(depth_ms * 2 + 30), delay_ms=self.motion,
            voices=voices, mix=mix, **_core.pcm())
        self.node.play(source)
        self.output = self.node


class Flanger(_core.Effect):
    """A very short modulated delay with feedback and doppler - the real
    swept comb, jet engine included."""

    def __init__(self, source, rate=0.25, depth_ms=2.5, feedback=0.6,
                 mix=0.5):
        self.motion = synthio.LFO(rate=rate, scale=depth_ms,
                                  offset=depth_ms + 1.0)
        self.node = audiodelays.Echo(
            max_delay_ms=int(depth_ms * 2 + 20), delay_ms=self.motion,
            decay=feedback, mix=mix, freq_shift=True, **_core.pcm())
        self.node.play(source)
        self.output = self.node


class Phaser(_core.Effect):
    def __init__(self, source, rate=0.4, depth=0.7, stages=6,
                 feedback=0.5, mix=0.6):
        self.sweep = synthio.LFO(rate=rate, scale=900.0 * depth,
                                 offset=1100.0)
        self.node = audiofilters.Phaser(
            frequency=self.sweep, feedback=feedback, stages=stages,
            mix=mix, **_core.pcm())
        self.node.play(source)
        self.output = self.node


class _MixerMod(_core.Effect):
    """One mixer voice whose level/panning carries the modulation."""

    def __init__(self, source):
        self.mixer = audiomixer.Mixer(voice_count=1, **_core.pcm(1024))
        self.mixer.voice[0].play(source)
        self.voice = self.mixer.voice[0]
        self.output = self.mixer


class Tremolo(_MixerMod):
    def __init__(self, source, rate=5.0, depth=0.6):
        _MixerMod.__init__(self, source)
        self.lfo = synthio.LFO(rate=rate, scale=depth * 0.5,
                               offset=1.0 - depth * 0.5)
        self.voice.level = self.lfo


class AutoPan(_MixerMod):
    def __init__(self, source, rate=0.8, depth=1.0):
        _MixerMod.__init__(self, source)
        self.lfo = synthio.LFO(rate=rate, scale=depth)
        self.voice.level = 1.0
        self.voice.panning = self.lfo


class Vibrato(_core.Effect):
    def __init__(self, source, rate=5.5, depth_semitones=0.4):
        self.lfo = synthio.LFO(rate=rate, scale=depth_semitones)
        self.node = audiodelays.PitchShift(
            semitones=self.lfo, mix=1.0, window=1024, **_core.pcm())
        self.node.play(source)
        self.output = self.node


class Rotary(_core.Effect):
    """Leslie-flavoured: vibrato for the doppler, tremolo for the beam
    sweeping past, auto-pan for the cabinet spin, at a shared speed."""

    def __init__(self, source, speed="slow"):
        rate = 0.8 if speed == "slow" else 6.5
        self.vibrato = Vibrato(source, rate=rate, depth_semitones=0.25)
        self.tremolo = Tremolo(self.vibrato.output, rate=rate, depth=0.35)
        self.mixer = self.tremolo.mixer
        self.pan_lfo = synthio.LFO(rate=rate, scale=0.7, phase_offset=0.25)
        self.tremolo.voice.panning = self.pan_lfo
        self.output = self.tremolo.output


#: Frames a carrier table aims for. It holds a whole number of cycles, so the
#: length lands near this rather than on it; the closest it can get is what
#: sets the frequency error, which is under 0.03% anywhere in the range. At
#: 48 kHz that is 8 KB of table, which is the reason this is 2048 and not
#: 16384 - a board with 264 KB of RAM has to be able to afford one.
_CARRIER_FRAMES = 2048


def _carrier(frequency, depth, sample_rate):
    """One sine as a looping stereo table, at `depth` between a constant and
    full swing.

    The table holds a *whole number of cycles*, which is what makes pulling it
    over and over a seamless loop: `audiomath.Multiply` hands its modulator
    back to the start when it runs out, so a partial cycle would step the
    phase once per table and buzz at the table rate.

    `depth` folds in here rather than being a second multiply: at 1.0 the
    table swings through zero and the result is ring modulation, at 0.5 it
    just touches zero and the result is textbook amplitude modulation, and at
    0.0 it is a constant and the effect is a bypass.
    """
    cycles = max(1, int(round(frequency * _CARRIER_FRAMES / sample_rate)))
    length = max(2, int(round(cycles * sample_rate / frequency)))
    values = array("h")
    for frame in range(length):
        shape = (1.0 - depth) + depth * math.sin(
            2.0 * math.pi * cycles * frame / length)
        sample = int(32767.0 * shape)
        values.append(sample)
        values.append(sample)
    return audiocore.RawSample(values, sample_rate=sample_rate,
                               channel_count=2)


class RingMod(_core.Effect):
    """The source multiplied by a sine: every partial replaced by its sum and
    difference with the carrier, and neither original kept.

    That is what makes it sound the way it does - the output is inharmonic
    unless the carrier happens to be related to the note, so it turns pitched
    material into metal and speech into a Dalek. `depth` walks it back toward
    plain amplitude modulation, which keeps the original and adds sidebands
    around it.

    This is the one effect here that could not be built before `audiomath`.
    An LFO-driven level updates once per block, about 187 Hz at 48 kHz, and a
    ring modulator wants hundreds - `Tremolo` is the same idea inside that
    limit.
    """

    MACRO_LABELS = ("Frequency", "Depth", "Mix")
    MACRO_RANGES = ((20.0, 4000.0, "log"), (0.0, 1.0), (0.0, 1.0))
    PATCHES = {
        0: ("Init", (57, 127, 127)),
        1: ("Dalek", (10, 127, 127)),
        2: ("Clangour", (98, 127, 127)),
        # Below about 30 Hz the sidebands stop being heard as pitch and start
        # being heard as movement; at 0.6 depth the carrier no longer crosses
        # zero, so this is a tremolo faster than an LFO can run.
        3: ("Growl", (4, 76, 127)),
        4: ("Sideband Wash", (85, 127, 44)),
        5: ("Bell Strike", (118, 127, 89)),
    }

    def __init__(self, source, frequency=220.0, depth=1.0, mix=1.0,
                 patch=None):
        self.node = audiomath.Multiply(sample_rate=_core.sample_rate())
        self.node.play(source)
        self.output = self.node
        self._built = None
        self._init_macros((frequency, depth, mix), patch)

    def _apply_macro(self, index, position):
        if index == 2:
            self.node.set(mix=position)
            return
        # Frequency and depth are both baked into the table, so either one
        # rebuilds it - and the constructor sets both, which would otherwise
        # build the same table twice.
        frequency = self.macro(0)
        depth = self.macro(1)
        if self._built == (frequency, depth):
            return
        self._built = (frequency, depth)
        self.carrier = _carrier(frequency, depth, _core.sample_rate())
        self.node.modulate(self.carrier)

    def set_frequency(self, frequency):
        """Retune the carrier, in hertz."""
        self.set_macro(0, _core.macro_of(self.MACRO_RANGES[0], frequency))
