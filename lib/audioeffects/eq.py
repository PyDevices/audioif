"""Equalizers and filters, built on Biquad chains inside
audiofilters.Filter. Biquad frequencies and Qs accept synthio blocks, so
every cutoff here can be swept smoothly from a macro via set_* methods.
"""

VENDOR = "PyDevices"

import audiodelays
import audiodynamics
import audiofilters
import audiomixer
import audioroute
import synthio

from . import _core

_FM = synthio.FilterMode


class ParametricEQ(_core.Effect):
    """bands: (frequency_hz, gain_db, q) peaking bells, plus optional
    low_shelf/high_shelf as (frequency_hz, gain_db).

    Every section - bell, low shelf, high shelf - is one Biquad in a
    single Filter's cascade, which is what a parametric EQ is. Boosts and
    cuts cost exactly the same and there is no limit on how many of
    either. The bells were previously synthesized from notch sections and
    band-passed Splitter branches summed through a Mixer, because the
    engine's peaking biquad computed b2 with the wrong sign; boosts were
    capped at three because a Splitter has four taps. Both constraints are
    gone.

    ``biquads`` holds the sections in chain order, so an application can
    bind a macro straight to ``eq.biquads[2].frequency`` or ``.A``."""

    NAME = 'ParametricEQ'
    DISPLAY_NAME = 'Parametric EQ'
    CATEGORIES = ('EQ',)
    VERSION = '0.0.1'
    MACRO_LABELS = ()
    MACRO_MODES = {}
    PATCHES = {0: ("Default", ())}

    def __init__(self, source, bands=(), low_shelf=None, high_shelf=None):
        self.biquads = []
        for frequency, gain_db, q in bands:
            self.biquads.append(synthio.Biquad(
                _FM.PEAKING_EQ, _core.check_hz(frequency), Q=q,
                A=_core.db_to_amplitude(gain_db)))
        for shelf, mode in ((low_shelf, _FM.LOW_SHELF),
                            (high_shelf, _FM.HIGH_SHELF)):
            if shelf is not None:
                self.biquads.append(synthio.Biquad(
                    mode, _core.check_hz(shelf[0]), Q=0.707,
                    A=_core.db_to_amplitude(shelf[1])))
        if not self.biquads:
            # An EQ asked for nothing is a wire, not a chain of no filters:
            # every Filter stage costs a buffer and 16 bits of headroom.
            self.node = None
            self._output = source
            return
        self.node = audiofilters.Filter(filter=self.biquads, **_core.pcm())
        self.node.play(source)
        self._output = self.node


ISO_BANDS = (31.5, 63.0, 125.0, 250.0, 500.0,
             1000.0, 2000.0, 4000.0, 8000.0, 16000.0)


class GraphicEQ(ParametricEQ):
    """Ten fixed ISO-centered bands; gains_db is one value per band, any
    mix of boosts and cuts. Bands left flat are dropped rather than built
    as unity sections, and so are bands above Nyquist at the configured
    rate - the top ISO band needs better than 32 kHz to exist at all."""

    NAME = 'GraphicEQ'
    DISPLAY_NAME = 'Graphic EQ'
    CATEGORIES = ('EQ',)
    VERSION = '0.0.1'
    MACRO_LABELS = ()
    MACRO_MODES = {}
    PATCHES = {0: ("Default", ())}

    def __init__(self, source, gains_db=None):
        # No curve means a flat one. Every other effect in this package is
        # constructible from a source alone, and a graphic EQ that cannot be
        # is a wart rather than a design: flat is precisely what it does
        # before anyone moves a slider.
        if gains_db is None:
            gains_db = [0.0] * len(ISO_BANDS)
        limit = _core.sample_rate() * 0.5
        ParametricEQ.__init__(self, source, bands=[
            (freq, gain, 1.4) for freq, gain in zip(ISO_BANDS, gains_db)
            if abs(gain) > 0.01 and freq < limit])


class _SingleFilter(_core.Effect):
    MODE = None

    def __init__(self, source, frequency=1000.0, q=0.707, mix=1.0):
        self.frequency = synthio.Math(synthio.MathOperation.SUM,
                                      _core.check_hz(frequency), 0.0, 0.0)
        self.biquad = synthio.Biquad(self.MODE, self.frequency, Q=q)
        self.node = audiofilters.Filter(filter=self.biquad, mix=mix,
                                        **_core.pcm())
        self.node.play(source)
        self._output = self.node

    def set_frequency(self, hz):
        self.frequency.a = _core.check_hz(hz)


class LowPass(_SingleFilter):

    NAME = 'LowPass'
    DISPLAY_NAME = 'Low Pass'
    CATEGORIES = ('Filter',)
    VERSION = '0.0.1'
    MACRO_LABELS = ()
    MACRO_MODES = {}
    PATCHES = {0: ("Default", ())}
    MODE = _FM.LOW_PASS


class HighPass(_SingleFilter):

    NAME = 'HighPass'
    DISPLAY_NAME = 'High Pass'
    CATEGORIES = ('Filter',)
    VERSION = '0.0.1'
    MACRO_LABELS = ()
    MACRO_MODES = {}
    PATCHES = {0: ("Default", ())}
    MODE = _FM.HIGH_PASS


