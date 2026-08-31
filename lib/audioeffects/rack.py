"""Effect racks: one component whose internal graph is several effects.

A rack has exactly the effect shape - audio source in, `.output` out, MIDI
for control only - so it lives here as one more effect kind rather than in
a package of its own. `Rack` is the mechanism, ported from the way
micropython-vst3's soundtrack builds its custom racks: a serial chain of
this package's own classes, described by portable literals so a host can
construct one without holding any live objects:

    rack = audioeffects.create("Rack", source, 48000, chain=(
        ("Compressor", {"threshold_db": -24.0, "ratio": 3.0}),
        ("TapeDelay", {"time_ms": 340.0, "mix": 0.25}),
        ("Reverb", {"preset": "hall", "mix": 0.3}),
    ))
    audio_out.play(rack.output)

`ShimmerHall` and `AirSpace` are the two racks the soundtrack shares
between pieces (its `fx_shimmer.py` and `fx_space.py`), ported whole:
fixed topologies with a macro surface over the children, so they carry
patches the way any patchable effect here does. Racks may contain and be
used by other racks: a `chain` entry may itself be a `("Rack", {...})`.
"""

VENDOR = "PyDevices"

from . import _core


def _child(name, tail, options):
    """One chain entry built around `tail` at the configured rate."""
    import audioeffects
    return audioeffects.create(name, tail, _core.sample_rate(), **options)


class Rack(_core.Effect):
    """A serial chain of this package's effects, as one component.

    `chain` is a tuple of entries, each either an effect `NAME` or a
    `(NAME, options)` pair whose options are the keyword arguments that
    effect's constructor takes. The entries are built in order, each fed
    the previous one's `.output`; the live children are kept on
    `self.effects` in that order. An empty chain is a wire: the rack's
    output is its source, the same pattern as a flat `GraphicEQ`.

    The rack owns its children and `deinit()` releases them; the outer
    source stays borrowed, as the component contract requires. Latency and
    tail are those of the complete graph: latencies add, and the tail is
    the children's tails summed, or `None` as soon as any child's tail is
    unbounded.
    """

    NAME = 'Rack'
    DISPLAY_NAME = 'Effect Rack'
    CATEGORIES = ('Effect Rack',)
    VERSION = '0.0.1'
    MACRO_LABELS = ()
    MACRO_MODES = {}
    PATCHES = {0: ("Default", ())}

    def __init__(self, source, chain=()):
        self.effects = []
        tail = source
        for entry in chain:
            if isinstance(entry, str):
                name, options = entry, {}
            else:
                try:
                    name, options = entry
                except (TypeError, ValueError):
                    raise ValueError(
                        "a chain entry is a NAME or a (NAME, options) "
                        "pair, not %r" % (entry,))
                options = dict(options)
            child = _child(name, tail, options)
            self.effects.append(child)
            tail = child.output
        self._output = tail

    @property
    def latency_samples(self):
        self._check_live()
        return sum(child.latency_samples for child in self.effects)

    @property
    def tail_samples(self):
        self._check_live()
        total = 0
        for child in self.effects:
            tail = child.tail_samples
            if tail is None:
                return None
            total += tail
        return total

    def reset(self):
        """Clear the whole graph's DSP history, then restore patch 0.

        Each child's history is cleared directly rather than through
        `child.reset()`, because a child's own reset would also reapply
        that child's patch 0 over the options this rack built it with.
        """
        self._check_live()
        for child in self.effects:
            output = child.output
            if output is not child._source:
                try:
                    import audiocore
                    audiocore.reset_buffer(output)
                except (AttributeError, RuntimeError):
                    pass
        self.program_change(0)

    def deinit(self):
        if self._deinited:
            return
        for child in reversed(self.effects):
            child.deinit()
        self._output = None
        self._deinited = True


