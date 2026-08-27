"""Delays, of two kinds.

`DigitalDelay`, `SlapbackDelay` and `MultiTapDelay` are clean: they run on
`audiodelays`, whose feedback path is the echo times a decay and nothing
else, which is exactly what a clean repeat is.

`TapeDelay`, `AnalogDelay` and `PingPongDelay` are not clean, and cannot be
built that way. All three are named after something that happens *inside* the
feedback loop - a filter that takes a little more off each pass, a soft-clip
that rounds it, a modulation that bends it, a cross-feed that sends it to the
other speaker - so they run on `audioecho.FeedbackDelay`, which puts those
there. See audioif's docs/upstream-diff.md.

The three coloured ones carry patches; see this package's README.
"""

import audiodelays
import audioecho

from . import _core


class DigitalDelay(_core.Effect):
    def __init__(self, source, time_ms=350.0, feedback=0.4, mix=0.3):
        self.node = audiodelays.Echo(
            max_delay_ms=int(time_ms) + 100, delay_ms=time_ms,
            decay=feedback, mix=mix, freq_shift=False, **_core.pcm())
        self.node.play(source)
        self.output = self.node

    def set_time(self, time_ms):
        self.node.delay_ms = time_ms

    def set_mix(self, mix):
        self.node.mix = mix


class SlapbackDelay(DigitalDelay):
    """One short, single repeat - the rockabilly vocal trick."""

    def __init__(self, source, time_ms=95.0, mix=0.4):
        DigitalDelay.__init__(self, source, time_ms=time_ms, feedback=0.0,
                              mix=mix)


class _LoopDelay(_core.Effect):
    """Shared plumbing for the three built on `audioecho.FeedbackDelay`.

    `max_time_ms` sizes the line and cannot change afterwards - it is what was
    allocated, and at 48 kHz a second of stereo line is 192 KB, so it is worth
    asking for only what will be used.

    `mix` runs 0..2 with the dry at unity until 1, which is `audiodelays.Echo`'s
    convention rather than a crossfade: the six delay classes have to mean one
    thing by it, and three of them are Echo's. The Time macro's range is fixed across
    every instance so a patch means the same milliseconds everywhere; on an
    instance with a short line the engine clamps, which is the honest failure.
    """

    #: Line headroom over the requested time, for the wow to move within and
    #: for the Time macro to have somewhere to go.
    HEADROOM = 2.0

    def _build(self, source, time_ms, max_time_ms, **options):
        line_ms = max_time_ms
        if line_ms is None:
            line_ms = max(float(time_ms) * self.HEADROOM, 400.0)
        self.node = audioecho.FeedbackDelay(
            sample_rate=_core.sample_rate(), max_delay_ms=line_ms, **options)
        self.node.play(source)
        self.max_time_ms = line_ms
        self.output = self.node

    def set_time(self, time_ms):
        """Retune the delay, in milliseconds."""
        self.set_macro(0, _core.macro_of(self.MACRO_RANGES[0], time_ms))

    def set_mix(self, mix):
        self.set_macro(2, _core.macro_of(self.MACRO_RANGES[2], mix))

    def clear(self):
        """Empty the line, so the next thing through is not played over the
        last thing that was."""
        self.node.clear()


class TapeDelay(_LoopDelay):
    """A tape machine's echo: each pass loses top and bottom and softens, and
    the transport's wow bends the pitch of the repeats as they go.

    The filtering is *in* the loop, which is the whole difference. This class
    used to low-pass the delay's output - the wet and the dry together, once -
    which darkened the first repeat as much as the tenth and, at a low mix,
    quietly took the top off the dry signal as well. Repeats now darken
    progressively and the dry path is untouched.
    """

    MACRO_LABELS = ("Time", "Feedback", "Mix", "Wow", "Tone", "Drive")
    MACRO_RANGES = ((20.0, 1000.0, "log"), (0.0, 0.95), (0.0, 2.0),
                    (0.0, 1.0), (800.0, 16000.0, "log"), (0.0, 1.0))
    PATCHES = {
        0: ("Init", (90, 60, 22, 38, 66, 38)),
        1: ("Slapback Tape", (55, 13, 19, 19, 79, 42)),
        2: ("Space Echo", (97, 74, 25, 42, 60, 55)),
        # Long, hot and dark: the repeats pile up faster than they decay and
        # the loop's soft-clip is what stops it running away.
        3: ("Dub Siren", (108, 107, 32, 60, 47, 72)),
        4: ("Worn Cassette", (86, 67, 25, 108, 37, 85)),
        5: ("Clean Repeats", (93, 53, 19, 6, 103, 6)),
    }

    #: The wobble's rate. Fixed rather than exposed: a tape transport's wow is
    #: slow by construction, and `Wow` is how far it swings.
    WOW_HZ = 0.7

    def __init__(self, source, time_ms=320.0, feedback=0.45, mix=0.35,
                 wow=0.3, tone_hz=3800.0, drive=0.3, max_time_ms=None,
                 patch=None):
        self._build(source, time_ms, max_time_ms, wow_hz=self.WOW_HZ,
                    cut_hz=90.0)
        self._init_macros((time_ms, feedback, mix, wow, tone_hz, drive),
                          patch)

    def _apply_macro(self, index, position):
        if index == 0:
            self.node.set(delay_ms=self.macro(0))
        elif index == 1:
            self.node.set(feedback=self.macro(1))
        elif index == 2:
            self.node.set(mix=self.macro(2))
        elif index == 3:
            self.node.set(wow_depth_ms=2.5 * self.macro(3))
        elif index == 4:
            self.node.set(damping_hz=self.macro(4))
        else:
            self.node.set(loop_drive=self.macro(5))