class BandPass(_SingleFilter):

    NAME = 'BandPass'
    DISPLAY_NAME = 'Band Pass'
    CATEGORIES = ('Filter',)
    VERSION = '0.0.1'
    MACRO_LABELS = ()
    MACRO_MODES = {}
    PATCHES = {0: ("Default", ())}
    MODE = _FM.BAND_PASS


class Notch(_SingleFilter):

    NAME = 'Notch'
    DISPLAY_NAME = 'Notch'
    CATEGORIES = ('Filter',)
    VERSION = '0.0.1'
    MACRO_LABELS = ()
    MACRO_MODES = {}
    PATCHES = {0: ("Default", ())}
    MODE = _FM.NOTCH


class LadderFilter(_core.Effect):
    """Moog-style: four cascaded one-pole-pair low-passes sharing one
    cutoff, resonance concentrated in the last stages. 24 dB/octave slope
    with the familiar squelch when resonance is pushed."""

    NAME = 'LadderFilter'
    DISPLAY_NAME = 'Ladder Filter'
    CATEGORIES = ('Filter',)
    VERSION = '0.0.1'
    MACRO_LABELS = ()
    MACRO_MODES = {}
    PATCHES = {0: ("Default", ())}

    def __init__(self, source, cutoff=1200.0, resonance=0.4):
        self.cutoff = synthio.Math(synthio.MathOperation.SUM,
                                   _core.check_hz(cutoff), 0.0, 0.0)
        q = 0.55 + 6.0 * resonance
        self.stages = [
            synthio.Biquad(_FM.LOW_PASS, self.cutoff, Q=0.6),
            synthio.Biquad(_FM.LOW_PASS, self.cutoff, Q=0.7),
            synthio.Biquad(_FM.LOW_PASS, self.cutoff, Q=q * 0.5),
            synthio.Biquad(_FM.LOW_PASS, self.cutoff, Q=q),
        ]
        self.node = audiofilters.Filter(filter=self.stages, **_core.pcm())
        self.node.play(source)
        self._output = self.node

    def set_cutoff(self, hz):
        self.cutoff.a = _core.check_hz(hz)


class CombFilter(_core.Effect):
    """A short feedback delay tuned to a frequency: 1/f seconds."""

    NAME = 'CombFilter'
    DISPLAY_NAME = 'Comb Filter'
    CATEGORIES = ('Filter',)
    VERSION = '0.0.1'
    MACRO_LABELS = ()
    MACRO_MODES = {}
    PATCHES = {0: ("Default", ())}

    def __init__(self, source, frequency=440.0, feedback=0.7, mix=0.5):
        delay_ms = 1000.0 / float(frequency)
        self.node = audiodelays.Echo(
            max_delay_ms=50, delay_ms=delay_ms, decay=feedback, mix=mix,
            freq_shift=False, **_core.pcm())
        self.node.play(source)
        self._output = self.node


class DynamicEQ(_core.Effect):
    """One dynamic band: the signal splits into everything-but-the-band
    (a notch) and the band itself, the band alone is compressed, and the
    two are summed, so the band comes down only when it crosses the
    threshold.

    The split is exact, not an approximation. RBJ's notch and its
    0 dB-peak band-pass share a denominator and their numerators sum to
    it, so notch + band-pass is unity: with the compressor idle this
    reconstructs the input. That was always the intent; it only became
    true once a stereo Filter stopped sharing one biquad state between
    the channels, which used to leak each channel's band into the other's
    notch."""

    NAME = 'DynamicEQ'
    DISPLAY_NAME = 'Dynamic EQ'
    CATEGORIES = ('EQ',)
    VERSION = '0.0.1'
    MACRO_LABELS = ()
    MACRO_MODES = {}
    PATCHES = {0: ("Default", ())}

    def __init__(self, source, frequency=3000.0, threshold_db=-30.0,
                 ratio=4.0, q=2.0):
        frequency = _core.check_hz(frequency)
        split = audioroute.Splitter(source, taps=2)
        self.rest = audiofilters.Filter(
            filter=synthio.Biquad(_FM.NOTCH, frequency, Q=q), **_core.pcm())
        self.rest.play(split.tap(0))
        self.band = audiofilters.Filter(
            filter=synthio.Biquad(_FM.BAND_PASS, frequency, Q=q),
            **_core.pcm())
        self.band.play(split.tap(1))
        self.dynamics = audiodynamics.Dynamics(
            audiodynamics.DYN_COMPRESS, threshold_db=threshold_db, ratio=ratio,
            attack_ms=2.0, release_ms=80.0, sample_rate=_core.SAMPLE_RATE, channel_count=_core.channel_count())
        self.dynamics.play(self.band)
        self.mixer = audiomixer.Mixer(voice_count=2, **_core.pcm(1024))
        self.mixer.voice[0].play(self.rest)
        self.mixer.voice[0].level = 1.0
        self.mixer.voice[1].play(self.dynamics)
        self.mixer.voice[1].level = 1.0
        self.splitter = split
        self._output = self.mixer