class ShimmerHall(Rack):
    """The classic shimmer: the signal plus a copy of itself an octave up,
    smeared through a tape echo and a long hall.

    The octave-up is the whole trick. A reverb on its own gets bigger; a
    reverb fed something an octave above what went in keeps growing upward,
    and that rising quality is what "shimmer" actually names. The tape echo
    in between is what stops it arriving all at once - each repeat is a
    little darker than the last, so the octave blooms in and decays rather
    than sitting there.

    Shimmer is how loud the octave sits under the dry, Echo the tape send,
    Space the hall, Tone how bright the repeats stay.
    """

    NAME = 'ShimmerHall'
    DISPLAY_NAME = 'Shimmer Hall'
    CATEGORIES = ('Effect Rack', 'Reverb')
    VERSION = '0.0.1'

    MACRO_LABELS = ("Shimmer", "Echo", "Space", "Tone")
    MACRO_MODES = {0: "UNIPOLAR", 1: "UNIPOLAR", 2: "UNIPOLAR",
                   3: "UNIPOLAR"}
    _MACRO_RANGES = ((0.0, 1.0), (0.0, 0.8), (0.0, 0.7),
                     (800.0, 16000.0, "log"))
    PATCHES = {0: ("Shimmer Hall", (70, 57, 76, 79))}

    def __init__(self, source, shimmer=0.55, echo=0.36, space=0.42,
                 tone_hz=5160.0, patch=None):
        # The octave branch is built at full level whatever `shimmer` asks
        # for, because the topology is fixed by construction: the Shimmer
        # macro moves the branch's mixer level, and a branch that was
        # skipped for starting at zero could never come back.
        Rack.__init__(self, source, chain=(
            ("Octaver", {"down": 0.0, "up": 1.0}),
            ("TapeDelay", {"time_ms": 420.0, "feedback": 0.5, "wow": 0.3,
                           "drive": 0.2}),
            ("Reverb", {"preset": "hall"}),
        ))
        self.octave, self.tape, self.hall = self.effects
        self._init_macros((shimmer, echo, space, tone_hz), patch)

    def _apply_macro(self, index, position):
        if index == 0:
            # voice[0] is the dry; voice[1] is the octave, which is the
            # only branch this Octaver was asked to build.
            self.octave.mixer.voice[1].level = self.macro(0)
        elif index == 1:
            self.tape.set_mix(self.macro(1))
        elif index == 2:
            self.hall.set_mix(self.macro(2))
        else:
            # The tape's own Tone macro, on the same 800-16000 Hz log span.
            self.tape.set_macro(4, position * 127.0)


class AirSpace(Rack):
    """A send-style space: a swept tone filter into a wobbling tape delay
    into a hall. Space is the reverb mix, Echo the tape send, Tone the
    filter."""

    NAME = 'AirSpace'
    DISPLAY_NAME = 'Air Space'
    CATEGORIES = ('Effect Rack', 'Reverb')
    VERSION = '0.0.1'

    MACRO_LABELS = ("Space", "Echo", "Tone")
    MACRO_MODES = {0: "UNIPOLAR", 1: "UNIPOLAR", 2: "UNIPOLAR"}
    _MACRO_RANGES = ((0.0, 0.6), (0.0, 0.6), (500.0, 12000.0, "log"))
    PATCHES = {0: ("Air Space", (64, 53, 85))}

    def __init__(self, source, space=0.3, echo=0.25, frequency=4200.0,
                 patch=None):
        Rack.__init__(self, source, chain=(
            ("LowPass", {"frequency": 4200.0}),
            ("TapeDelay", {"time_ms": 375.0, "feedback": 0.4}),
            ("Reverb", {"preset": "hall"}),
        ))
        self.tone, self.tape, self.hall = self.effects
        self._init_macros((space, echo, frequency), patch)

    def _apply_macro(self, index, position):
        if index == 0:
            self.hall.set_mix(self.macro(0))
        elif index == 1:
            self.tape.set_mix(self.macro(1))
        else:
            self.tone.set_frequency(self.macro(2))
