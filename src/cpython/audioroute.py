"""Fan one audio stream out to several parallel branches.

Unlike the rest of this package, `audioroute` is not a CircuitPython module.
It comes from micropython-vst3's `vstaudio` engine, where the effects
library's exciters, Haas wideners and multiband splits are built on it.

    split = audioroute.Splitter(source, taps=3)
    low.play(split.tap(0))
    mid.play(split.tap(1))
    high.play(split.tap(2))
    mixer.play(low, voice=0) ...

Every tap reads the same stream at its own pace over a shared ring. Whichever
one is pulled first refills the ring; the others read what it wrote. A branch
that nobody reads must not wedge the ring, so writing past a laggard's cursor
drags it forward: that branch skips ahead rather than stalling the graph.
"""

from audiocore import (
    GET_BUFFER_ERROR, GET_BUFFER_MORE_DATA, _AudioSample, get_buffer,
)
import _audioif

MAX_TAPS = 4
CHUNK_FRAMES = _audioif.SPLITTER_CHUNK_FRAMES

_SILENCE = bytes(CHUNK_FRAMES * 4)


class SplitterTap(_AudioSample):
    """One branch's view of a Splitter's ring. Built by the Splitter."""

    def __init__(self, owner, index, sample_rate):
        self._owner = owner
        self._index = index
        self.sample_rate = sample_rate
        self.bits_per_sample = 16
        self.channel_count = 2
        self.samples_signed = True
        self.single_buffer = False
        self.max_buffer_length = CHUNK_FRAMES * 4
        self._deinited = False

    def _reset_buffer(self, single_channel_output=False, audio_channel=0):
        # Deliberately nothing. The cursors belong to the Splitter and the
        # other taps are still reading against them; rewinding one branch
        # mid-stream would desynchronise the rest.
        pass

    def _get_buffer(self, single_channel_output=False, audio_channel=0):
        self._check()
        owner = self._owner
        if owner._ring.starved(self._index):
            owner._pull()
        data = owner._ring.take(self._index)
        if not data:
            # Still nothing: the source is dry, or another tap has already
            # read past what one pull could supply.
            return GET_BUFFER_MORE_DATA, memoryview(_SILENCE)
        return GET_BUFFER_MORE_DATA, memoryview(data)


class Splitter:
    def __init__(self, source, taps=2):
        taps = int(taps)
        if taps < 1 or taps > MAX_TAPS:
            raise ValueError("taps must be 1..4")
        self._source = source
        self._ring = _audioif.SplitterRing(taps=taps)
        self._tap_count = taps
        # Every tap exists from the start, whether or not anything asks for
        # it: the ring drops what an unread tap never collects, so a branch
        # built late would begin mid-stream rather than at the beginning.
        self._taps = tuple(SplitterTap(self, index, source.sample_rate)
                           for index in range(taps))

    def tap(self, index):
        index = int(index)
        if index < 0 or index >= self._tap_count:
            raise ValueError("tap index out of range")
        return self._taps[index]

    def _pull(self):
        if self._source is None:
            return
        result, data = get_buffer(self._source, False, 0)
        if result == GET_BUFFER_ERROR:
            return
        self._ring.write(bytes(data))


__all__ = ("Splitter", "SplitterTap")
