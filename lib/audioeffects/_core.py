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


#: How many taps one `audioroute.Splitter` fans out to. The limit lives in
#: the C (`AUDIOIF_SPLITTER_MAX_TAPS`, which raises "taps must be 1..4"),
#: and the native modules do not export it, so classes that build parallel
#: branches count against this mirror rather than a literal 4 apiece.
SPLITTER_TAPS = 4


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


# This library used to halve every frequency it handed a Biquad, and to
# build bells out of notch and band-pass sections. Both were workarounds
# for engine bugs that no longer exist: a stereo audiofilters.Filter now
# keeps one biquad state per channel (so a filter asked for f is centered
# at f, not 2f), and PEAKING_EQ computes b2 with the sign the RBJ cookbook
# calls for. See docs/upstream-diff.md. Frequencies here are now just
# frequencies. Note that a stock CircuitPython board still has both bugs -
# see this package's README.


def check_hz(frequency):
    """A biquad's center must sit below Nyquist. Above it the coefficient
    math folds over and the filter is noise rather than a filter, silently.
    Halving every frequency used to keep the library clear of the edge by
    accident; now that it doesn't, say so out loud instead."""
    frequency = float(frequency)
    limit = SAMPLE_RATE * 0.5
    if not 0.0 < frequency < limit:
        raise ValueError(
            "filter frequency %g Hz is outside 0..%g Hz (Nyquist at the "
            "configured %d Hz rate)" % (frequency, limit, SAMPLE_RATE))
    return frequency
