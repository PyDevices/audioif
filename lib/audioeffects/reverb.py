"""Reverb: an algorithmic one over the engine's Freeverb, and a convolution
one over `audioconvolve`.

Reach for `Reverb` first. Freeverb is a fixed handful of delay lines and it
costs the same on a Cortex-M0 as on a workstation. `ConvolutionReverb` applies
a real impulse response, which is the only way to get a *particular* room
rather than a plausible one -- and it costs, in both directions, roughly two
orders of magnitude more. See its docstring before using it on a board.
"""

VENDOR = "PyDevices"

import audiodelays
import audiofreeverb

from . import _core

try:
    import audioconvolve
except ImportError:      # a stock CircuitPython board, or an old audioif
    audioconvolve = None

_PRESETS = {
    #            roomsize damp
    "room":     (0.55, 0.6),
    "chamber":  (0.72, 0.5),
    "hall":     (0.88, 0.35),
    "plate":    (0.80, 0.15),
    "spring":   (0.62, 0.25),
}


class Reverb(_core.Effect):

    NAME = 'Reverb'
    DISPLAY_NAME = 'Reverb'
    CATEGORIES = ('Reverb',)
    VERSION = '0.0.1'
    MACRO_LABELS = ()
    MACRO_MODES = {}
    PATCHES = {0: ("Default", ())}
    def __init__(self, source, preset="hall", mix=0.3):
        roomsize, damp = _PRESETS[preset]
        chain_source = source
        if preset == "spring":
            # the boingy pre-flutter of a spring tank
            self.flutter = audiodelays.Echo(
                max_delay_ms=60, delay_ms=33, decay=0.45, mix=0.5,
                freq_shift=True, **_core.pcm())
            self.flutter.play(source)
            chain_source = self.flutter
        self.node = audiofreeverb.Freeverb(
            roomsize=roomsize, damp=damp, mix=mix, **_core.pcm())
        self.node.play(chain_source)
        self.output = self.node

    def set_mix(self, mix):
        self.node.mix = mix


class ConvolutionReverb(_core.Effect):
    """A reverb built by convolving with an impulse response.

    With `impulse` given -- int16 frames, interleaved if `impulse_channels`
    is 2 -- this is the room that impulse was measured in. With no impulse it
    synthesizes decaying noise, which is a serviceable hall and, more to the
    point, is what makes the class usable with nothing to load::

        verb = ConvolutionReverb(source, seconds=1.2, stereo=True)
        verb.set_macro(0, 100)          # Decay, MIDI scale
        verb.set_macro(4, 40)           # Mix

    **`seconds` is an allocation, not a setting.** It fixes how long an
    impulse this instance can ever hold, because the storage is carved once
    and the audio path may already be pulling. The Decay macro then works
    *within* that allocation, which is why it is a proportion (0.05..1.0)
    rather than a time: on a fixed length, size is a fraction. `.seconds`
    reports the allocation and `.decay_seconds` what the knob currently means.

    **What it costs.** Every partition is 256 taps, and both the arithmetic
    and the memory grow linearly with the count. One second at 48 kHz is 188
    partitions: about 1.2 MB, and on the order of 150 MFLOPS to run in real
    time. That is a desktop or a render, not a microcontroller. The MCU-scale
    use of convolution on this palette is a *short* impulse -- see
    `drive.CabinetSim`, which is 1024 taps and about 3 MFLOPS.

    The output trails the input by `audioconvolve.FRAMES` (5.3 ms at 48 kHz);
    see the audioconvolve docstring for why that is inherent here.
    """

    NAME = 'ConvolutionReverb'
    DISPLAY_NAME = 'Convolution Reverb'
    CATEGORIES = ('Reverb',)
    VERSION = '0.0.1'

    MACRO_LABELS = ("Decay", "Damping", "Predelay", "Diffusion", "Mix")
    MACRO_MODES = {
        0: "UNIPOLAR",
        1: "UNIPOLAR",
        2: "UNIPOLAR",
        3: "UNIPOLAR",
        4: "UNIPOLAR",
    }
    _MACRO_RANGES = (
        (0.05, 1.0),                 # fraction of `seconds`
        (500.0, 16000.0, "log"),
        (0.0, 120.0),
        (0.0, 60.0),
        (0.0, 1.0),
    )
    PATCHES = {
        0: ("Natural Room", (127, 91, 0, 0, 38)),
        1: ("Small Room", (26, 76, 4, 6, 45)),
        2: ("Concert Hall", (127, 96, 30, 25, 51)),
        3: ("Dark Chamber", (79, 51, 13, 19, 45)),
        4: ("Bright Plate", (98, 118, 0, 4, 57)),
        5: ("Cathedral", (127, 83, 51, 38, 64)),
        6: ("Gated Slap", (18, 108, 21, 0, 76)),
    }

    def __init__(self, source, seconds=1.0, stereo=True, decay=1.0,
                 damping_hz=6000.0, predelay_ms=0.0, diffusion_ms=0.0,
                 seed=1, mix=0.3, impulse=None, impulse_channels=1,
                 gain=1.0, patch=None):
        if audioconvolve is None:
            raise ImportError(
                "ConvolutionReverb needs the audioconvolve module, which a "
                "stock CircuitPython board does not have")
        rate = _core.sample_rate()
        self.seconds = float(seconds)
        self._seed = int(seed)
        self._taps = max(int(self.seconds * rate), audioconvolve.FRAMES)
        self.node = audioconvolve.Convolver(
            max_taps=self._taps, ir_channels=2 if stereo else 1,
            sample_rate=rate)
        self.node.play(source)
        self.output = self.node

        # A loaded impulse is the room; the macros that would shape a
        # synthetic one stop applying, and saying so is better than letting a
        # Decay knob look connected while it does nothing.
        self.measured = impulse is not None
        if self.measured:
            self.node.load(impulse, impulse_channels, gain)

        # One synthesis, not one per knob: _init_macros walks every macro in
        # turn, and rebuilding a second of impulse five times over would be
        # the most expensive thing this constructor does.
        self._ready = False
        self._init_macros(
            (decay, damping_hz, predelay_ms, diffusion_ms, mix), patch)
        self._ready = True
        self._rebuild()

    @property
    def decay_seconds(self):
        """What the Decay knob currently stands for, in seconds."""
        return self.macro(0) * self.seconds

    def set_mix(self, mix):
        self.node.set(mix=mix)

    def program_change(self, index):
        # Suppress the per-macro rebuild and do one at the end. A patch moves
        # every knob, and four of the five reshape the impulse.
        if int(index) not in self.PATCHES:
            return
        self._ready = False
        try:
            _core.Effect.program_change(self, index)
        finally:
            self._ready = True
        self._rebuild()

    def _rebuild(self):
        if not self._ready or self.measured:
            return
        self.node.synthesize(
            decay=self.decay_seconds, damping_hz=self.macro(1),
            predelay_ms=self.macro(2), diffusion_ms=self.macro(3),
            seed=self._seed)

    def _apply_macro(self, index, position):
        if index == 4:
            self.node.set(mix=_core.macro_value(self._MACRO_RANGES[4], position))
        else:
            self._rebuild()
