"""A table-driven waveshaper that does its shaping above the sample rate.

Not a CircuitPython module, and not from micropython-vst3's engine either --
audioif adds it. `audiofilters.Distortion` exists upstream and runs one of
four fixed curves at the base rate; this one takes the curve as data and
oversamples:

    from array import array
    import audioshaper

    # a soft knee at +-0.6, computed once, on the desktop
    points = 2048
    curve = array("h")
    for i in range(points):
        x = -1.0 + 2.0 * i / (points - 1)
        y = x if abs(x) <= 0.6 else (x / abs(x)) * (
            0.6 + 0.4 * (1.0 - 2.718281828 ** (-3.0 * (abs(x) - 0.6) / 0.4)))
        curve.append(max(-32768, min(32767, int(round(y * 32767)))))

    drive = audioshaper.Waveshaper(
        sample_rate=48000, curve=curve, oversample=4,
        pre_gain=8.0, post_gain=0.5, mix=1.0)
    drive.play(source)
    audio_out.play(drive)

The curve is where the circuit lives: diodes in a feedback loop, diodes to
ground, a biased germanium pair are each a different shape, and none of them
is one of `Distortion`'s four. It is computed once, on CPython, and shipped
as data -- never rebuilt on the target, whose float is single-precision
where the desktop's is double, so a table built on a board would be a
different table.

`pre_gain` is the drive knob: gain into one normalised curve, rather than a
curve rebuilt on every knob move. `bias` moves the operating point. A bias
that has to move *per sample* is a second stream summed in front of this
node -- `audiomixer.Mixer` adds sample by sample -- not an argument here.

`oversample` (1, 2, 4 or 8) is how far above the sample rate the shaping
happens, between a matched pair of polyphase all-pass half-bands. It is the
whole reason this module exists: a nonlinearity makes harmonics above
Nyquist and they fold back onto the signal, and nothing else in audioif
resamples at all.

`hysteresis` is off by default and is the one thing a table cannot do: give
the curve a memory, so a slow triangle in and out traces two different paths
and encloses an area. At zero the node is a static table, sample for sample.

A new module rather than arguments on `Distortion`, deliberately: an argument
added to audioif's copy of a CircuitPython module would not exist on a stock
board, so an effect written against it would silently be a different effect
there. This either installs whole or is absent and says so on import.
"""

from audiocore import (
    GET_BUFFER_ERROR, GET_BUFFER_MORE_DATA, _AudioSample, get_buffer,
)
import _audioif

FRAMES = _audioif.SHAPER_FRAMES
MAX_OVERSAMPLE = _audioif.SHAPER_MAX_OVERSAMPLE

#: Option name -> the native configure() slot. Kept in the order
#: shared/audioif_shaper.h declares, which is the order the MicroPython
#: bindings list them in too. Append only, never renumber.
_OPTIONS = {
    "pre_gain": 0,
    "bias": 1,
    "post_gain": 2,
    "mix": 3,
    "hysteresis": 4,
    "hysteresis_width": 5,
    "hysteresis_bias": 6,
}

#: Group delay of the whole up/shape/down chain, in samples at the base rate,
#: per oversampling factor. Measured on the built extension rather than
#: derived: a 200 Hz..5 kHz sine in, the output's phase against the input's,
#: at 48 kHz (tools/design_halfband.py holds the filter design the numbers
#: come out of). It is flat across the audio band to within a hundredth of a
#: sample, and the magnitude response over 200 Hz..18 kHz is flat to within
#: 0.001 dB. A component reporting `latency_samples` should report the entry
#: for the factor it built with -- it is small, but it is not zero.
GROUP_DELAY_SAMPLES = {1: 0.0, 2: 2.2, 4: 3.3, 8: 3.9}


class Waveshaper(_AudioSample):
    def __init__(self, sample_rate=48000, curve=None, oversample=4,
                 **options):
        channel_count = int(options.pop("channel_count", 2))
        if channel_count not in (1, 2):
            raise ValueError("channel_count must be 1 or 2")
        # Powers of two only, and no higher than 8: the state is a fixed
        # number of half-band stages, and rounding a stray 3 down to 2 would
        # be a different effect than the caller asked for, quietly.
        oversample = int(options.pop("oversample", oversample))
        if oversample not in (1, 2, 4, 8):
            raise ValueError("oversample must be 1, 2, 4 or 8")
        curve = options.pop("curve", curve)
        if curve is None:
            raise ValueError("curve is required")
        options.pop("sample_rate", None)
        self.sample_rate = int(sample_rate)
        self.bits_per_sample = 16
        self.channel_count = channel_count
        self.samples_signed = True
        self.single_buffer = False
        self.max_buffer_length = FRAMES * 2 * channel_count
        self.oversample = oversample
        self._deinited = False
        self._source = None
        self._pending = b""
        self._state = _audioif.WaveshaperState(
            sample_rate=self.sample_rate, oversample=oversample,
            channel_count=channel_count)
        self._state.load_curve(bytes(memoryview(curve).cast("B")))
        self._apply(options)

    def _apply(self, options):
        for name, value in options.items():
            if name == "curve":
                self._state.load_curve(bytes(memoryview(value).cast("B")))
                continue
            slot = _OPTIONS.get(name)
            if slot is None:
                raise TypeError("unknown Waveshaper option %r" % (name,))
            self._state.configure(slot, float(value))
        self._state.finish()

    def set(self, **options):
        """Change settings mid-stream. The half-band memories and the play
        position keep their contents; only what the node does to them
        changes."""
        self._check()
        self._apply(options)

    def clear(self):
        """Empty the half-band memories and the play position. That is the
        whole of this node's state: it has no delay line."""
        self._check()
        self._state.reset()

    @property
    def playing(self):
        return self._source is not None

    def play(self, sample, *, loop=False):
        self._check()
        self._source = sample
        self._pending = b""

    def stop(self):
        self._source = None
        self._pending = b""

    def _release(self):
        self.stop()

    def _reset_buffer(self, single_channel_output=False, audio_channel=0):
        self._check()
        self._pending = b""
        self._state.reset()

    def _get_buffer(self, single_channel_output=False, audio_channel=0):
        self._check()
        output = bytearray()
        produced = 0
        while produced < FRAMES:
            if not self._pending:
                if self._source is None:
                    break
                result, data = get_buffer(self._source, False, 0)
                data = bytes(data)
                if result == GET_BUFFER_ERROR or len(data) < 2 * self.channel_count:
                    break
                width = 2 * self.channel_count
                self._pending = data[:len(data) // width * width]
            width = 2 * self.channel_count
            run = min(FRAMES - produced, len(self._pending) // width)
            output += self._state.process(self._pending[:run * width])
            self._pending = self._pending[run * width:]
            produced += run
        # A starved chain gets silence rather than a short block: this node
        # sits in the middle of a live graph and never reports itself
        # finished. It has no tail of its own -- no delay line, no
        # reverberation -- so silence in really is silence out, once the
        # half-bands have rung down.
        if produced == 0:
            return GET_BUFFER_MORE_DATA, memoryview(
                bytes(FRAMES * 2 * self.channel_count))
        return GET_BUFFER_MORE_DATA, memoryview(bytes(output))


__all__ = ("Waveshaper",)
