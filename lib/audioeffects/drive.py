"""Drive, distortion, and saturation over the engine's Distortion node
(CLIP, OVERDRIVE, LOFI, WAVESHAPE modes).

Two facts about that node shape everything here. First, its `drive`
argument does nothing in OVERDRIVE mode - the curve is a fixed shape, and
the only way to push harder into it is `pre_gain` (see `_push`). Second,
the two curves differ in symmetry, which is what makes the saturation
characters below distinguishable rather than cosmetic: OVERDRIVE is
asymmetric and so generates even harmonics (a 2nd about level with the
3rd), while WAVESHAPE is odd-symmetric and generates no even harmonics at
all - measured 120 dB down, i.e. the numerical floor.

`CabinetSim` at the end is the exception: it is a convolution rather than a
curve, because what a speaker does to a signal is a response, not a
nonlinearity. It sits here because it belongs after the others in a chain.
"""

VENDOR = "PyDevices"

import array
import math

import audiofilters
import audiomixer
import audioroute
import synthio

from . import _core

try:
    import audioconvolve
except ImportError:      # a stock CircuitPython board, or an old audioif
    audioconvolve = None

_DM = audiofilters.DistortionMode
_FM = synthio.FilterMode


def _push(drive, unity):
    """A 0..1 drive knob as (pre_gain_db, post_gain_db).

    `unity` is the drive value at which the curve is hit at its natural
    level, so a class can keep its own historical default sounding the way
    it always has. Off that point the signal is pushed into the curve, or
    backed off it, and the level is put back afterwards - so turning drive
    up changes how hard the curve works, not how loud the result is.
    """
    pre = (float(drive) - unity) * 24.0
    return pre, -pre


class Overdrive(_core.Effect):
    """Soft clipping with a tone control - tube breakup territory.

    `drive` is how hard the signal is pushed into the curve, and the output
    level is compensated, so turning it up buys harmonics rather than
    volume. It used to do nothing at all; see the module docstring.
    """

    NAME = 'Overdrive'
    DISPLAY_NAME = 'Overdrive'
    CATEGORIES = ('Distortion',)
    VERSION = '0.0.1'
    MACRO_LABELS = ()
    MACRO_MODES = {}
    PATCHES = {0: ("Default", ())}

    def __init__(self, source, drive=0.4, tone_hz=4500.0, mix=1.0):
        # OVERDRIVE ignores the node's own drive argument, so passing it
        # through - as this class used to - left the knob inert. Drive is
        # pre-gain into a fixed curve, with the level put back after.
        pre, post = _push(drive, 0.4)
        self.node = audiofilters.Distortion(
            mode=_DM.OVERDRIVE, soft_clip=True, pre_gain=pre,
            post_gain=post - 3.0, mix=mix, **_core.pcm())
        self.node.play(source)
        self.tone = audiofilters.Filter(
            filter=synthio.Biquad(_FM.LOW_PASS, _core.check_hz(tone_hz),
                                  Q=0.707),
            **_core.pcm())
        self.tone.play(self.node)
        self._output = self.tone


class Distortion(_core.Effect):
    """Hard clipping."""

    NAME = 'Distortion'
    DISPLAY_NAME = 'Distortion'
    CATEGORIES = ('Distortion',)
    VERSION = '0.0.1'
    MACRO_LABELS = ()
    MACRO_MODES = {}
    PATCHES = {0: ("Default", ())}

    def __init__(self, source, drive=0.7, mix=1.0):
        self.node = audiofilters.Distortion(
            drive=drive, mode=_DM.CLIP, soft_clip=False,
            pre_gain=6.0, post_gain=-6.0, mix=mix, **_core.pcm())
        self.node.play(source)
        self._output = self.node


