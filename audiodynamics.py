"""Envelope-follower dynamics processing: compression, limiting, downward
expansion, gating and transient shaping.

Unlike the rest of this package, `audiodynamics` is not a CircuitPython module.
It comes from micropython-vst3's `vstaudio` engine, which grew it for its
effects library, and it is provided here for MicroPython, CPython and patched
CircuitPython alike.

    node = audiodynamics.Dynamics(
        audiodynamics.DYN_COMPRESS, sample_rate=48000,
        threshold_db=-24, ratio=4, knee_db=6, attack_ms=10, release_ms=120)
    node.play(source)          # any audiosample: 16-bit signed stereo
    audio_out.play(node)

`sidechain_hz` high-passes the detector without touching the audio, which is
how the de-essers in the effects library are built. `gain_reduction_db()`
reports what the last processed frame was reduced by, for a meter.
"""

from audiocore import (
    GET_BUFFER_ERROR, GET_BUFFER_MORE_DATA, _AudioSample, get_buffer,
)
import _audioif

DYN_COMPRESS = 0
DYN_LIMIT = 1
DYN_EXPAND = 2
DYN_GATE = 3
DYN_TRANSIENT = 4

#: Option name -> the native configure() slot. Kept in the order
#: shared/audioif_dynamics.h declares, which is the order the MicroPython
#: bindings list them in too.
_OPTIONS = {
    "threshold_db": 0,
    "ratio": 1,
    "knee_db": 2,
    "makeup_db": 3,
    "attack_ms": 4,
    "release_ms": 5,
    "attack_gain_db": 6,
    "sustain_gain_db": 7,
    "sidechain_hz": 8,
}

FRAMES = _audioif.DYNAMICS_FRAMES


class Dynamics(_AudioSample):
    def __init__(self, mode=DYN_COMPRESS, **options):
        sample_rate = int(options.pop("sample_rate", 48000))
        self.sample_rate = sample_rate
        self.bits_per_sample = 16
        self.channel_count = 2
        self.samples_signed = True
        self.single_buffer = False
        self.max_buffer_length = FRAMES * 4
        self._deinited = False
        self._source = None
        self._pending = b""
        self._state = _audioif.DynamicsState(mode=int(mode),
                                             sample_rate=sample_rate)
        self._apply(options)
        # Only now do the unset attack/release times fall back to their
        # defaults - see shared/audioif_dynamics.h for why that is a separate
        # step rather than part of the initial state.
        self._state.finish()

    def _apply(self, options):
        rate = options.pop("sample_rate", None)
        if rate is not None:
            # First, whatever order the caller wrote them: the millisecond
            # options are converted against it.
            self.sample_rate = int(rate)
            self._state.set_sample_rate(self.sample_rate)
        for name, value in options.items():
            slot = _OPTIONS.get(name)
            if slot is None:
                raise TypeError("unknown Dynamics option %r" % (name,))
            self._state.configure(slot, float(value))

    def set(self, **options):
        """Change settings mid-stream. The detector keeps its memory."""
        self._check()
        self._apply(options)

    def gain_reduction_db(self):
        """Gain applied to the most recent frame, in dB (negative = cut)."""
        return self._state.gain_reduction_db

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
        # The sidechain filter's memory and the last reported gain reduction
        # deliberately survive; only the detector envelopes are dropped.
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
                if result == GET_BUFFER_ERROR or len(data) < 4:
                    break
                self._pending = data[:len(data) // 4 * 4]
            run = min(FRAMES - produced, len(self._pending) // 4)
            output += self._state.process(self._pending[:run * 4])
            self._pending = self._pending[run * 4:]
            produced += run
        # A starved chain gets silence rather than a short block: this node
        # sits in the middle of a live graph and never reports itself finished.
        if produced == 0:
            return GET_BUFFER_MORE_DATA, memoryview(bytes(FRAMES * 4))
        return GET_BUFFER_MORE_DATA, memoryview(bytes(output))


__all__ = ("Dynamics", "DYN_COMPRESS", "DYN_LIMIT", "DYN_EXPAND", "DYN_GATE",
           "DYN_TRANSIENT")
