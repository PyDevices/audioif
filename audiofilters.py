"""CircuitPython-compatible streaming audio filters."""

from array import array
from enum import Enum
from audiocore import GET_BUFFER_DONE, GET_BUFFER_MORE_DATA, _AudioSample, get_buffer, reset_buffer
import _audioif


def _value(value):
    evaluator = getattr(value, "_evaluate", None)
    if evaluator is not None:
        # Import lazily: synthio imports audiocore and effects may in turn
        # be imported while applications are assembling their graph.
        from synthio import _BLOCK_TICK
        return float(evaluator(_BLOCK_TICK))
    return float(value.value if hasattr(value, "value") else value)


class _CircuitEnum(Enum):
    def __repr__(self):
        return "{}.{}.{}".format(
            self.__class__.__module__, self.__class__.__name__, self.name)

    __str__ = __repr__


class DistortionMode(_CircuitEnum):
    CLIP = 0
    LOFI = 1
    OVERDRIVE = 2
    WAVESHAPE = 3


class _Effect(_AudioSample):
    _process_during_pull = True

    def _init_format(self, *, buffer_size, sample_rate, bits_per_sample, samples_signed, channel_count):
        if channel_count not in (1, 2): raise ValueError("channel_count must be 1 or 2")
        if bits_per_sample not in (8, 16): raise ValueError("bits_per_sample must be 8 or 16")
        if sample_rate < 1: raise ValueError("sample_rate must be at least 1")
        self.buffer_size, self.sample_rate = int(buffer_size), int(sample_rate)
        self.bits_per_sample, self.samples_signed = int(bits_per_sample), bool(samples_signed)
        self.channel_count, self._sample, self._loop, self._deinited = int(channel_count), None, False, False
        self._remaining, self._source_more = b"", False

    @property
    def playing(self): return self._sample is not None
    def play(self, sample, *, loop=False):
        self._check()
        for name in ("sample_rate", "channel_count", "bits_per_sample", "samples_signed"):
            if getattr(sample, name) != getattr(self, name): raise ValueError("The sample's %s does not match" % name)
        self._sample, self._loop = sample, bool(loop); reset_buffer(sample)
        result, data = get_buffer(sample)
        self._remaining = bytes(data)
        self._source_more = result == GET_BUFFER_MORE_DATA
    def stop(self): self._sample = None
    def _release(self):
        self._sample = None
        self._remaining = b""
    def _reset_buffer(self, single_channel_output=False, audio_channel=0):
        self._check()
        self._reset_state()
    def _reset_state(self):
        pass
    def _get_buffer(self, single_channel_output=False, audio_channel=0):
        self._check()
        output = bytearray()
        while len(output) < self.buffer_size and self._sample is not None:
            take = min(self.buffer_size - len(output), len(self._remaining))
            if self._process_during_pull:
                take = min(take, 256 * self.channel_count *
                           (self.bits_per_sample // 8))
            segment = bytes(self._remaining[:take])
            output += self._process(segment) if self._process_during_pull else segment
            self._remaining = self._remaining[take:]
            if len(output) == self.buffer_size:
                break
            if not self._remaining:
                if not self._source_more:
                    if self._loop:
                        reset_buffer(self._sample, single_channel_output, audio_channel)
                    else:
                        self._sample = None
                        break
                if self._sample is not None:
                    result, data = get_buffer(
                        self._sample, single_channel_output, audio_channel
                    )
                    self._remaining = bytes(data)
                    self._source_more = result == GET_BUFFER_MORE_DATA
                    if not self._remaining and not self._source_more:
                        self._sample = None
                        break
        valid_length = len(output)
        output += bytes(self.buffer_size - valid_length)
        if self._process_during_pull:
            if getattr(self, "_process_silence", False) and valid_length < self.buffer_size:
                output[valid_length:] = self._process(
                    bytes(self.buffer_size - valid_length))
            processed = bytes(output)
        elif getattr(self, "_process_silence", False):
            processed = self._process(bytes(output))
        else:
            processed = (self._process(bytes(output[:valid_length]))
                         + bytes(self.buffer_size - valid_length))
        return GET_BUFFER_MORE_DATA, memoryview(processed)

    def _process(self, data):
        return data


class Filter(_Effect):
    # The C implementation filters each at-most-256-frame source segment
    # before requesting the next one.  This ordering matters when both the
    # source and filter parameters are driven by synthio blocks.
    def __init__(self, *, filter=None, mix=1, buffer_size=512, sample_rate=8000, bits_per_sample=16, samples_signed=True, channel_count=1):
        self.filter, self.mix = filter, mix
        self._init_format(buffer_size=buffer_size, sample_rate=sample_rate, bits_per_sample=bits_per_sample, samples_signed=samples_signed, channel_count=channel_count)
        if filter is None:
            self._filters = ()
        elif isinstance(filter, (tuple, list)):
            self._filters = tuple(filter)
        else:
            self._filters = (filter,)
        self._filter_states = tuple(_audioif.BiquadState() for _ in self._filters)

    def _reset_state(self):
        for state in self._filter_states:
            state.reset()

    def _process(self, data):
        if self.bits_per_sample != 16 or not self.samples_signed or not data or not self._filters:
            return data
        from synthio import _advance_blocks
        frame_count = len(data) // (self.channel_count * 2)
        _advance_blocks(self.sample_rate, frame_count)
        requested_mix = min(1.0, max(0.0, _value(self.mix)))
        result = data
        for index, (biquad, state) in enumerate(zip(self._filters, self._filter_states)):
            stage_mix = requested_mix if index == len(self._filters) - 1 else 1.0
            amplitude = 1.0 if biquad.A is None else _value(biquad.A)
            result = state.process_s16(
                result, biquad.mode.value, _value(biquad.frequency),
                _value(biquad.Q), amplitude, self.sample_rate, stage_mix,
            )
        return result


class Distortion(_Effect):
    def __init__(self, *, drive=0, pre_gain=0, post_gain=0, mode=DistortionMode.CLIP, soft_clip=False, mix=1, buffer_size=512, sample_rate=8000, bits_per_sample=16, samples_signed=True, channel_count=1):
        if not isinstance(mode, DistortionMode): raise TypeError("mode must be a DistortionMode")
        self.drive, self.pre_gain, self.post_gain = drive, pre_gain, post_gain
        self.mode, self.soft_clip, self.mix = mode, bool(soft_clip), mix
        self._init_format(buffer_size=buffer_size, sample_rate=sample_rate, bits_per_sample=bits_per_sample, samples_signed=samples_signed, channel_count=channel_count)

    def _process(self, data):
        if self.bits_per_sample != 16 or not self.samples_signed or not data:
            return data
        from synthio import _advance_blocks
        _advance_blocks(self.sample_rate,
                        len(data) // (self.channel_count * 2))
        return _audioif.distortion_s16(
            data,
            min(1.0, max(0.0, _value(self.drive))),
            min(60.0, max(-60.0, _value(self.pre_gain))),
            min(24.0, max(-80.0, _value(self.post_gain))),
            self.mode.value,
            self.soft_clip,
            min(1.0, max(0.0, _value(self.mix))),
        )


class Phaser(_Effect):
    def __init__(self, *, frequency=1000, feedback=None, mix=1, stages=6, buffer_size=512, sample_rate=8000, bits_per_sample=16, samples_signed=True, channel_count=1):
        self.frequency = frequency
        self.feedback = 0.7 if feedback is None else feedback
        self.mix = mix
        self._stages = max(1, int(stages))
        self._init_format(buffer_size=buffer_size, sample_rate=sample_rate, bits_per_sample=bits_per_sample, samples_signed=samples_signed, channel_count=channel_count)
        from array import array
        self._feedback_words = array("h", (0 for _ in range(self.channel_count)))
        self._allpass = array(
            "h", (0 for _ in range(self.channel_count * self._stages)))

    @property
    def stages(self): return self._stages

    @stages.setter
    def stages(self, value):
        from array import array
        self._stages = max(1, int(value))
        self._allpass = array(
            "h", (0 for _ in range(self.channel_count * self._stages)))

    def _reset_state(self):
        self._feedback_words[:] = array("h", [0]) * len(self._feedback_words)
        self._allpass[:] = array("h", [0]) * len(self._allpass)

    @staticmethod
    def _sat16(value, shift=0):
        if value < 0 and shift:
            value += (1 << shift) - 1
        value >>= shift
        return max(-32768, min(32767, value))

    @staticmethod
    def _mixdown(value, voices=2):
        scale = voices
        if value < -28000:
            value = ((value + 28000) * scale >> 16) - 28000
        elif value > 28000:
            value = ((value - 28000) * scale >> 16) + 28000
        return ((value + 32768) & 0xffff) - 32768

    def _process(self, data):
        if not data:
            return data
        from synthio import _advance_blocks
        frame_size = self.channel_count * (self.bits_per_sample // 8)
        _advance_blocks(self.sample_rate, len(data) // frame_size)
        frequency = min(self.sample_rate / 2.0,
                        max(0.0, _value(self.frequency)))
        feedback = int(min(.9, max(.1, _value(self.feedback))) * 32767)
        mix = int(min(1.0, max(0.0, _value(self.mix))) * 32767)
        if mix <= 328:
            return data
        coefficient = int(((1.0 - frequency / (self.sample_rate / 2.0)) /
                           (1.0 + frequency / (self.sample_rate / 2.0))) * 32767)
        if self.bits_per_sample == 16:
            return _audioif.phaser_s16(
                data, self._feedback_words, self._allpass,
                self.channel_count, self._stages, frequency,
                self.sample_rate / 2.0,
                min(.9, max(.1, _value(self.feedback))),
                min(1.0, max(0.0, _value(self.mix))),
            )
        # Match the signed-domain conversion used by the C 8-bit path.
        result = bytearray()
        for index, raw in enumerate(data):
            sample = raw if self.samples_signed and raw < 128 else raw - 256
            if not self.samples_signed:
                sample = ((raw ^ 0x80) + 128) % 256 - 128
            channel = index % self.channel_count
            word = self._sat16(sample + self._sat16(
                self._feedback_words[channel] * feedback, 15))
            offset = channel * self._stages
            for stage in range(self._stages):
                state_index = offset + stage
                allpass_word = self._sat16(
                    self._sat16(word * -coefficient, 15) + self._allpass[state_index])
                self._allpass[state_index] = self._sat16(
                    self._sat16(allpass_word * coefficient, 15) + word)
                word = allpass_word
            self._feedback_words[channel] = word
            out = self._mixdown(sample + self._sat16(word * mix, 15)) & 0xff
            result.append(out if self.samples_signed else out ^ 0x80)
        return bytes(result)


__all__ = ("Filter", "Distortion", "Phaser", "DistortionMode")