class Fuzz(_core.Effect):
    """Everything into the ceiling: the waveform leaves as a square."""

    NAME = 'Fuzz'
    DISPLAY_NAME = 'Fuzz'
    CATEGORIES = ('Distortion',)
    VERSION = '0.0.1'
    MACRO_LABELS = ()
    MACRO_MODES = {}
    PATCHES = {0: ("Default", ())}

    def __init__(self, source, drive=0.95, mix=1.0):
        self.node = audiofilters.Distortion(
            drive=drive, mode=_DM.CLIP, soft_clip=False,
            pre_gain=18.0, post_gain=-9.0, mix=mix, **_core.pcm())
        self.node.play(source)
        self._output = self.node


#: The three analog-gear characters, as (mode, curve, makeup_db, shelves).
#: `curve` is the node's own drive for the modes that have one (OVERDRIVE
#: does not). `makeup_db` levels the three against each other, measured on
#: a -12 dBFS sine, so switching character changes the colour and not the
#: gain. `shelves` is the tone shaping that comes with the medium, as
#: (filter mode, frequency, gain at full amount).
#:
#: The low shelves here would have been meaningless a phase ago: the
#: engine's biquads were Q15 and anything below roughly 300 Hz quantized
#: into nonsense, so "tape" had a top octave and no head bump. They are
#: accurate to a hundredth of a decibel now - see README, "A note on how
#: low a filter can go" - which is what lets the two mediums differ at both
#: ends rather than only above 10 kHz.
_CHARACTERS = {
    # Asymmetric, so a 2nd harmonic level with the 3rd: the valve
    # signature. This is also the chain this class has always built, which
    # is why it is the default and why its makeup is zero - existing mixes
    # keep their sound, and the other two are matched to it.
    "tube": (_DM.OVERDRIVE, None, 0.0, ()),
    # Odd-symmetric curve for 3rd-harmonic thickening, the head bump a tape
    # machine gets from its own record/replay geometry, and the gap loss
    # that costs it the top octave.
    "tape": (_DM.WAVESHAPE, 0.18, -2.6, ((_FM.LOW_SHELF, 80.0, 1.5),
                                         (_FM.HIGH_SHELF, 10000.0, -3.0))),
    # The gentlest of the three - a desk sums through iron without
    # announcing it - with a touch of air on top.
    "console": (_DM.WAVESHAPE, 0.05, -1.06,
                ((_FM.HIGH_SHELF, 12000.0, 1.0),)),
}


class Saturation(_core.Effect):
    """Subtle harmonic thickening: a soft curve blended mostly dry.

    `character` picks the analog medium being imitated - "tube" (even
    harmonics, the default), "tape" (odd harmonics and a darker top), or
    "console" (the mildest, with a little air). `amount` is the dry/wet
    blend and scales the whole character, tone shaping included, so a
    quarter of the way in is a quarter of the effect rather than a quarter
    of the harmonics and all of the EQ. `drive` pushes harder into the
    curve without changing the output level.
    """

    NAME = 'Saturation'
    DISPLAY_NAME = 'Saturation'
    CATEGORIES = ('Distortion',)
    VERSION = '0.0.1'
    MACRO_LABELS = ()
    MACRO_MODES = {}
    PATCHES = {0: ("Default", ())}

    def __init__(self, source, amount=0.25, character="tube", drive=0.35):
        try:
            mode, curve, makeup_db, shelves = _CHARACTERS[character]
        except KeyError:
            raise ValueError("character must be one of %s, not %r"
                             % ("/".join(sorted(_CHARACTERS)), character))
        self.character = character
        pre, post = _push(drive, 0.35)
        arguments = {"mode": mode, "soft_clip": True, "pre_gain": pre,
                     "post_gain": post + makeup_db, "mix": amount}
        if curve is not None:
            arguments["drive"] = curve
        self.node = audiofilters.Distortion(**dict(_core.pcm(), **arguments))
        self.node.play(source)
        self._output = self.node
        if not shelves:
            self.tone = None
            return
        self.tone = audiofilters.Filter(
            filter=[synthio.Biquad(shelf_mode, _core.check_hz(hz), Q=0.707,
                                   A=_core.db_to_amplitude(gain_db * amount))
                    for shelf_mode, hz, gain_db in shelves],
            **_core.pcm())
        self.tone.play(self.node)
        self._output = self.tone


