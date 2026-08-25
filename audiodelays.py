"""CircuitPython-compatible streaming delay effects."""

from array import array

import _audioif
from audiofilters import _Effect
from audiofilters import _value


class Echo(_Effect):
    _process_silence = True

    def __init__(self, *, max_delay_ms=500, delay_ms=None, decay=None, mix=None, buffer_size=512, sample_rate=8000, bits_per_sample=16, samples_signed=True, channel_count=1, freq_shift=True):
        if not 1 <= max_delay_ms <= 4000: raise ValueError("max_delay_ms must be from 1 to 4000")
        self.max_delay_ms, self.delay_ms, self.decay, self.mix = max_delay_ms, 250 if delay_ms is None else delay_ms, 0.7 if decay is None else decay, 0.5 if mix is None else mix
        self.freq_shift = bool(freq_shift)
        self._init_format(buffer_size=buffer_size, sample_rate=sample_rate, bits_per_sample=bits_per_sample, samples_signed=samples_signed, channel_count=channel_count)
        self._maximum_samples = int(self.sample_rate / 1000.0 * self.max_delay_ms)
        self._echo_buffer = array(
            "h", (0 for _ in range(self._maximum_samples * self.channel_count))
        )
        self._left_position = self._right_position = 0

    def _reset_state(self):
        self._echo_buffer[:] = array("h", [0]) * len(self._echo_buffer)

    def _process(self, data):
        if self.bits_per_sample != 16 or not self.samples_signed or not data:
            return data
        from synthio import _advance_blocks
        _advance_blocks(self.sample_rate,
                        len(data) // (self.channel_count * 2))
        delay_ms = max(1000.0 / self.sample_rate, _value(self.delay_ms))
        if self.freq_shift:
            delay_samples = self._maximum_samples
            rate = max(int(self.max_delay_ms / delay_ms * 256.0), 1)
        else:
            delay_samples = int(self.sample_rate / 1000.0 * delay_ms)
            delay_samples = min(self._maximum_samples,
                                max(self.buffer_size // 2, delay_samples))
            rate = 1
        result, self._left_position, self._right_position = _audioif.echo_s16(
            data, self._echo_buffer, self._left_position, self._right_position,
            delay_samples, self._maximum_samples, rate,
            min(1.0, max(0.0, _value(self.decay))),
            min(1.0, max(0.0, _value(self.mix))) * 2.0,
            self.freq_shift, self.channel_count,
        )
        return result


class Chorus(_Effect):
    def __init__(self, *, max_delay_ms=50, delay_ms=None, voices=None, mix=None, buffer_size=512, sample_rate=8000, bits_per_sample=16, samples_signed=True, channel_count=1):
        if not 1 <= max_delay_ms <= 4000: raise ValueError("max_delay_ms must be from 1 to 4000")
        self.max_delay_ms, self.delay_ms = max_delay_ms, 50 if delay_ms is None else delay_ms
        self.voices, self.mix = 1.0 if voices is None else voices, 0.5 if mix is None else mix
        self._init_format(buffer_size=buffer_size, sample_rate=sample_rate, bits_per_sample=bits_per_sample, samples_signed=samples_signed, channel_count=channel_count)
        self._maximum_samples = int(
            self.sample_rate / 1000.0 * self.max_delay_ms * self.channel_count)
        self._chorus_buffer = array(
            "h", (0 for _ in range(self._maximum_samples)))
        self._position = 0

    def _reset_state(self):
        self._chorus_buffer[:] = array("h", [0]) * len(self._chorus_buffer)

    def _process(self, data):
        if self.bits_per_sample != 16 or not self.samples_signed or not data:
            return data
        from synthio import _advance_blocks
        _advance_blocks(self.sample_rate,
                        len(data) // (self.channel_count * 2))
        voices = max(1, int(_value(self.voices)))
        mix = min(1.0, max(0.0, _value(self.mix)))
        delay_ms = max(1000.0 / self.sample_rate, _value(self.delay_ms))
        delay_samples = int(self.sample_rate / 1000.0 * delay_ms)
        delay_samples *= self.channel_count
        delay_samples = min(self._maximum_samples, max(1, delay_samples))
        result, self._position = _audioif.chorus_s16(
            data, self._chorus_buffer, self._position, delay_samples,
            self._maximum_samples, voices, mix,
        )
        return result


class MultiTapDelay(_Effect):
    _process_silence = True

    def __init__(self, *, max_delay_ms=500, delay_ms=250, decay=None, mix=None, taps=None, buffer_size=512, sample_rate=8000, bits_per_sample=16, samples_signed=True, channel_count=1):
        if not 1 <= max_delay_ms <= 4000: raise ValueError("max_delay_ms must be from 1 to 4000")
        self.max_delay_ms, self.delay_ms = max_delay_ms, delay_ms
        self.decay, self.mix = 0.7 if decay is None else decay, 0.25 if mix is None else mix
        self._init_format(buffer_size=buffer_size, sample_rate=sample_rate, bits_per_sample=bits_per_sample, samples_signed=samples_signed, channel_count=channel_count)
        self._maximum_samples = int(
            self.sample_rate / 1000.0 * self.max_delay_ms)
        self._delay_buffer = array("h", (0 for _ in range(
            self._maximum_samples * self.channel_count)))
        self._position = 0
        self.taps = taps

    def _reset_state(self):
        self._delay_buffer[:] = array("h", [0]) * len(self._delay_buffer)

    @property
    def taps(self):
        return None if not self._tap_positions else tuple(zip(
            self._tap_positions, self._tap_levels))

    @taps.setter
    def taps(self, value):
        if value is None:
            items = ()
        else:
            items = tuple(value)
            if not items: raise ValueError("items length must be at least 1")
        positions, levels = [], []
        for item in items:
            if isinstance(item, (tuple, list)):
                if len(item) != 2: raise ValueError("items length must be 2")
                position, level = item
            else:
                position, level = item, 1.0
            position, level = float(position), float(level)
            if not 0 <= position <= 1: raise ValueError("position must be from 0 to 1")
            if not 0 <= level <= 1: raise ValueError("level must be from 0 to 1")
            positions.append(position); levels.append(level)
        self._tap_positions, self._tap_levels = tuple(positions), tuple(levels)

    def _process(self, data):
        if self.bits_per_sample != 16 or not self.samples_signed or not data:
            return data
        from synthio import _advance_blocks
        _advance_blocks(self.sample_rate,
                        len(data) // (self.channel_count * 2))
        delay_ms = max(1000.0 / self.sample_rate, float(self.delay_ms))
        delay_samples = int(self.sample_rate / 1000.0 * delay_ms)
        minimum_samples = self.buffer_size // (self.channel_count * 2)
        delay_samples = min(self._maximum_samples,
                            max(minimum_samples, delay_samples))
        offsets = array("I", (int(delay_samples * position)
                              for position in self._tap_positions))
        levels = array("d", self._tap_levels)
        result, self._position = _audioif.multitap_s16(
            data, self._delay_buffer, self._position, delay_samples,
            self.channel_count, offsets, levels,
            min(1.0, max(0.0, _value(self.decay))),
            min(1.0, max(0.0, _value(self.mix))) * 2.0,
        )
        return result


class PitchShift(_Effect):
    def __init__(self, *, semitones=0, mix=1, window=1024, overlap=128, buffer_size=512, sample_rate=8000, bits_per_sample=16, samples_signed=True, channel_count=1):
        self.semitones, self.mix, self.window, self.overlap = semitones, mix, int(window), int(overlap)
        self._init_format(buffer_size=buffer_size, sample_rate=sample_rate, bits_per_sample=bits_per_sample, samples_signed=samples_signed, channel_count=channel_count)
        self._window_samples = self.window // 2 // self.channel_count
        self._overlap_samples = self.overlap // 2 // self.channel_count
        self._window_buffer = array("h", (0 for _ in range(
            self._window_samples * self.channel_count)))
        self._overlap_buffer = array("h", (0 for _ in range(
            self._overlap_samples * self.channel_count)))
        self._window_index = self._overlap_index = self._read_index = 0

    def _reset_state(self):
        self._window_buffer[:] = array("h", [0]) * len(self._window_buffer)
        self._overlap_buffer[:] = array("h", [0]) * len(self._overlap_buffer)

    def _process(self, data):
        if self.bits_per_sample != 16 or not self.samples_signed or not data:
            return data
        from synthio import _advance_blocks
        _advance_blocks(self.sample_rate,
                        len(data) // (self.channel_count * 2))
        read_rate = int(2.0 ** (_value(self.semitones) / 12.0) * 256)
        result, self._window_index, self._overlap_index, self._read_index = (
            _audioif.pitchshift_s16(
                data, self._window_buffer, self._overlap_buffer,
                self._window_samples, self._overlap_samples,
                self.channel_count, read_rate, self._window_index,
                self._overlap_index, self._read_index,
                min(1.0, max(0.0, _value(self.mix))) * 2.0,
            )
        )
        return result


__all__ = ("Echo", "Chorus", "PitchShift", "MultiTapDelay")
