"""Arithmetic on audio streams: one stream multiplied by another.

Unlike most of this package, `audiomath` is not a CircuitPython module and did
not come from micropython-vst3's engine either - audioif adds it. Nothing else
in the palette multiplies two *streams*: `synthio` rings a note against an
oscillator, which cannot reach a microphone, a sampler, or the output of
another effect, and an LFO-driven parameter updates once per block (about
187 Hz at 48 kHz) where a ring modulator wants hundreds of hertz.

    carrier = audiocore.RawSample(one_cycle_of_sine, sample_rate=48000,
                                  channel_count=2)
    node = audiomath.Multiply(source, carrier, mix=1.0)
    audio_out.play(node)

The two inputs fail in opposite directions, deliberately. A source that runs
dry gives silence, as every other effect here does; a modulator that is absent
or has stopped lets the signal through untouched, because multiplying by
nothing and multiplying by zero must not mean the same thing.
"""

from audiocore import (
    GET_BUFFER_ERROR, GET_BUFFER_MORE_DATA, _AudioSample, get_buffer,
)
import _audioif

FRAMES = _audioif.MULTIPLY_FRAMES


class Multiply(_AudioSample):
    def __init__(self, source=None, modulator=None, mix=1.0,
                 sample_rate=48000):
        self.sample_rate = int(sample_rate)
        self.bits_per_sample = 16
        self.channel_count = 2
        self.samples_signed = True
        self.single_buffer = False
        self.max_buffer_length = FRAMES * 4
        self._deinited = False
        self._source = source
        self._modulator = modulator
        self._mix = 1.0
        self._pending_source = b""
        self._pending_modulator = b""
        self._apply({"mix": mix})

    def _apply(self, options):
        for name, value in options.items():
            if name != "mix":
                raise TypeError("unknown Multiply option %r" % (name,))
            self._mix = min(1.0, max(0.0, float(value)))

    def set(self, **options):
        """Change settings mid-stream."""
        self._check()
        self._apply(options)

    @property
    def playing(self):
        return self._source is not None

    def play(self, sample, *, loop=False):
        """Set the signal - the input that gets multiplied."""
        self._check()
        self._source = sample
        self._pending_source = b""

    def modulate(self, sample):
        """Set what to multiply it by."""
        self._check()
        self._modulator = sample
        self._pending_modulator = b""

    def stop(self):
        self._source = None
        self._pending_source = b""

    def _release(self):
        self.stop()

    def _reset_buffer(self, single_channel_output=False, audio_channel=0):
        self._check()
        self._pending_source = b""
        # The modulator's cursor goes too, so a chain restarted mid-cycle
        # begins at the top of the table rather than wherever it stopped.
        self._pending_modulator = b""

    def _pull(self, sample):
        result, data = get_buffer(sample, False, 0)
        data = bytes(data)
        if result == GET_BUFFER_ERROR or len(data) < 4:
            return b""
        return data[:len(data) // 4 * 4]

    def _get_buffer(self, single_channel_output=False, audio_channel=0):
        self._check()
        output = bytearray()
        produced = 0
        while produced < FRAMES:
            if not self._pending_source:
                if self._source is None:
                    break
                self._pending_source = self._pull(self._source)
                if not self._pending_source:
                    break
            if not self._pending_modulator and self._modulator is not None:
                # A modulator is normally a short looping table, which hands
                # back its whole length every time it is asked; one that has
                # genuinely stopped leaves the signal alone rather than
                # muting it.
                self._pending_modulator = self._pull(self._modulator)
            run = min(FRAMES - produced, len(self._pending_source) // 4)
            if self._pending_modulator:
                run = min(run, len(self._pending_modulator) // 4)
                output += _audioif.multiply_s16(
                    self._pending_source[:run * 4],
                    self._pending_modulator[:run * 4], self._mix)
                self._pending_modulator = self._pending_modulator[run * 4:]
            else:
                output += self._pending_source[:run * 4]
            self._pending_source = self._pending_source[run * 4:]
            produced += run
        # A starved chain gets silence rather than a short block: this node
        # sits in the middle of a live graph and never reports itself finished.
        if produced == 0:
            return GET_BUFFER_MORE_DATA, memoryview(bytes(FRAMES * 4))
        return GET_BUFFER_MORE_DATA, memoryview(bytes(output))


__all__ = ("Multiply",)