class Bitcrusher(_core.Effect):
    """Bit-depth reduction. `bits` says how many of the sixteen survive
    (2..16) and is the parameter worth reaching for; `crush` is the same
    control as a 0..1 knob, and `bits` wins when both are given.

    Sample-rate reduction - the other half of what a lo-fi box does - is
    not here. The engine's LOFI mode masks low bits and nothing else;
    decimation needs a sample-and-hold the palette does not have.
    """

    NAME = 'Bitcrusher'
    DISPLAY_NAME = 'Bitcrusher'
    CATEGORIES = ('Distortion',)
    VERSION = '0.0.1'
    MACRO_LABELS = ()
    MACRO_MODES = {}
    PATCHES = {0: ("Default", ())}

    #: LOFI masks off `round(drive * 14)` of a sample's low bits, so the
    #: knob spans 16 bits down to 2 and no further.
    BIT_RANGE = (2, 16)

    def __init__(self, source, crush=0.6, mix=1.0, bits=None):
        if bits is not None:
            low, high = self.BIT_RANGE
            if not low <= bits <= high:
                raise ValueError("bits must be %d..%d, not %r"
                                 % (low, high, bits))
            crush = (high - bits) / float(high - low)
        self.bits = self.BIT_RANGE[1] - round(crush * 14.0)
        self.node = audiofilters.Distortion(
            drive=crush, mode=_DM.LOFI, mix=mix, **_core.pcm())
        self.node.play(source)
        self._output = self.node


class Exciter(_core.Effect):
    """New highs synthesized from the source: a high-passed branch is
    overdriven (generating harmonics) and blended back in under the dry."""

    NAME = 'Exciter'
    DISPLAY_NAME = 'Exciter'
    CATEGORIES = ('Distortion',)
    VERSION = '0.0.1'
    MACRO_LABELS = ()
    MACRO_MODES = {}
    PATCHES = {0: ("Default", ())}

    def __init__(self, source, frequency=3000.0, amount=0.3):
        split = audioroute.Splitter(source, taps=2)
        self.highs = audiofilters.Filter(
            filter=synthio.Biquad(_FM.HIGH_PASS, _core.check_hz(frequency),
                                  Q=0.707),
            **_core.pcm())
        self.highs.play(split.tap(1))
        # No drive argument: OVERDRIVE ignores it. The branch is driven by
        # how loud the high-passed signal arrives, and blended by `amount`.
        self.harmonics = audiofilters.Distortion(
            mode=_DM.OVERDRIVE, soft_clip=True, **_core.pcm())
        self.harmonics.play(self.highs)
        self.mixer = audiomixer.Mixer(voice_count=2, **_core.pcm(1024))
        self.mixer.voice[0].play(split.tap(0))
        self.mixer.voice[0].level = 1.0
        self.mixer.voice[1].play(self.harmonics)
        self.mixer.voice[1].level = amount
        self.splitter = split
        self._output = self.mixer


