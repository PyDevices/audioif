"""A source claiming MORE_DATA while returning nothing must not hang the mixer.

`Mixer._get_buffer` fills a render block by repeatedly pulling from each
voice's source. A source that reports ``GET_BUFFER_MORE_DATA`` and hands back
a zero-length buffer takes 0 bytes, grows the output not at all, and satisfies
neither loop exit — so the loop spins and the whole render hangs rather than
failing.

That is not hypothetical. Planting it in ``audiodelays.Echo`` during the
fault-planting pass made ``verify_acceptance.py`` run until it was killed at
45 s with no output at all, where ``verify_streaming.py`` failed in 0.07 s on
the identical command line. In CI that shape is an untimed job hang, not a
named failure — strictly worse than a red gate, because nothing says what
broke.

One empty chunk is tolerated; a second consecutive one stops the voice. See
issue #24.
"""

import array
import unittest

import audiocore
import audiomixer

SAMPLE_RATE = 48000
BUFFER_SIZE = 512


class _EmptyButHopeful:
    """Reports MORE_DATA forever and never produces a byte."""

    bits_per_sample = 16
    samples_signed = True
    channel_count = 2
    sample_rate = SAMPLE_RATE

    def __init__(self):
        self.calls = 0

    def _reset_buffer(self, single_channel_output=False, audio_channel=0):
        pass

    def _get_buffer(self, single_channel_output=False, audio_channel=0):
        self.calls += 1
        return audiocore.GET_BUFFER_MORE_DATA, memoryview(bytearray())


class _OneChunkThenEmpty(_EmptyButHopeful):
    """Produces once, then behaves badly - the tolerated-once case."""

    def _get_buffer(self, single_channel_output=False, audio_channel=0):
        self.calls += 1
        if self.calls == 1:
            return audiocore.GET_BUFFER_MORE_DATA, memoryview(
                bytearray(BUFFER_SIZE))
        return audiocore.GET_BUFFER_MORE_DATA, memoryview(bytearray())


class MixerEmptySource(unittest.TestCase):
    def _mixer(self):
        return audiomixer.Mixer(
            voice_count=1, sample_rate=SAMPLE_RATE, channel_count=2,
            bits_per_sample=16, samples_signed=True, buffer_size=BUFFER_SIZE)

    def test_an_always_empty_source_does_not_hang(self):
        """Without the guard this never returns."""
        mixer = self._mixer()
        source = _EmptyButHopeful()
        mixer.voice[0].play(source)
        _result, buffer = audiocore.get_buffer(mixer)
        self.assertTrue(len(bytes(buffer)) > 0)
        self.assertEqual(set(array.array("h", bytes(buffer))), {0})
        self.assertFalse(mixer.voice[0].playing)
        self.assertLess(source.calls, 10, "source pulled far more than needed")

    def test_a_source_that_produces_once_is_not_punished_for_one_empty(self):
        """One empty chunk is a beat, not a fault - its audio must survive."""
        mixer = self._mixer()
        mixer.voice[0].play(_OneChunkThenEmpty())
        _result, buffer = audiocore.get_buffer(mixer)
        self.assertTrue(len(bytes(buffer)) > 0)

    def test_a_well_behaved_source_is_unaffected(self):
        """The control: without it this suite proves only that things stop."""
        mixer = self._mixer()

        class Tone(_EmptyButHopeful):
            def _get_buffer(self, single_channel_output=False,
                            audio_channel=0):
                self.calls += 1
                block = array.array("h", [4000] * (BUFFER_SIZE // 2))
                return audiocore.GET_BUFFER_MORE_DATA, memoryview(block)

        mixer.voice[0].play(Tone())
        _result, buffer = audiocore.get_buffer(mixer)
        self.assertNotEqual(set(array.array("h", bytes(buffer))), {0})
        self.assertTrue(mixer.voice[0].playing)


if __name__ == "__main__":
    unittest.main()
