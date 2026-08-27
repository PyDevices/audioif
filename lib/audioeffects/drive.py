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
"""

import audiofilters
import audiomixer
import audioroute
import synthio

from . import _core

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
        self.output = self.tone


class Distortion(_core.Effect):
    """Hard clipping."""

    def __init__(self, source, drive=0.7, mix=1.0):
        self.node = audiofilters.Distortion(
            drive=drive, mode=_DM.CLIP, soft_clip=False,
            pre_gain=6.0, post_gain=-6.0, mix=mix, **_core.pcm())
        self.node.play(source)
        self.output = self.node


class Fuzz(_core.Effect):
    """Everything into the ceiling: the waveform leaves as a square."""

    def __init__(self, source, drive=0.95, mix=1.0):
        self.node = audiofilters.Distortion(
            drive=drive, mode=_DM.CLIP, soft_clip=False,
            pre_gain=18.0, post_gain=-9.0, mix=mix, **_core.pcm())
        self.node.play(source)
        self.output = self.node


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
        self.output = self.node
        if not shelves:
            self.tone = None
            return
        self.tone = audiofilters.Filter(
            filter=[synthio.Biquad(shelf_mode, _core.check_hz(hz), Q=0.707,
                                   A=_core.db_to_amplitude(gain_db * amount))
                    for shelf_mode, hz, gain_db in shelves],
            **_core.pcm())
        self.tone.play(self.node)
        self.output = self.tone


class Bitcrusher(_core.Effect):
    """Bit-depth reduction. `bits` says how many of the sixteen survive
    (2..16) and is the parameter worth reaching for; `crush` is the same
    control as a 0..1 knob, and `bits` wins when both are given.

    Sample-rate reduction - the other half of what a lo-fi box does - is
    not here. The engine's LOFI mode masks low bits and nothing else;
    decimation needs a sample-and-hold the palette does not have.
    """

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
        self.output = self.node


class Exciter(_core.Effect):
    """New highs synthesized from the source: a high-passed branch is
    overdriven (generating harmonics) and blended back in under the dry."""

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
        self.output = self.mixer
