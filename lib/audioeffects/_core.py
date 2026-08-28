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
CHANNEL_COUNT = 2


def configure(rate, channel_count=2):
    """Set the format every effect built after this call will run at."""
    global SAMPLE_RATE, CHANNEL_COUNT
    SAMPLE_RATE = int(rate)
    CHANNEL_COUNT = int(channel_count)


def sample_rate():
    """The rate `configure()` last set. Read this rather than importing
    SAMPLE_RATE, which would be a copy taken at import time."""
    return SAMPLE_RATE


def channel_count():
    """Return the channel count selected by :func:`configure`."""
    return CHANNEL_COUNT


def static_transport():
    """Default transport for components that do not need a clock."""
    return (False, 0.0, 120.0, 4, 4)


#: How many taps one `audioroute.Splitter` fans out to. The limit lives in
#: the C (`AUDIOIF_SPLITTER_MAX_TAPS`, which raises "taps must be 1..4"),
#: and the native modules do not export it, so classes that build parallel
#: branches count against this mirror rather than a literal 4 apiece.
SPLITTER_TAPS = 4


def pcm(buffer_size=2048):
    """The keyword bundle every audioif node wants."""
    return {
        "sample_rate": SAMPLE_RATE,
        "channel_count": CHANNEL_COUNT,
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

    CAPABILITIES = ()
    LATENCY_SAMPLES = 0
    TAIL_SAMPLES = None

    def __new__(cls, *args, **kwargs):
        effect = super().__new__(cls)
        source = args[0] if args else kwargs.get("source")
        # Direct class construction is a supported local API.  Historically
        # those constructors read the package-wide format, so keep that path
        # coherent with the source as well as the canonical factory path.
        source_rate = getattr(source, "sample_rate", None)
        source_channels = getattr(source, "channel_count", None)
        if source_rate is not None and source_channels is not None:
            configure(source_rate, source_channels)
        effect._source = source
        effect._output = None
        effect._sample_rate = (SAMPLE_RATE if source_rate is None
                               else source_rate)
        effect._channel_count = (CHANNEL_COUNT if source_channels is None
                                 else source_channels)
        effect._transport = static_transport
        effect._macros = []
        effect._patch_index = 0
        effect._deinited = False
        effect._factory_options = None
        return effect

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
    def create(cls, source, sample_rate, transport=None, **options):
        """Construct ``cls`` for ``sample_rate`` around ``source``.

        Effect implementations historically took ``source`` in their
        constructor and used the package-wide ``configure()`` setting. Keep
        that implementation shape, but make the host-facing rate explicit at
        this one boundary.
        """
        source_rate = getattr(source, "sample_rate", None)
        source_channels = getattr(source, "channel_count", None)
        if source_rate is None or source_channels is None:
            raise TypeError("effect source must expose sample_rate and "
                            "channel_count")
        if int(source_rate) != int(sample_rate):
            raise ValueError("effect source sample_rate does not match "
                             "requested sample_rate")
        if int(source_channels) not in (1, 2):
            raise ValueError("effect source channel_count must be 1 or 2")
        configure(sample_rate, source_channels)
        effect = cls(source, **options)
        effect._finish_component(source, sample_rate, transport, options)
        if effect._output is None:
            raise TypeError("%s.create() returned no output"
                            % cls.__name__)
        return effect

    def _finish_component(self, source, sample_rate, transport, options):
        self._check_live()
        self._source = source
        self._sample_rate = int(sample_rate)
        self._channel_count = int(source.channel_count)
        self._transport = static_transport if transport is None else transport
        self._factory_options = dict(options)
        output_rate = getattr(self._output, "sample_rate", self._sample_rate)
        output_channels = getattr(self._output, "channel_count",
                                  self._channel_count)
        if int(output_rate) != self._sample_rate:
            raise ValueError("effect output sample_rate does not match source")
        if int(output_channels) != self._channel_count:
            raise ValueError("effect output channel_count does not match source")

    def _check_live(self):
        if self._deinited:
            raise RuntimeError("effect has been deinitialized")

    @property
    def output(self):
        self._check_live()
        return self._output

    @property
    def sample_rate(self):
        self._check_live()
        return self._sample_rate

    @property
    def channel_count(self):
        self._check_live()
        return self._channel_count

    @property
    def latency_samples(self):
        self._check_live()
        return _nonnegative_int(getattr(type(self), "LATENCY_SAMPLES", 0),
                                "latency_samples")

    @property
    def tail_samples(self):
        self._check_live()
        return _tail_value(getattr(type(self), "TAIL_SAMPLES", None))

    @property
    def capabilities(self):
        self._check_live()
        capabilities = tuple(getattr(type(self), "CAPABILITIES", ()))
        if any(not isinstance(capability, str) or
               any(ord(character) >= 128 for character in capability)
               for capability in capabilities):
            raise ValueError("effect capabilities must be ASCII strings")
        return capabilities

    @property
    def patch_index(self):
        self._check_live()
        return self._patch_index

    @property
    def transport(self):
        self._check_live()
        return self._transport

    def _init_macros(self, values, patch=None):
        """Seed the knobs from the constructor's arguments and, if one was
        asked for, apply a patch over the top."""
        self._macros = [macro_position(span, value)
                        for span, value in zip(self._MACRO_RANGES, values)]
        for index, position in enumerate(self._macros):
            self._apply_macro(index, position)
        self._patch_index = 0
        if patch is not None:
            self.program_change(patch)

    def set_macro(self, index, value, channel=0, note_id=-1,
                  sample_position=0):
        """Set macro `index` from the 0-127 MIDI scale. Floats are accepted so
        a host with finer resolution need not quantize."""
        del channel, note_id
        _sample_position(sample_position)
        self._check_live()
        if isinstance(index, bool) or not isinstance(index, int):
            raise IndexError("macro index must be an integer")
        if not 0 <= index < len(self.MACRO_LABELS):
            raise IndexError("%s has %d macros; no index %d"
                             % (type(self).__name__, len(self.MACRO_LABELS),
                                index))
        self._macros[index] = min(1.0, max(0.0, float(value) / 127.0))
        self._patch_index = None
        self._apply_macro(index, self._macros[index])

    def program_change(self, index, channel=0, note_id=-1,
                       sample_position=0):
        """Apply patch `index`. An index this class does not have is ignored,
        as it is on an instrument: a program change is a wire message, and the
        wire carries indices nobody has to have implemented."""
        del channel, note_id
        _sample_position(sample_position)
        self._check_live()
        if isinstance(index, bool) or not isinstance(index, int):
            raise ValueError("program index must be a non-negative integer")
        if index < 0:
            raise ValueError("program index must be non-negative")
        patch = self.PATCHES.get(index)
        if patch is None:
            return
        for macro, value in enumerate(patch[1]):
            self._macros[macro] = min(1.0, max(0.0, float(value) / 127.0))
            self._apply_macro(macro, self._macros[macro])
        self._patch_index = index

    def macro(self, index):
        """What macro `index` currently stands for, in its own units."""
        self._check_live()
        return macro_value(self._MACRO_RANGES[index], self._macros[index])

    def get_macro(self, index):
        self._check_live()
        if isinstance(index, bool) or not isinstance(index, int):
            raise IndexError("macro index must be an integer")
        if not 0 <= index < len(self.MACRO_LABELS):
            raise IndexError("%s has %d macros; no index %d"
                             % (type(self).__name__, len(self.MACRO_LABELS),
                                index))
        return self._macros[index] * 127.0

    def pitch_bend(self, value, channel=0, sample_position=0):
        self._check_live()
        _pitch_bend(value)
        _channel(channel)
        _sample_position(sample_position)

    def control_change(self, controller, value, channel=0, sample_position=0):
        self._check_live()
        _midi_value(controller, "controller")
        _bounded_midi(value)
        _channel(channel)
        _sample_position(sample_position)

    def channel_pressure(self, value, channel=0, sample_position=0):
        self._check_live()
        _bounded_midi(value)
        _channel(channel)
        _sample_position(sample_position)

    def poly_pressure(self, pitch, value, channel=0, note_id=-1,
                      sample_position=0):
        self._check_live()
        _midi_value(pitch, "pitch")
        _bounded_midi(value)
        _channel(channel)
        _note_id(note_id)
        _sample_position(sample_position)

    def reset(self):
        self._check_live()
        if self._output is not None and self._output is not self._source:
            try:
                import audiocore
                audiocore.reset_buffer(self._output)
            except (AttributeError, RuntimeError):
                pass
        self.program_change(0)

    def deinit(self):
        if self._deinited:
            return
        output = self._output
        if output is not None and output is not self._source:
            deinit = getattr(output, "deinit", None)
            if deinit is not None:
                deinit()
        self._output = None
        self._deinited = True

    def _apply_macro(self, index, position):
        """Push macro `index`, at its 0..1 `position`, into the nodes. Read
        `self._macros[other]` for a setting that depends on two knobs."""
        raise NotImplementedError(
            "%s declares macros but does not apply them"
            % (type(self).__name__,))


def _nonnegative_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("%s must be a non-negative integer" % name)
    if value < 0:
        raise ValueError("%s must be non-negative" % name)
    return value


def _tail_value(value):
    if value is None:
        return None
    return _nonnegative_int(value, "tail_samples")


def _midi_value(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("%s must be an integer from 0 through 127" % name)
    if not 0 <= value <= 127:
        raise ValueError("%s must be from 0 through 127" % name)
    return value


def _bounded_midi(value):
    value = float(value)
    return min(127.0, max(0.0, value))


def _pitch_bend(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("pitch bend must be an integer from 0 through 16383")
    if not 0 <= value <= 16383:
        raise ValueError("pitch bend must be from 0 through 16383")
    return value


def _channel(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("channel must be an integer from 0 through 15")
    if not 0 <= value <= 15:
        raise ValueError("channel must be from 0 through 15")
    return value


def _note_id(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("note_id must be -1 or a non-negative integer")
    if value < -1:
        raise ValueError("note_id must be -1 or non-negative")
    return value


def _sample_position(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("sample_position must be a non-negative integer")
    if value < 0:
        raise ValueError("sample_position must be non-negative")
    return value


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