class AnalogDelay(_LoopDelay):
    """A bucket-brigade delay: band-limited at both ends by construction,
    darker with every pass, and drifting slightly because its clock does.

    `age` is one knob over the lot of it - a fresh unit against one whose
    capacitors have been in a pedal since 1978. It moves the loop's low-pass
    down, its high-pass up, and the drift and softening up with them.
    """

    MACRO_LABELS = ("Time", "Feedback", "Mix", "Age", "Drive")
    MACRO_RANGES = ((20.0, 1000.0, "log"), (0.0, 0.95), (0.0, 2.0),
                    (0.0, 1.0), (0.0, 1.0))
    PATCHES = {
        0: ("Init", (88, 53, 19, 64, 44)),
        1: ("Short BBD", (65, 47, 18, 51, 38)),
        2: ("Memory Man", (99, 74, 22, 79, 57)),
        3: ("Chorus Echo", (81, 51, 25, 38, 44)),
        4: ("Dying Battery", (96, 83, 29, 127, 89)),
    }

    WOW_HZ = 1.3

    def __init__(self, source, time_ms=300.0, feedback=0.4, mix=0.3,
                 age=0.5, drive=0.35, max_time_ms=None, patch=None):
        self._build(source, time_ms, max_time_ms, wow_hz=self.WOW_HZ)
        self._init_macros((time_ms, feedback, mix, age, drive), patch)

    def _apply_macro(self, index, position):
        if index == 0:
            self.node.set(delay_ms=self.macro(0))
        elif index == 1:
            self.node.set(feedback=self.macro(1))
        elif index == 2:
            self.node.set(mix=self.macro(2))
        elif index == 4:
            self.node.set(loop_drive=self.macro(4))
        else:
            # One knob, four settings. A bucket-brigade line loses its top
            # first and its bottom soon after, and an old one drifts: the
            # three move together or the knob is not describing a thing.
            age = self.macro(3)
            self.node.set(damping_hz=_core.logmap(1.0 - age, 1100.0, 4200.0),
                          cut_hz=_core.logmap(age, 60.0, 280.0),
                          wow_depth_ms=0.15 + 1.6 * age)


class PingPongDelay(_LoopDelay):
    """Repeats bouncing between the speakers: each channel's output feeds the
    *other* channel's line, so one repeat is on the left, the next on the
    right, and they alternate all the way down.

    This used to be two independent delays panned hard apart, one at twice the
    other's time. That gives repeats on both sides, which is not the same
    thing - nothing crossed over, so the pattern never alternated and the
    right side simply ran at half speed.
    """

    MACRO_LABELS = ("Time", "Feedback", "Mix", "Spread", "Tone")
    MACRO_RANGES = ((20.0, 1000.0, "log"), (0.0, 0.95), (0.0, 2.0),
                    (0.0, 1.0), (800.0, 16000.0, "log"))
    PATCHES = {
        0: ("Init", (86, 47, 22, 127, 85)),
        1: ("Wide Eighths", (95, 60, 25, 127, 95)),
        2: ("Narrow Taps", (68, 40, 19, 64, 103)),
        3: ("Dark Bounce", (104, 74, 29, 127, 50)),
    }

    def __init__(self, source, time_ms=280.0, feedback=0.35, mix=0.35,
                 spread=1.0, tone_hz=6000.0, max_time_ms=None, patch=None):
        self._build(source, time_ms, max_time_ms)
        self._init_macros((time_ms, feedback, mix, spread, tone_hz), patch)

    def _apply_macro(self, index, position):
        if index == 0:
            self.node.set(delay_ms=self.macro(0))
        elif index == 1:
            self.node.set(feedback=self.macro(1))
        elif index == 2:
            self.node.set(mix=self.macro(2))
        elif index == 4:
            self.node.set(damping_hz=self.macro(4))
        else:
            # Spread does two things at once because half of it is useless
            # alone: crossing the feedback over without steering the input to
            # one side gives repeats that alternate but start on both.
            spread = self.macro(3)
            self.node.set(cross_feed=spread, input_pan=-spread)


class MultiTapDelay(_core.Effect):
    """taps: (position 0..1 of time_ms, level) pairs."""

    def __init__(self, source, time_ms=500.0,
                 taps=((0.25, 0.8), (0.5, 0.6), (0.75, 0.4), (1.0, 0.3)),
                 mix=0.4):
        self.node = audiodelays.MultiTapDelay(
            max_delay_ms=int(time_ms) + 100, delay_ms=time_ms,
            decay=0.0, mix=mix, taps=tuple(taps), **_core.pcm())
        self.node.play(source)
        self.output = self.node
