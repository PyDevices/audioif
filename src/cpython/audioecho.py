"""A delay with a filter, a soft-clip and a cross-feed inside its feedback
loop.

Not a CircuitPython module, and not from micropython-vst3's engine either --
audioif adds it. `audiodelays.Echo` exists upstream and its feedback path is
`echo * decay` and nothing else, so everything a delay is actually *called*
falls out of what this module puts in that path:

    tape = audioecho.FeedbackDelay(
        sample_rate=48000, max_delay_ms=600, delay_ms=340, feedback=0.45,
        mix=0.28, damping_hz=3200, cut_hz=180, wow_hz=0.7,
        wow_depth_ms=1.4, loop_drive=0.35)
    tape.play(source)
    audio_out.play(tape)

`damping_hz` and `cut_hz` are one-pole filters *in* the loop, so each repeat
loses a little more top and bottom than the last - which is what makes tape
sound like tape rather than like a delay with a tone control after it.
`loop_drive` softens each pass the same way. `wow_hz`/`wow_depth_ms` modulate
the delay per sample, so the repeats get the doppler an LFO at block rate
cannot reach. `cross_feed` sends each channel's repeats into the other
channel's line, and `input_pan` steers the *input* to one line only: hard
over with full cross-feed is a real ping-pong, where the first repeat is on
one side alone.

A new module rather than arguments on `Echo`, deliberately: an argument added
to audioif's copy of a CircuitPython module would not exist on a stock board,
so an effect written against it would silently be a different effect there.
This either installs whole or is absent and says so on import.
"""

from audiocore import (
    GET_BUFFER_ERROR, GET_BUFFER_MORE_DATA, _AudioSample, get_buffer,
)
import _audioif

FRAMES = _audioif.FEEDBACK_DELAY_FRAMES

#: Option name -> the native configure() slot. Kept in the order
#: shared/audioif_feedback_delay.h declares, which is the order the
#: MicroPython bindings list them in too.
_OPTIONS = {
    "delay_ms": 0,
    "feedback": 1,
    "mix": 2,
    "damping_hz": 3,
    "cut_hz": 4,
    "wow_hz": 5,
    "wow_depth_ms": 6,
    "cross_feed": 7,
    "loop_drive": 8,
    "input_pan": 9,
}


class FeedbackDelay(_AudioSample):
    def __init__(self, sample_rate=48000, max_delay_ms=250.0, **options):
        channel_count = int(options.pop("channel_count", 2))
        if channel_count not in (1, 2):
            raise ValueError("channel_count must be 1 or 2")
        options.pop("sample_rate", None)
        options.pop("max_delay_ms", None)
        self.sample_rate = int(sample_rate)
        self.bits_per_sample = 16
        self.channel_count = channel_count
        self.samples_signed = True
        self.single_buffer = False
        self.max_buffer_length = FRAMES * 2 * channel_count
        self._deinited = False
        self._source = None
        self._pending = b""
        if max_delay_ms <= 0:
            raise ValueError("max_delay_ms must be positive")
        self._state = _audioif.FeedbackDelayState(
            sample_rate=self.sample_rate, max_delay_ms=float(max_delay_ms),
            channel_count=channel_count)
        # The default delay is half the line rather than all of it, so a
        # caller who sizes the line and says nothing else still hears repeats.
        self._apply(options)
        self._state.finish()

    def _apply(self, options):
        for name, value in options.items():
            slot = _OPTIONS.get(name)
            if slot is None:
                raise TypeError("unknown FeedbackDelay option %r" % (name,))
            self._state.configure(slot, float(value))

    def set(self, **options):
        """Change settings mid-stream. The line and the filters keep their
        contents; only what the loop does to them changes."""
        self._check()
        self._apply(options)

    def clear(self):
        """Empty the line and the loop filters."""
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
        # Unlike audiodynamics, everything goes. A delay's whole state is
        # audible: a chain restarted with the old repeats still in the line
        # plays the previous take over the new one.
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
        # finished. Note that the tail stops with the source -- the line is
        # only advanced by frames that arrive, so repeats do not ring on into
        # silence. That matches audiodelays.Echo, whose users expect it.
        if produced == 0:
            return GET_BUFFER_MORE_DATA, memoryview(
                bytes(FRAMES * 2 * self.channel_count))
        return GET_BUFFER_MORE_DATA, memoryview(bytes(output))


__all__ = ("FeedbackDelay",)