class CabinetSim(_core.Effect):
    """A speaker cabinet, by convolution with a short synthetic impulse.

    This is the microcontroller-scale use of `audioconvolve`: 1024 taps is
    four partitions, roughly 3 MFLOPS at 48 kHz, against the ~150 a second of
    `reverb.ConvolutionReverb` costs. A cabinet is a short response, and a
    short response is cheap.

    What a guitar cabinet does is mostly a *shape*: nothing below about
    70 Hz, a bump where the cone and the box argue, a presence peak a couple
    of kilohertz up, and a steep roll-off above about 5 kHz where the paper
    stops following the coil. So the impulse is a filter's impulse response --
    the sections below, run over a unit impulse -- rather than a sum of
    ringing resonances, which would be a bell rather than a box.

    It is a designed response, not a measured one. Hand a measured one to
    `reverb.ConvolutionReverb`, or to `audioconvolve` directly, when you want
    a cabinet in particular rather than a cabinet in general.

    Every knob but Mix rebuilds the impulse, which is a few thousand
    multiplies. Fine on a knob move, wrong to automate per block.
    """

    NAME = 'CabinetSim'
    DISPLAY_NAME = 'Cabinet Sim'
    CATEGORIES = ('Distortion',)
    VERSION = '0.0.1'

    #: Taps in the impulse. 21 ms at 48 kHz, which is long enough for the low
    #: end to settle and short enough to stay cheap.
    TAPS = 1024

    #: Where the response is sampled to find its peak, for normalizing. Log
    #: spaced over the audible band; 48 points resolve a Q-1.5 bell to well
    #: under a decibel, and the whole sweep is a few hundred multiplies.
    _PROBES = 48

    MACRO_LABELS = ("Body", "Presence", "Top", "Mix")
    MACRO_MODES = {
        0: "UNIPOLAR",
        1: "UNIPOLAR",
        2: "UNIPOLAR",
        3: "UNIPOLAR",
    }
    _MACRO_RANGES = (
        (60.0, 140.0, "log"),        # cone/box resonance
        (1500.0, 6000.0, "log"),     # presence peak
        (2500.0, 12000.0, "log"),    # where the paper gives up
        (0.0, 1.0),
    )
    PATCHES = {
        0: ("Studio Cabinet", (77, 57, 56, 127)),
        1: ("4x12 Stack", (46, 74, 47, 127)),
        2: ("1x12 Combo", (99, 55, 74, 127)),
        3: ("Tweed Box", (117, 40, 88, 127)),
        4: ("Bass Rig", (12, 20, 25, 127)),
        5: ("Broken Radio", (127, 40, 6, 127)),
    }

    def __init__(self, source, body_hz=100.0, presence_hz=2800.0,
                 top_hz=5000.0, mix=1.0, patch=None):
        if audioconvolve is None:
            raise ImportError(
                "CabinetSim needs the audioconvolve module, which a stock "
                "CircuitPython board does not have")
        self.node = audioconvolve.Convolver(
            max_taps=self.TAPS, ir_channels=1,
            sample_rate=_core.sample_rate(),
            channel_count=_core.channel_count())
        self.node.play(source)
        self._output = self.node
        # One impulse build at the end rather than one per knob.
        self._ready = False
        self._init_macros((body_hz, presence_hz, top_hz, mix), patch)
        self._ready = True
        self._rebuild()

    def set_mix(self, mix):
        self.node.set(mix=mix)

    def program_change(self, index, channel=0, note_id=-1,
                       sample_position=0):
        if int(index) not in self.PATCHES:
            return
        self._ready = False
        try:
            _core.Effect.program_change(self, index, channel=channel,
                                         note_id=note_id,
                                         sample_position=sample_position)
        finally:
            self._ready = True
        self._rebuild()

    def _sections(self, rate):
        """RBJ biquads, as (b0, b1, b2, a1, a2) with a0 divided out.

        Written here rather than taken from a Biquad node because this needs
        the *coefficients*, to run in float over an impulse and to evaluate a
        magnitude response - neither of which the engine's filter exposes.
        """
        body, presence, top = self.macro(0), self.macro(1), self.macro(2)
        top = min(top, rate * 0.45)
        designs = (
            # The roll-off sits below the box resonance rather than at a fixed
            # frequency: a bigger box resonates lower *and* passes lower, and
            # tying the two means one knob moves the whole bottom end together.
            ("high_pass", body * 0.7, 0.707, 0.0),
            ("peaking", body, 1.1, 5.0),
            ("peaking", presence, 1.4, 4.0),
            # Twice, for the 24 dB/octave a cone actually rolls off at.
            ("low_pass", top, 0.707, 0.0),
            ("low_pass", top, 0.707, 0.0),
        )
        sections = []
        for kind, frequency, q, gain_db in designs:
            w0 = 2.0 * math.pi * frequency / rate
            cosine, sine = math.cos(w0), math.sin(w0)
            alpha = sine / (2.0 * q)
            if kind == "low_pass":
                b0 = b2 = (1.0 - cosine) * 0.5
                b1 = 1.0 - cosine
                a0, a1, a2 = 1.0 + alpha, -2.0 * cosine, 1.0 - alpha
            elif kind == "high_pass":
                b0 = b2 = (1.0 + cosine) * 0.5
                b1 = -(1.0 + cosine)
                a0, a1, a2 = 1.0 + alpha, -2.0 * cosine, 1.0 - alpha
            else:
                amplitude = _core.db_to_amplitude(gain_db)
                b0 = 1.0 + alpha * amplitude
                b1 = -2.0 * cosine
                b2 = 1.0 - alpha * amplitude
                a0 = 1.0 + alpha / amplitude
                a1 = -2.0 * cosine
                a2 = 1.0 - alpha / amplitude
            sections.append((b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0))
        return sections

    def _peak_response(self, sections, rate):
        """The largest gain the cascade has anywhere in the band.

        An impulse response has to be normalized by what it does to a signal,
        not by how tall its own tallest tap is - two peaking sections and a
        resonance make a cabinet that is several times unity at its bump, and
        a cabinet that multiplies everything by four is a cabinet that clips.
        """
        peak = 0.0
        for probe in range(self._PROBES):
            frequency = _core.logmap(probe / (self._PROBES - 1.0), 20.0,
                                     min(20000.0, rate * 0.49))
            w0 = 2.0 * math.pi * frequency / rate
            cos1, sin1 = math.cos(w0), math.sin(w0)
            cos2, sin2 = math.cos(2.0 * w0), math.sin(2.0 * w0)
            magnitude = 1.0
            for b0, b1, b2, a1, a2 in sections:
                # e^-jw = cos - j sin, so the imaginary parts pick up a minus.
                nr = b0 + b1 * cos1 + b2 * cos2
                ni = -(b1 * sin1 + b2 * sin2)
                dr = 1.0 + a1 * cos1 + a2 * cos2
                di = -(a1 * sin1 + a2 * sin2)
                denominator = dr * dr + di * di
                if denominator <= 0.0:
                    continue
                magnitude *= math.sqrt((nr * nr + ni * ni) / denominator)
            if magnitude > peak:
                peak = magnitude
        return peak

    def _rebuild(self):
        if not self._ready:
            return
        rate = float(_core.sample_rate())
        sections = self._sections(rate)

        # The cascade's impulse response, section by section over the whole
        # buffer. Direct form I, in float: the taps are quantized once at the
        # end rather than between every section.
        values = [0.0] * self.TAPS
        values[0] = 1.0
        for b0, b1, b2, a1, a2 in sections:
            x1 = x2 = y1 = y2 = 0.0
            for index in range(self.TAPS):
                x0 = values[index]
                y0 = b0 * x0 + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
                values[index] = y0
                x2, x1 = x1, x0
                y2, y1 = y1, y0

        peak = 0.0
        for value in values:
            magnitude = value if value >= 0.0 else -value
            if magnitude > peak:
                peak = magnitude
        # The taps go in at full scale so the int16 they are stored as keeps
        # its resolution; the level correction rides on `gain`, which is
        # applied in float on the way to the transform.
        # A list, not `array("h", bytes(...))`: CPython reads a bytes
        # initializer as raw storage and MicroPython iterates it, which would
        # give twice the taps there.
        taps = array.array("h", [0] * self.TAPS)
        scale = 32767.0 / peak if peak > 0.0 else 0.0
        for index in range(self.TAPS):
            taps[index] = int(values[index] * scale)
        response = self._peak_response(sections, rate)
        gain = (32768.0 / (scale * response)
                if scale > 0.0 and response > 0.0 else 0.0)
        self.node.load(taps, 1, gain)

    def _apply_macro(self, index, position):
        if index == 3:
            self.node.set(mix=_core.macro_value(self._MACRO_RANGES[3], position))
        else:
            self._rebuild()
