"""CircuitPython-compatible PCM mixer."""

from audiocore import GET_BUFFER_DONE, GET_BUFFER_MORE_DATA, _AudioSample, get_buffer, reset_buffer
import _audioif


def _source_chunk(sample):
    result, data = get_buffer(sample)
    raw = bytes(data)
    # CircuitPython's mixer consumes packed 32-bit words. Any trailing bytes
    # that do not form a word are therefore intentionally ignored.
    return result, raw[:len(raw) // 4 * 4]


class MixerVoice:
    def __init__(self, mixer):
        self._mixer = mixer
        self._sample = None
        self._loop = False
        self.level = 1.0
        self.panning = 0.0
        self._remaining = b""
        self._source_more = False

    @property
    def playing(self): return self._sample is not None

    def play(self, sample, *, loop=False):
        self._mixer._check_sample(sample)
        reset_buffer(sample)
        self._sample, self._loop = sample, bool(loop)
        result, self._remaining = _source_chunk(sample)
        self._source_more = result == GET_BUFFER_MORE_DATA

    def stop(self): self._sample = None


class Mixer(_AudioSample):
    def __init__(self, *, voice_count=2, buffer_size=1024, channel_count=2,
                 bits_per_sample=16, samples_signed=True, sample_rate=8000):
        if not 1 <= voice_count <= 255: raise ValueError("voice_count must be from 1 to 255")
        if channel_count not in (1, 2): raise ValueError("channel_count must be 1 or 2")
        if bits_per_sample not in (8, 16): raise ValueError("bits_per_sample must be 8 or 16")
        if sample_rate < 1: raise ValueError("sample_rate must be at least 1")
        self.sample_rate, self.channel_count = int(sample_rate), int(channel_count)
        self.bits_per_sample, self.samples_signed = int(bits_per_sample), bool(samples_signed)
        self.buffer_size = int(buffer_size)
        self._render_size = self.buffer_size // 2 // 4 * 4
        self.voice = tuple(MixerVoice(self) for _ in range(voice_count))
        self._deinited = False

    @property
    def playing(self): return any(voice.playing for voice in self.voice)

    def _release(self):
        for voice in self.voice:
            voice.stop()
            voice._remaining = b""

    def _check_sample(self, sample):
        self._check()
        for name in ("sample_rate", "channel_count", "bits_per_sample", "samples_signed"):
            if getattr(sample, name) != getattr(self, name):
                raise ValueError("The sample's %s does not match" % name)

    def play(self, sample, *, voice=0, loop=False): self.voice[voice].play(sample, loop=loop)
    def stop_voice(self, voice=0): self.voice[voice].stop()

    def _reset_buffer(self, single_channel_output=False, audio_channel=0):
        self._check()
        for voice in self.voice:
            voice.stop()

    def _get_buffer(self, single_channel_output=False, audio_channel=0):
        self._check()
        chunks = []
        active = [voice for voice in self.voice if voice.playing]
        if not active:
            if not self.samples_signed and self.bits_per_sample == 16:
                silence = b"\x00\x80" * (self._render_size // 2)
            else:
                neutral = 128 if not self.samples_signed else 0
                silence = bytes([neutral]) * self._render_size
            return GET_BUFFER_MORE_DATA, memoryview(silence)
        for voice in active:
            output = bytearray()
            while len(output) < self._render_size and voice._sample is not None:
                take = min(self._render_size - len(output), len(voice._remaining))
                output += voice._remaining[:take]
                voice._remaining = voice._remaining[take:]
                if len(output) == self._render_size:
                    break
                if not voice._remaining:
                    if not voice._source_more:
                        if voice._loop:
                            reset_buffer(voice._sample, single_channel_output, audio_channel)
                        else:
                            voice.stop()
                            break
                    if voice._sample is not None:
                        result, voice._remaining = _source_chunk(voice._sample)
                        voice._source_more = result == GET_BUFFER_MORE_DATA
                        if not voice._remaining and not voice._source_more:
                            voice.stop()
                            break
            data = bytes(output) + bytes(self._render_size - len(output))
            if self.bits_per_sample == 16:
                import array
                samples = array.array("h"); samples.frombytes(data)
                from audiofilters import _value
                level = int(min(1.0, max(0.0, _value(voice.level))) * 32768)
                panning_value = min(32767 / 32768,
                                    max(-32767 / 32768,
                                        _value(voice.panning)))
                panning = int(panning_value * 32768 +
                              (0.5 if panning_value >= 0 else -0.5))
                left = right = level
                if self.channel_count == 2:
                    left_scale = 32768 if panning >= 0 else 32767 + panning
                    right_scale = 32767 - panning if panning >= 0 else 32768
                    left = (left_scale * level) >> 15
                    right = (right_scale * level) >> 15
                multipliers = (left, right)
                data = array.array("h", (
                    max(-32768, min(32767,
                        int(value * (multipliers[index % self.channel_count] /
                                     32767.0))))
                    for index, value in enumerate(samples)
                )).tobytes()
            chunks.append(data)
        size = max(map(len, chunks), default=0)
        chunks = [chunk + bytes(size - len(chunk)) for chunk in chunks]
        if self.bits_per_sample == 16 and chunks:
            mixed = chunks[0]
            for chunk in chunks[1:]: mixed = _audioif.mix_s16(mixed, chunk)
        else:
            neutral = 128 if not self.samples_signed else 0
            mixed = bytes(max(0, min(255, sum(chunk[i] - neutral for chunk in chunks) + neutral)) for i in range(size))
        return GET_BUFFER_MORE_DATA, memoryview(mixed)


__all__ = ("Mixer",)
