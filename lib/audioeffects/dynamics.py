"""Dynamic range processors, built on the audiodynamics.Dynamics engine node.

Character presets stand in for classic circuit topologies by their
envelope behaviour: VCA (clean, fast), FET (very fast, hard knee),
Optical (slow, program-dependent feel via a long release and soft knee),
Vari-Mu (slow and round). They shape *when* gain moves, which is most of
what those circuits sound like at this level of modelling.
"""

import audiodynamics
import audiofilters
import audiomixer
import audioroute
import synthio

from . import _core

_CHARACTERS = {
    "vca": (10.0, 120.0, 6.0),
    "fet": (0.5, 50.0, 0.0),
    "optical": (15.0, 400.0, 12.0),
    "varimu": (30.0, 250.0, 18.0),
}


class Compressor(_core.Effect):
    def __init__(self, source, threshold_db=-24.0, ratio=4.0,
                 character="vca", attack_ms=None, release_ms=None,
                 knee_db=None, makeup_db=0.0):
        preset = _CHARACTERS[character]
        self.node = audiodynamics.Dynamics(
            audiodynamics.DYN_COMPRESS,
            threshold_db=threshold_db, ratio=ratio,
            attack_ms=attack_ms if attack_ms is not None else preset[0],
            release_ms=release_ms if release_ms is not None else preset[1],
            knee_db=knee_db if knee_db is not None else preset[2],
            makeup_db=makeup_db, sample_rate=_core.SAMPLE_RATE)
        self.node.play(source)
        self.output = self.node


class Limiter(_core.Effect):
    """Brickwall-style: instant attack against a hard ceiling."""

    def __init__(self, source, ceiling_db=-1.0, release_ms=60.0):
        self.node = audiodynamics.Dynamics(
            audiodynamics.DYN_LIMIT, threshold_db=ceiling_db,
            attack_ms=0.05, release_ms=release_ms,
            sample_rate=_core.SAMPLE_RATE)
        self.node.play(source)
        self.output = self.node


class Expander(_core.Effect):
    """Downward expander: below the threshold, quiet gets quieter."""

    def __init__(self, source, threshold_db=-40.0, ratio=2.0,
                 attack_ms=5.0, release_ms=150.0):
        self.node = audiodynamics.Dynamics(
            audiodynamics.DYN_EXPAND, threshold_db=threshold_db, ratio=ratio,
            attack_ms=attack_ms, release_ms=release_ms,
            sample_rate=_core.SAMPLE_RATE)
        self.node.play(source)
        self.output = self.node


class NoiseGate(_core.Effect):
    def __init__(self, source, threshold_db=-50.0, attack_ms=1.5,
                 release_ms=80.0):
        self.node = audiodynamics.Dynamics(
            audiodynamics.DYN_GATE, threshold_db=threshold_db,
            attack_ms=attack_ms, release_ms=release_ms,
            sample_rate=_core.SAMPLE_RATE)
        self.node.play(source)
        self.output = self.node


class DeEsser(_core.Effect):
    """Broadband de-esser: the detector hears only what is above
    `frequency`, so sibilance ducks the signal and lows never trigger it."""

    def __init__(self, source, threshold_db=-30.0, ratio=6.0,
                 frequency=5000.0, attack_ms=0.5, release_ms=60.0):
        self.node = audiodynamics.Dynamics(
            audiodynamics.DYN_COMPRESS, threshold_db=threshold_db, ratio=ratio,
            attack_ms=attack_ms, release_ms=release_ms, knee_db=3.0,
            sidechain_hz=frequency, sample_rate=_core.SAMPLE_RATE)
        self.node.play(source)
        self.output = self.node


class TransientShaper(_core.Effect):
    """Positive attack_db pushes the hit forward, negative pulls it back;
    sustain_db does the same for what rings after it."""

    def __init__(self, source, attack_db=0.0, sustain_db=0.0):
        self.node = audiodynamics.Dynamics(
            audiodynamics.DYN_TRANSIENT, attack_gain_db=attack_db,
            sustain_gain_db=sustain_db, sample_rate=_core.SAMPLE_RATE)
        self.node.play(source)
        self.output = self.node


class MultibandCompressor(_core.Effect):
    """Three bands split at the two crossover frequencies, compressed
    independently, and summed. Linkwitz-Riley crossovers - two cascaded
    Butterworth sections a side - so the three bands recombine flat to a
    fraction of a decibel when none of them is working."""

    def __init__(self, source, low_hz=200.0, high_hz=2000.0,
                 thresholds_db=(-28.0, -24.0, -24.0),
                 ratios=(4.0, 3.0, 4.0)):
        split = audioroute.Splitter(source, taps=3)
        FM = synthio.FilterMode

        def band(tap, biquads):
            return audiofilters.Filter(filter=biquads, **_core.pcm())

        def pair(mode, hz):
            # Both halves of a crossover have to be the same order or the sum
            # dips at the crossing. The mid band used to take a single
            # high-pass against the low band's cascaded pair, which cost 3.4 dB
            # at 200 Hz - invisible while the filters themselves were wrong.
            return [synthio.Biquad(mode, hz, Q=0.707) for _ in range(2)]

        lo = _core.check_hz(low_hz)
        hi = _core.check_hz(high_hz)
        low = band(0, pair(FM.LOW_PASS, lo))
        mid = band(1, pair(FM.HIGH_PASS, lo) + pair(FM.LOW_PASS, hi))
        high = band(2, pair(FM.HIGH_PASS, hi))
        low.play(split.tap(0))
        mid.play(split.tap(1))
        high.play(split.tap(2))

        self.bands = []
        mixer = audiomixer.Mixer(voice_count=3, **_core.pcm(1024))
        for index, (filt, thr, ratio) in enumerate(
                zip((low, mid, high), thresholds_db, ratios)):
            comp = audiodynamics.Dynamics(
                audiodynamics.DYN_COMPRESS, threshold_db=thr, ratio=ratio,
                attack_ms=8.0, release_ms=150.0,
                sample_rate=_core.SAMPLE_RATE)
            comp.play(filt)
            self.bands.append(comp)
            mixer.voice[index].play(comp)
            mixer.voice[index].level = 1.0
        self.splitter = split
        self.mixer = mixer
        self.output = mixer
