"""Modulation effects. LFOs tick at the engine's block rate (about 187 Hz
at 48 kHz), which is ample for musical sweep rates."""

import audiodelays
import audiofilters
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
