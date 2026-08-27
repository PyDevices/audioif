"""CircuitPython-compatible Freeverb streaming effect."""

from array import array

import _audioif

from audiofilters import _Effect
from audiofilters import _value


class Freeverb(_Effect):
    _process_silence = True

    def __init__(self, *, roomsize=None, damp=None, mix=None, buffer_size=512, sample_rate=8000, bits_per_sample=16, samples_signed=True, channel_count=1):
        if not samples_signed: raise ValueError("Freeverb requires signed samples")
        if bits_per_sample != 16: raise ValueError("bits_per_sample must be 16")
        self.roomsize = 0.5 if roomsize is None else roomsize
        self.damp = 0.5 if damp is None else damp
        self.mix = 0.5 if mix is None else mix
        self._init_format(buffer_size=buffer_size, sample_rate=sample_rate, bits_per_sample=bits_per_sample, samples_signed=samples_signed, channel_count=channel_count)
        # CircuitPython allocates separate right-channel banks, but its
        # current processing loop resets the channel offsets for every
        # sample and therefore uses the first banks for both channels.
        self._comb = array("h", (0 for _ in range(11024)))
        self._comb_indices = array("I", (0 for _ in range(8)))
        self._comb_filters = array("h", (0 for _ in range(8)))
        self._allpass = array("h", (0 for _ in range(1563)))
        self._allpass_indices = array("I", (0 for _ in range(4)))

    def _process(self, data):
        if not data:
            return data
        from synthio import _advance_blocks
        _advance_blocks(self.sample_rate,
                        len(data) // (self.channel_count * 2))
        return _audioif.freeverb_s16(
            data, self._comb, self._comb_indices, self._comb_filters,
            self._allpass, self._allpass_indices,
            min(1.0, max(0.0, _value(self.roomsize))),
            min(1.0, max(0.0, _value(self.damp))),
            min(1.0, max(0.0, _value(self.mix))),
        )


__all__ = ("Freeverb",)
