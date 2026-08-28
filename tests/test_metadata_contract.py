import unittest
from types import SimpleNamespace

from tools.validate_metadata import MetadataError, validate_component


def component(**fields):
    defaults = {
        "NAME": "example",
        "MACRO_LABELS": (),
        "MACRO_MODES": {},
        "PATCHES": {0: ("Default", ())},
    }
    defaults.update(fields)
    return SimpleNamespace(**defaults)


class MetadataContractTest(unittest.TestCase):
    def test_macroless_component_is_valid_when_empty_fields_are_explicit(self):
        self.assertFalse(validate_component(component(), kind="instrument"))

    def test_missing_required_field_is_invalid_even_when_the_value_is_empty(self):
        owner = component()
        del owner.MACRO_MODES
        with self.assertRaises(MetadataError):
            validate_component(owner, kind="instrument")

    def test_modes_are_complete_and_toggle_patches_are_discrete(self):
        owner = component(
            MACRO_LABELS=("Power", "Drive"),
            MACRO_MODES={0: "TOGGLE", 1: "UNIPOLAR"},
            PATCHES={0: ("Default", (64, 64))},
        )
        with self.assertRaises(MetadataError):
            validate_component(owner, kind="instrument")

    def test_malformed_patch_values_report_metadata_error(self):
        owner = component(PATCHES={0: ("Default", (128,))},
                           MACRO_LABELS=("Level",),
                           MACRO_MODES={0: "UNIPOLAR"})
        with self.assertRaises(MetadataError):
            validate_component(owner, kind="instrument")

    def test_percussion_is_defined_by_a_valid_note_map(self):
        melodic = component()
        self.assertFalse(validate_component(melodic, kind="instrument"))

        percussion = component(NOTE_MAP=((36, "Bass Drum"),))
        self.assertTrue(validate_component(percussion, kind="instrument"))

    def test_note_map_is_not_valid_on_an_effect(self):
        with self.assertRaises(MetadataError):
            validate_component(
                component(NOTE_MAP=((36, "Bass Drum"),)), kind="effect")

    def test_public_engineering_ranges_are_rejected(self):
        with self.assertRaises(MetadataError):
            validate_component(component(MACRO_RANGES=()), kind="effect")


if __name__ == "__main__":
    unittest.main()
