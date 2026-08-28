"""The instrument library's public shape, and that its drum voices sound."""

import unittest

import audiocore
import audioinstruments
from tools.validate_metadata import validate_instruments

SAMPLE_RATE = 48000


def peak(sample, blocks):
    """Loudest sample over the next `blocks` buffers, 0.0-1.0."""
    loudest = 0
    for _ in range(blocks):
        data = memoryview(bytes(audiocore.get_buffer(sample)[1])).cast("h")
        for value in data:
            if value < 0:
                value = -value
            if value > loudest:
                loudest = value
    return loudest / 32768.0


class InstrumentLibraryTest(unittest.TestCase):
    def test_every_module_implements_the_component_contract(self):
        required = ("output", "note_on", "note_off", "all_notes_off",
                    "set_macro", "program_change", "channel_pressure",
                    "poly_pressure")
        self.assertEqual(validate_instruments(audioinstruments),
                         audioinstruments.DRUM_MACHINES)
        for name in audioinstruments.ALL:
            module = audioinstruments.load(name)
            self.assertTrue(callable(module.create), name)
            instrument = module.create(SAMPLE_RATE)
            for member in required:
                self.assertTrue(hasattr(instrument, member),
                                "%s missing %s" % (name, member))
            self.assertIsNotNone(instrument.output, name)

    def test_every_module_declares_its_surface(self):
        for name in audioinstruments.ALL:
            module = audioinstruments.load(name)
            self.assertLessEqual(len(module.MACRO_LABELS), 16, name)
            self.assertTrue(all(isinstance(label, str)
                                for label in module.MACRO_LABELS), name)
            self.assertEqual(set(module.MACRO_MODES),
                             set(range(len(module.MACRO_LABELS))), name)
            self.assertIn(0, module.PATCHES, name)
            patch_name, values = module.PATCHES[0]
            self.assertIsInstance(patch_name, str)
            self.assertEqual(len(values), len(module.MACRO_LABELS), name)
            for value in values:
                self.assertIsInstance(value, int, name)
                self.assertTrue(0 <= value <= 127, "%s: %r" % (name, value))

    def test_drum_machines_map_their_voices(self):
        for name in audioinstruments.DRUM_MACHINES:
            module = audioinstruments.load(name)
            notes = [note for note, _ in module.NOTE_MAP]
            self.assertEqual(len(notes), len(set(notes)), name)
            for note, label in module.NOTE_MAP:
                self.assertTrue(0 <= note <= 127, name)
                self.assertTrue(label.strip(), name)

    def test_every_mapped_drum_voice_makes_sound(self):
        # A pad that renders silence is a pad a sequencer cannot use.
        for name in audioinstruments.DRUM_MACHINES:
            module = audioinstruments.load(name)
            for note, label in module.NOTE_MAP:
                instrument = module.create(SAMPLE_RATE)
                instrument.note_on(note)
                level = peak(instrument.output, 6)
                self.assertGreater(level, 0.001,
                                   "%s %s (note %d) is silent"
                                   % (name, label, note))

    def test_every_melodic_instrument_sounds_a_chord(self):
        # Enough blocks for the slow string and pad attacks to get going.
        for name in audioinstruments.MELODIC:
            instrument = audioinstruments.create(name, SAMPLE_RATE)
            for pitch in (48, 60, 64, 67):
                instrument.note_on(pitch, 100)
            level = peak(instrument.output, 24)
            self.assertGreater(level, 0.001, "%s is silent" % name)

    def test_patch_zero_is_what_a_fresh_instrument_plays(self):
        for name in audioinstruments.DRUM_MACHINES:
            module = audioinstruments.load(name)
            note = module.NOTE_MAP[0][0]

            fresh = module.create(SAMPLE_RATE)
            fresh.note_on(note)
            before = bytes(audiocore.get_buffer(fresh.output)[1])

            reselected = module.create(SAMPLE_RATE)
            reselected.program_change(0)
            reselected.note_on(note)
            after = bytes(audiocore.get_buffer(reselected.output)[1])

            self.assertEqual(before, after, name)

    def test_macros_accept_midi_integers_and_floats(self):
        module = audioinstruments.load("tr808")
        instrument = module.create(SAMPLE_RATE)
        instrument.set_macro(2, 64)
        instrument.set_macro(2, 64.5)      # finer than 7-bit, still legal
        instrument.set_macro(2, 0)
        instrument.set_macro(2, 127)

    def test_all_notes_off_releases_everything(self):
        module = audioinstruments.load("tr808")
        instrument = module.create(SAMPLE_RATE)
        for note, _ in module.NOTE_MAP:
            instrument.note_on(note)
        self.assertTrue(instrument.synth.pressed)
        instrument.all_notes_off()
        self.assertEqual(instrument.synth.pressed, ())


if __name__ == "__main__":
    unittest.main()
