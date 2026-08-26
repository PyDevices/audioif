"""Equalizers and filters, built on Biquad chains inside
audiofilters.Filter. Biquad frequencies and Qs accept synthio blocks, so
every cutoff here can be swept smoothly from a macro via set_* methods.
"""

import audiodelays
import audiodynamics
import audiofilters
import audiomixer
import audioroute
import synthio

from . import _core

_FM = synthio.FilterMode


class ParametricEQ(_core.Effect):
    """bands: (frequency_hz, gain_db, q) bell sections, plus optional
    low_shelf/high_shelf as (frequency_hz, gain_db).

    Bells are built without the (broken-upstream) peaking biquad: cuts
    are notch sections blended to depth via the Filter's mix, boosts are
    band-passed branches summed back over the dry signal. At most three
    boost bands (the splitter has four taps); cuts are unlimited."""

    def __init__(self, source, bands=(), low_shelf=None, high_shelf=None):
        boosts = [b for b in bands if b[1] > 0.0]
        cuts = [b for b in bands if b[1] <= 0.0]
        if len(boosts) > 3:
            raise ValueError("at most 3 boost bands")

        chain = source
        self.mixer = None
        self.splitter = None
        if boosts:
            split = audioroute.Splitter(source, taps=len(boosts) + 1)
            self.mixer = audiomixer.Mixer(voice_count=len(boosts) + 1,
                                          **_core.pcm(1024))
            self.mixer.voice[0].play(split.tap(0))
            self.mixer.voice[0].level = 1.0
            self.branches = []
            for index, (frequency, gain_db, q) in enumerate(boosts):
                band = audiofilters.Filter(
                    filter=synthio.Biquad(_FM.BAND_PASS,
                                          _core.filter_hz(frequency), Q=q),
                    **_core.pcm())
                band.play(split.tap(index + 1))
                self.branches.append(band)
                self.mixer.voice[index + 1].play(band)
                self.mixer.voice[index + 1].level = min(
                    1.0, _core.db_to_gain(gain_db) - 1.0)
            self.splitter = split
            chain = self.mixer

        self.sections = []
        for frequency, gain_db, q in cuts:
            depth = 1.0 - _core.db_to_gain(gain_db)
            section = audiofilters.Filter(
                filter=synthio.Biquad(_FM.NOTCH,
                                      _core.filter_hz(frequency), Q=q),
                mix=depth, **_core.pcm())
            section.play(chain)
            self.sections.append(section)
            chain = section
        shelf_biquads = []
        if low_shelf is not None:
            shelf_biquads.append(synthio.Biquad(
                _FM.LOW_SHELF, _core.filter_hz(low_shelf[0]), Q=0.707,
                A=_core.db_to_amplitude(low_shelf[1])))
        if high_shelf is not None:
            shelf_biquads.append(synthio.Biquad(
                _FM.HIGH_SHELF, _core.filter_hz(high_shelf[0]), Q=0.707,
                A=_core.db_to_amplitude(high_shelf[1])))
        if shelf_biquads:
            shelf = audiofilters.Filter(filter=shelf_biquads, **_core.pcm())
            shelf.play(chain)
            self.sections.append(shelf)
            chain = shelf
        self.output = chain


ISO_BANDS = (31.5, 63.0, 125.0, 250.0, 500.0,
             1000.0, 2000.0, 4000.0, 8000.0, 16000.0)


class GraphicEQ(ParametricEQ):
    """Ten fixed ISO-centered bands; gains_db is one value per band.
    Up to three of them may be boosts."""

    def __init__(self, source, gains_db):
        ParametricEQ.__init__(self, source, bands=[
            (freq, gain, 1.4) for freq, gain in zip(ISO_BANDS, gains_db)
            if abs(gain) > 0.01])


