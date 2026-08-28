import array
import unittest

import audiocore
import audioeffects
import audioinstruments


COMMON = ("set_macro", "program_change", "get_macro", "reset", "deinit")
INSTRUMENT = ("note_on", "note_off", "all_notes_off", "pitch_bend",
              "control_change", "channel_pressure", "poly_pressure")
EFFECT = ("pitch_bend", "control_change", "channel_pressure",
          "poly_pressure")


def source(channels=2):
    return audiocore.RawSample(
        array.array("h", [0] * 256 * channels), sample_rate=48000,
        channel_count=channels)


class AudioComponentApiTests(unittest.TestCase):
    def check_common(self, component, methods, channels=2):
        for name in COMMON + methods:
            self.assertTrue(callable(getattr(component, name)), name)
        self.assertEqual(component.sample_rate, 48000)
        self.assertEqual(component.channel_count, channels)
        self.assertGreaterEqual(component.latency_samples, 0)
        self.assertTrue(component.tail_samples is None or
                        component.tail_samples >= 0)
        self.assertIsInstance(component.capabilities, tuple)
        self.assertEqual(component.patch_index, 0)
        self.assertEqual(len(component.output._get_buffer()[1]) %
                         (2 * channels), 0)

    def test_discovery_lists_are_stable(self):
        self.assertEqual(audioinstruments.ALL,
                         tuple(dict.fromkeys(audioinstruments.ALL)))
        self.assertEqual(audioeffects.ALL,
                         tuple(sorted(audioeffects.ALL)))
        self.assertEqual(len(audioinstruments.ALL), 53)
        self.assertEqual(len(audioeffects.ALL), 43)

    def test_all_instruments_implement_live_surface(self):
        for name in audioinstruments.ALL:
            with self.subTest(name=name):
                component = audioinstruments.create(name, 48000)
                try:
                    self.check_common(component, INSTRUMENT)
                    if component.macro_labels:
                        component.set_macro(0, 64)
                        self.assertIsNone(component.patch_index)
                        component.program_change(0)
                        self.assertEqual(component.patch_index, 0)
                    component.note_on(60, 100, note_id=22,
                                     sample_position=3)
                    component.note_off(60, note_id=22, sample_position=7)
                    component.all_notes_off()
                    component.reset()
                finally:
                    component.deinit()
                    component.deinit()
                with self.assertRaises(RuntimeError):
                    _ = component.output

    def test_all_effects_preserve_mono_and_implement_live_surface(self):
        for name in audioeffects.ALL:
            with self.subTest(name=name):
                component = audioeffects.create(name, source(1), 48000)
                try:
                    self.check_common(component, EFFECT, channels=1)
                    labels = getattr(component, "MACRO_LABELS", ())
                    if labels:
                        component.set_macro(0, 64, sample_position=3)
                        self.assertIsNone(component.patch_index)
                        component.program_change(0, sample_position=7)
                    else:
                        with self.assertRaises(IndexError):
                            component.get_macro(0)
                    component.pitch_bend(8192, sample_position=2)
                    component.control_change(1, 64, sample_position=2)
                    component.channel_pressure(64, sample_position=2)
                    component.poly_pressure(60, 64, sample_position=2)
                    component.reset()
                finally:
                    component.deinit()
                    component.deinit()
                with self.assertRaises(RuntimeError):
                    _ = component.output

    def test_invalid_construction_and_control_values_are_explicit(self):
        with self.assertRaises(ValueError):
            audioinstruments.create("minimoog", 48000, channel_count=3)
        with self.assertRaises(ValueError):
            audioeffects.create("LowPass", source(1), 44100)
        component = audioinstruments.create("minimoog", 48000)
        try:
            with self.assertRaises(IndexError):
                component.set_macro(99, 0)
            with self.assertRaises(ValueError):
                component.note_on(128)
            with self.assertRaises(ValueError):
                component.pitch_bend(16384)
            # MIDI scalar controls clamp instead of rejecting host automation
            # overshoot, while the patch index itself remains an ignored wire
            # message when unknown.
            component.set_macro(0, 1000)
            self.assertEqual(component.get_macro(0), 127.0)
            component.program_change(999)
        finally:
            component.deinit()

    def test_note_identity_and_zero_velocity_follow_midi_rules(self):
        component = audioinstruments.create("minimoog", 48000)
        try:
            component.note_on(60, 100, note_id=10)
            component.note_on(60, 100, note_id=11)
            self.assertEqual(len(component._active), 2)
            component.note_off(60, note_id=10)
            self.assertEqual(len(component._active), 1)
            # A note-off for an unrelated identity must not release note 11.
            component.note_off(61, note_id=99)
            self.assertEqual(len(component._active), 1)
            # MIDI's zero-velocity note-on is the other spelling of note-off.
            component.note_on(60, 0, note_id=11)
            self.assertEqual(len(component._active), 0)
        finally:
            component.deinit()


if __name__ == "__main__":
    unittest.main()
