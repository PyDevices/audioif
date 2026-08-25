from array import array
import gc
import unittest
import weakref

import _audioif
import audiocore
import audiodelays
import audiofilters
import audiofreeverb
import audiomixer
import audiospeed
import synthio


class AudioifApiTests(unittest.TestCase):
    def test_enum_repr_identity_and_envelope_tuple(self):
        values = (
            (synthio.FilterMode.LOW_PASS, "synthio.FilterMode.LOW_PASS"),
            (synthio.MathOperation.SUM, "synthio.MathOperation.SUM"),
            (synthio.EnvelopeState.ATTACK, "synthio.EnvelopeState.ATTACK"),
            (audiofilters.DistortionMode.CLIP,
             "audiofilters.DistortionMode.CLIP"),
        )
        for value, expected in values:
            with self.subTest(value=value):
                self.assertIs(value, value.__class__(value.value))
                self.assertEqual(repr(value), expected)
                self.assertEqual(str(value), expected)
        envelope = synthio.Envelope()
        self.assertIsInstance(envelope, tuple)
        self.assertEqual(
            repr(envelope),
            "Envelope(attack_time=0.1, decay_time=0.05, release_time=0.2, "
            "attack_level=1.0, sustain_level=0.8)",
        )

    def test_rawsample_uses_shared_native_core(self):
        self.assertIs(audiocore.RawSample, _audioif.RawSample)
        sample = audiocore.RawSample(bytearray(range(8)), single_buffer=False)
        self.assertEqual(bytes(audiocore.get_buffer(sample)[1]), bytes(range(4)))
        self.assertEqual(bytes(audiocore.get_buffer(sample)[1]), bytes(range(4, 8)))

    def test_rawsample_returns_owned_byte_view(self):
        exporter = array("h", (1, -2, 3, -4))
        sample = audiocore.RawSample(exporter, sample_rate=8000)
        result, view = audiocore.get_buffer(sample)
        self.assertEqual(result, 0)
        self.assertEqual(view.format, "B")
        before = bytes(view)
        exporter[0] = 99
        self.assertEqual(bytes(view), before)

    def test_buffer_protocol_inputs(self):
        exporters = [
            array("h", (1, 2, 3, 4)),
            bytearray((1, 2, 3, 4)),
            memoryview(array("h", (1, 2, 3, 4))),
        ]
        try:
            import numpy
        except ImportError:
            pass
        else:
            exporters.append(numpy.array((1, 2, 3, 4), dtype=numpy.int16))
        for exporter in exporters:
            with self.subTest(exporter=type(exporter).__name__):
                sample = audiocore.RawSample(exporter)
                self.assertEqual(audiocore.get_buffer(sample)[1].format, "B")
                sample.deinit()

    def test_deinit_guard_and_context_manager(self):
        sample = audiocore.RawSample(bytearray(8))
        with sample as entered:
            self.assertIs(entered, sample)
        with self.assertRaises(RuntimeError):
            audiocore.get_buffer(sample)

        synth = synthio.Synthesizer()
        synth.deinit()
        with self.assertRaises(RuntimeError):
            _ = synth.sample_rate
        with self.assertRaises(RuntimeError):
            _ = synth.pressed

    def test_chained_sources_released_on_deinit_and_gc(self):
        synth = synthio.Synthesizer(sample_rate=8000, channel_count=1)
        synth_ref = weakref.ref(synth)
        mixer = audiomixer.Mixer(
            voice_count=1, sample_rate=8000, channel_count=1)
        mixer.play(synth)
        del synth
        gc.collect()
        self.assertIsNotNone(synth_ref())
        mixer.deinit()
        gc.collect()
        self.assertIsNone(synth_ref())

        for _ in range(100):
            sample = audiocore.RawSample(array("h", range(16)), sample_rate=8000)
            effect = audiodelays.Echo(sample_rate=8000, channel_count=1)
            effect.play(sample)
            effect.deinit()
            sample.deinit()
        gc.collect()

    def test_exporter_retained_until_deinit(self):
        class Exporter(bytearray):
            pass
        exporter = Exporter(b"\x80" * 8)
        ref = weakref.ref(exporter)
        sample = audiocore.RawSample(exporter)
        del exporter
        gc.collect()
        self.assertIsNotNone(ref())
        sample.deinit()
        gc.collect()
        self.assertIsNone(ref())

    def test_synth_mixer_effect_chain(self):
        synth = synthio.Synthesizer(sample_rate=8000, channel_count=1)
        synth.press(synthio.Note(440))
        mixer = audiomixer.Mixer(voice_count=1, sample_rate=8000, channel_count=1)
        self.assertIs(mixer.voice[0], mixer.voice[0])
        effect = audiofilters.Filter(sample_rate=8000, channel_count=1)
        effect.play(mixer)
        mixer.play(synth)
        result, view = audiocore.get_buffer(effect)
        self.assertEqual(result, 1)
        self.assertEqual(view.format, "B")
        self.assertEqual(len(view), 512)

    def test_all_effect_types_construct(self):
        types = (
            audiofilters.Distortion, audiofilters.Phaser, audiodelays.Echo,
            audiodelays.Chorus, audiodelays.MultiTapDelay,
            audiodelays.PitchShift, audiofreeverb.Freeverb,
        )
        for effect_type in types:
            for channel_count in (1, 2):
                with self.subTest(effect_type=effect_type, channel_count=channel_count):
                    effect_type(sample_rate=8000, channel_count=channel_count).deinit()

    def test_speedchanger_retains_source(self):
        source = audiocore.RawSample(array("h", range(32)))
        speed = audiospeed.SpeedChanger(source, 2)
        self.assertEqual(audiocore.get_buffer(speed)[1].format, "B")


if __name__ == "__main__":
    unittest.main()
