"""CircuitPython-compatible audio sample sources for CPython."""

import wave

import _audioif  # noqa: F401 - verifies that the native runtime is present

GET_BUFFER_DONE = 0
GET_BUFFER_MORE_DATA = 1
GET_BUFFER_ERROR = 2


class _AudioSample:
    def __getattribute__(self, name):
        if not name.startswith("_") and name != "deinit":
            namespace = object.__getattribute__(self, "__dict__")
            if namespace.get("_deinited", False):
                raise RuntimeError(
                    "Object has been deinitialized and can no longer be used")
        return object.__getattribute__(self, name)

    def _check(self):
        if getattr(self, "_deinited", False):
            raise RuntimeError("Object has been deinitialized and can no longer be used")

    def deinit(self):
        if object.__getattribute__(self, "__dict__").get("_deinited", False):
            return
        self._release()
        self._deinited = True

    def _release(self):
        pass

    def __enter__(self):
        self._check()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.deinit()


RawSample = _audioif.RawSample


class WaveFile(_AudioSample):
    def __init__(self, file, buffer=None):
        self._file_owner = file
        self._stream = open(file, "rb") if isinstance(file, (str, bytes)) else file
        self._close_stream = self._stream is not file
        self._wave = wave.open(self._stream, "rb")
        self.channel_count = self._wave.getnchannels()
        self.sample_rate = self._wave.getframerate()
        self.bits_per_sample = self._wave.getsampwidth() * 8
        self.samples_signed = self.bits_per_sample != 8
        self._buffer_size = memoryview(buffer).nbytes if buffer is not None else 1024
        self._buffer_owner = buffer
        self._deinited = False

    def _reset_buffer(self, single_channel_output=False, audio_channel=0):
        self._check()
        self._wave.rewind()

    def _get_buffer(self, single_channel_output=False, audio_channel=0):
        self._check()
        frame_size = self.channel_count * self.bits_per_sample // 8
        data = self._wave.readframes(max(1, self._buffer_size // frame_size))
        if not data:
            return GET_BUFFER_DONE, memoryview(b"")
        result = GET_BUFFER_DONE if self._wave.tell() >= self._wave.getnframes() else GET_BUFFER_MORE_DATA
        return result, memoryview(bytes(data))

    def _release(self):
        wave_reader = getattr(self, "_wave", None)
        self._wave = self._buffer_owner = self._file_owner = None
        if wave_reader is not None:
            wave_reader.close()
        if getattr(self, "_close_stream", False) and self._stream is not None:
            self._stream.close()
        self._stream = None


def _sample_method(sample, name):
    method = getattr(sample, name, None)
    if method is None:
        raise TypeError("object does not implement the audiocore sample protocol")
    return method


def reset_buffer(sample, single_channel_output=False, audio_channel=0):
    _sample_method(sample, "_reset_buffer")(single_channel_output, audio_channel)


def get_buffer(sample, single_channel_output=False, audio_channel=0):
    result, data = _sample_method(sample, "_get_buffer")(single_channel_output, audio_channel)
    # Deliberately own a byte-format copy: callers may retain it after the
    # producer advances or is deinitialized.
    return int(result), memoryview(bytes(data))


def get_structure(sample, single_channel_output=False):
    return {
        "sample_rate": sample.sample_rate,
        "bits_per_sample": sample.bits_per_sample,
        "channel_count": 1 if single_channel_output else sample.channel_count,
        "samples_signed": sample.samples_signed,
    }


__all__ = ("RawSample", "WaveFile", "get_buffer", "reset_buffer", "get_structure")
