"""Shared plumbing for the effects library.

Every effect class takes its audio source as the first argument - a
synthesizer, an instrument's ``output``, the host's input, or a previous
effect's ``output`` - builds its chain immediately, and exposes the chain
tail as ``.output``:

    import audioeffects

    comp = audioeffects.create("Compressor", source, 48000,
                               threshold_db=-20, ratio=3)
    verb = audioeffects.create("Reverb", comp.output, 48000,
                               preset="hall", mix=0.3)
    audio_out.play(verb.output)

The underlying audioif nodes are kept as attributes so applications can bind
parameters straight to them. Direct class construction remains supported for
local code after `configure()`.

Some classes also carry patches - named settings on the 0-127 MIDI grid, the
way an instrument does. See `Effect` below.
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


def macro_value(span, position):
    """A macro's 0..1 position -> the value it stands for. ``span`` is
    ``(low, high)``, or ``(low, high, "log")`` for the ones that should sweep
    by ratio rather than by difference - anything in hertz or seconds."""
    low, high = span[0], span[1]
    if len(span) > 2:
        return logmap(position, low, high)
    return low + (high - low) * position


def macro_position(span, value):
    """The inverse of `macro_value`, unquantized. Used to seed a knob from a
    constructor argument, so the exact number a caller asked for stays on the
    audio path rather than being rounded onto the 7-bit grid first."""
    low, high = span[0], span[1]
    if len(span) > 2:
        position = math.log(value / low) / math.log(high / low)
    else:
        position = (value - low) / (high - low)
    return min(1.0, max(0.0, position))


def macro_of(span, value):
    """`value` as the nearest integer on the 0-127 MIDI grid. Patch authoring
    and the tests that hold patch 0 to the constructor's defaults need this;
    nothing on the audio path calls it."""
    return int(round(macro_position(span, value) * 127))


class Effect:
    """Base: subclasses set self.output to their chain tail.

    ``create(source, sample_rate, **options)`` is the stable construction
    boundary for hosts. Direct class calls remain a convenient local API and
    use the package-wide rate selected by :func:`configure`.

    A public subclass carries a **patch surface**, in the shape the instrument
    tier uses: `MACRO_LABELS` names the knobs, `MACRO_MODES` describes each
    control's public behavior, `PATCHES` holds settings on the 0-127 MIDI
    grid, and `_apply_macro` does the work. `_MACRO_RANGES` is private
    implementation data for converting those values into engineering units.
    The provider validator requires every public subclass to declare the
    public fields explicitly, including empty values for a macro-less effect.

    A patchable class calls `_init_macros()` at the end of its `__init__` with
    its own arguments, in the macros' own units. That is deliberately the only
    route into `_apply_macro`, so the constructor and a later `set_macro` can
    never drift apart.
    """

    output = None

    #: Knob names, one per macro index - the same thing an instrument module's
    #: MACRO_LABELS means.
    MACRO_LABELS = ()

    #: One of UNIPOLAR, BIPOLAR, or TOGGLE for every macro index.
    MACRO_MODES = {}

    #: Private engineering spans; never part of the provider metadata.
    _MACRO_RANGES = ()

    #: {index: (name, (values on the 0-127 grid,))}. Patch 0 is the
    #: constructor's own defaults rendered onto that grid - close to a fresh
    #: instance, not identical to one, because the grid is 128 steps wide and
    #: the defaults are not obliged to land on it. `test_patch_zero_is_the_
    #: constructor_defaults` holds every patchable class to that.
    PATCHES = {}

    @classmethod
    def create(cls, source, sample_rate, **options):
        """Construct ``cls`` for ``sample_rate`` around ``source``.

        Effect implementations historically took ``source`` in their
        constructor and used the package-wide ``configure()`` setting. Keep
        that implementation shape, but make the host-facing rate explicit at
        this one boundary.
        """
        configure(sample_rate)
        effect = cls(source, **options)
        if getattr(effect, "output", None) is None:
            raise TypeError("%s.create() returned no output"
                            % cls.__name__)
        return effect

    def _init_macros(self, values, patch=None):
        """Seed the knobs from the constructor's arguments and, if one was
        asked for, apply a patch over the top."""
        self._macros = [macro_position(span, value)
                        for span, value in zip(self._MACRO_RANGES, values)]
        for index, position in enumerate(self._macros):
            self._apply_macro(index, position)
        if patch is not None:
            self.program_change(patch)

    def set_macro(self, index, value):
        """Set macro `index` from the 0-127 MIDI scale. Floats are accepted so
        a host with finer resolution need not quantize."""
        index = int(index)
        if not 0 <= index < len(self.MACRO_LABELS):
            raise IndexError("%s has %d macros; no index %d"
                             % (type(self).__name__, len(self.MACRO_LABELS),
                                index))
        self._macros[index] = min(1.0, max(0.0, value / 127.0))
        self._apply_macro(index, self._macros[index])

    def program_change(self, index):
        """Apply patch `index`. An index this class does not have is ignored,
        as it is on an instrument: a program change is a wire message, and the
        wire carries indices nobody has to have implemented."""
        patch = self.PATCHES.get(int(index))
        if patch is None:
            return
        for macro, value in enumerate(patch[1]):
            self.set_macro(macro, value)

    def macro(self, index):
        """What macro `index` currently stands for, in its own units."""
        return macro_value(self._MACRO_RANGES[index], self._macros[index])

    def _apply_macro(self, index, position):
        """Push macro `index`, at its 0..1 `position`, into the nodes. Read
        `self._macros[other]` for a setting that depends on two knobs."""
        raise NotImplementedError(
            "%s declares macros but does not apply them"
            % (type(self).__name__,))


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