class _SingleFilter(_core.Effect):
    MODE = None

    def __init__(self, source, frequency=1000.0, q=0.707, mix=1.0):
        self.frequency = synthio.Math(synthio.MathOperation.SUM,
                                      _core.filter_hz(frequency), 0.0, 0.0)
        self.biquad = synthio.Biquad(self.MODE, self.frequency, Q=q)
        self.node = audiofilters.Filter(filter=self.biquad, mix=mix,
                                        **_core.pcm())
        self.node.play(source)
        self.output = self.node

    def set_frequency(self, hz):
        self.frequency.a = _core.filter_hz(hz)


class LowPass(_SingleFilter):
    MODE = _FM.LOW_PASS


class HighPass(_SingleFilter):
    MODE = _FM.HIGH_PASS


class BandPass(_SingleFilter):
    MODE = _FM.BAND_PASS


class Notch(_SingleFilter):
    MODE = _FM.NOTCH


class LadderFilter(_core.Effect):
    """Moog-style: four cascaded one-pole-pair low-passes sharing one
    cutoff, resonance concentrated in the last stages. 24 dB/octave slope
    with the familiar squelch when resonance is pushed."""

    def __init__(self, source, cutoff=1200.0, resonance=0.4):
        self.cutoff = synthio.Math(synthio.MathOperation.SUM,
                                   _core.filter_hz(cutoff), 0.0, 0.0)
        q = 0.55 + 6.0 * resonance
        self.stages = [
            synthio.Biquad(_FM.LOW_PASS, self.cutoff, Q=0.6),
            synthio.Biquad(_FM.LOW_PASS, self.cutoff, Q=0.7),
            synthio.Biquad(_FM.LOW_PASS, self.cutoff, Q=q * 0.5),
            synthio.Biquad(_FM.LOW_PASS, self.cutoff, Q=q),
        ]
        self.node = audiofilters.Filter(filter=self.stages, **_core.pcm())
        self.node.play(source)
        self.output = self.node

    def set_cutoff(self, hz):
        self.cutoff.a = _core.filter_hz(hz)


class CombFilter(_core.Effect):
    """A short feedback delay tuned to a frequency: 1/f seconds."""

    def __init__(self, source, frequency=440.0, feedback=0.7, mix=0.5):
        delay_ms = 1000.0 / float(frequency)
        self.node = audiodelays.Echo(
            max_delay_ms=50, delay_ms=delay_ms, decay=feedback, mix=mix,
            freq_shift=False, **_core.pcm())
        self.node.play(source)
        self.output = self.node


class DynamicEQ(_core.Effect):
    """One dynamic band: the signal splits into everything-but-the-band
    (a notch) and the band itself, the band alone is compressed, and the
    two are summed. The band only comes down when it crosses the
    threshold - an approximation of a dynamic bell cut."""

    def __init__(self, source, frequency=3000.0, threshold_db=-30.0,
                 ratio=4.0, q=2.0):
        split = audioroute.Splitter(source, taps=2)
        self.rest = audiofilters.Filter(
            filter=synthio.Biquad(_FM.NOTCH, _core.filter_hz(frequency),
                                  Q=q), **_core.pcm())
        self.rest.play(split.tap(0))
        self.band = audiofilters.Filter(
            filter=synthio.Biquad(_FM.BAND_PASS, _core.filter_hz(frequency),
                                  Q=q), **_core.pcm())
        self.band.play(split.tap(1))
        self.dynamics = audiodynamics.Dynamics(
            audiodynamics.DYN_COMPRESS, threshold_db=threshold_db, ratio=ratio,
            attack_ms=2.0, release_ms=80.0, sample_rate=_core.SAMPLE_RATE)
        self.dynamics.play(self.band)
        self.mixer = audiomixer.Mixer(voice_count=2, **_core.pcm(1024))
        self.mixer.voice[0].play(self.rest)
        self.mixer.voice[0].level = 1.0
        self.mixer.voice[1].play(self.dynamics)
        self.mixer.voice[1].level = 1.0
        self.splitter = split
        self.output = self.mixer
