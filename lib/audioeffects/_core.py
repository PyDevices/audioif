"""Shared plumbing for the effects library.

Every effect class takes its audio source as the first argument - a
synthesizer, an instrument's ``output``, the host's input, or a previous
effect's ``output`` - builds its chain immediately, and exposes the chain
tail as ``.output``:

    import audioeffects
    from audioeffects import Compressor, Reverb

    audioeffects.configure(48000)
    comp = Compressor(source, threshold_db=-20, ratio=3)
    verb = Reverb(comp.output, preset="hall", mix=0.3)
    audio_out.play(verb.output)

The underlying audioif nodes are kept as attributes so applications can
bind parameters straight to them.
"""

import math

#: Every node this library builds is created at this rate. It is module state
#: rather than a constructor argument because a process only ever has one
#: sample rate, and threading it through 39 classes would be noise. Call
#: ``configure()`` before building anything.
SAMPLE_RATE = 48000


def configure(rate):
    """Set the rate every effect built after this call will run at."""
    global SAMPLE_RATE
    SAMPLE_RATE = int(rate)


def sample_rate():
    """The rate `configure()` last set. Read this rather than importing
    SAMPLE_RATE, which would be a copy taken at import time."""
    return SAMPLE_RATE


def pcm(buffer_size=2048):
    """The keyword bundle every audioif node wants."""
    return {
        "sample_rate": SAMPLE_RATE,
        "channel_count": 2,
        "bits_per_sample": 16,
        "samples_signed": True,
        "buffer_size": buffer_size,
    }


def db_to_gain(db):
    return 10.0 ** (db / 20.0)


def db_to_amplitude(db):
    """Biquad peaking/shelf A parameter."""
    return 10.0 ** (db / 40.0)


def logmap(value, lo, hi):
    """0..1 -> lo..hi, logarithmic; the natural mapping for frequencies."""
    return lo * ((hi / lo) ** value)


class Effect:
    """Base: subclasses set self.output to their chain tail."""

    output = None


# CircuitPython's audiofilters.Filter (and this engine's faithful port of
# it) runs one biquad state across the interleaved stereo stream, which
# halves every frequency the filter perceives: a biquad asked for f is
# centered at 2f. Verified against the CircuitPython oracle - mono is
# exact, stereo is shifted - so the library compensates here instead of
# diverging from upstream. Peaking EQ is unusable at this pin (upstream
# computes b2 with the wrong sign); ParametricEQ builds bells from notch
# and band-pass sections instead.
SPECTRAL_SCALE = 0.5


def filter_hz(frequency):
    """The value to hand a Biquad inside a stereo Filter so its true
    center lands at `frequency`."""
    return float(frequency) * SPECTRAL_SCALE
