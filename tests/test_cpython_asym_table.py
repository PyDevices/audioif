"""The asymmetric-clip wavetable stage builds on both numeric backends.

`_build_table`'s vectorized branch used `np.abs`, which CPython's numpy has
and **ulab does not** - it ships neither `abs` nor `fabs`. So `asym=` with
`fast=True` raised `AttributeError` on every interpreter carrying ulab.

It never fired in the wild because all six real `asym=` call sites
(farfisa's four booster waves, wurlitzer's reed and bite) also pass
`fast=False`, taking the scalar path. That made it a latent crash waiting
for the day the two paths were unified - which is exactly the direction the
library is going.

The replacement is `np.maximum(acc, -acc)`: present in ulab, and exactly
absolute value rather than approximately it, because it is pure selection
with no float round trip (`np.sqrt(acc * acc)` also works here but is not
guaranteed exact).

These tests assert the property that makes the substitution safe - the
vectorized and scalar paths agree **bit for bit** on every asym table the
library actually builds - rather than asserting the digests, so they stay
meaningful if a table's harmonics are ever retuned.
"""

import os
import sys
import unittest

from audioinstruments import _support
from audioinstruments._support import _build_table

# Import the ulab bridge from tests/support -- an explicit allowlist that
# re-exports only names real ulab actually has. Swapping _support.np to it
# is what lets a CPython test catch a ulab-only bug: under plain numpy the
# pre-fix code passes, because CPython's numpy does have np.abs.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "support"))
from ulab import numpy as ulab_np  # noqa: E402

# The six real asym= call sites: farfisa.py:50-53, wurlitzer.py:44-45.
ASYM_TABLES = [
    ("farfisa string boost", [(n, 1.0 / n) for n in range(1, 40)], 0.3),
    ("farfisa flute boost", ((1, 1.0), (3, 0.2)), 0.3),
    ("farfisa oboe boost", [(n, 1.0 / n) for n in range(1, 40, 2)], 0.3),
    ("farfisa trumpet boost", ((1, 1.0), (2, 0.8), (3, 0.6), (4, 0.4)), 0.3),
    ("wurlitzer reed", ((1, 1.0), (2, 0.4), (3, 0.2), (4, 0.1), (5, 0.05)), 0.25),
    ("wurlitzer bite", ((1, 1.0), (3, 0.8), (5, 0.6), (7, 0.4), (9, 0.2)), 0.4),
]


class _UlabBackend:
    """Run _build_table's vectorized branch against the ulab allowlist."""

    def __enter__(self):
        self._real = _support.np
        _support.np = ulab_np
        return self

    def __exit__(self, *exc):
        _support.np = self._real
        return False


class TestAsymTableUnderUlab(unittest.TestCase):
    """The regression, exercised on the backend that actually had the bug.

    Pre-fix these fail with AttributeError: module 'numpy' has no attribute
    'abs'. Verified by planting the old line back and watching them go red --
    without that check this file passed against the broken code and proved
    nothing.
    """

    def test_ulab_bridge_has_no_abs(self):
        # If this ever fails the bridge has drifted from real ulab and the
        # tests below stop meaning anything.
        self.assertFalse(hasattr(ulab_np, "abs"))
        self.assertFalse(hasattr(ulab_np, "fabs"))
        self.assertTrue(hasattr(ulab_np, "maximum"))

    def test_vectorized_path_builds_every_asym_table(self):
        with _UlabBackend():
            for name, parts, asym in ASYM_TABLES:
                with self.subTest(table=name):
                    self.assertEqual(
                        len(_build_table(parts, 2048, 32000, asym, True)), 2048)

    def test_vectorized_matches_scalar_bit_for_bit(self):
        with _UlabBackend():
            for name, parts, asym in ASYM_TABLES:
                with self.subTest(table=name):
                    scalar = list(_build_table(parts, 2048, 32000, asym, False))
                    fast = list(_build_table(parts, 2048, 32000, asym, True))
                    self.assertEqual(scalar, fast)


class TestAsymTableBackendAgreement(unittest.TestCase):
    def test_vectorized_path_builds_every_asym_table(self):
        """The regression itself: this raised AttributeError under ulab."""
        for name, parts, asym in ASYM_TABLES:
            with self.subTest(table=name):
                table = _build_table(parts, 2048, 32000, asym, True)
                self.assertEqual(len(table), 2048)

    def test_vectorized_matches_scalar_bit_for_bit(self):
        for name, parts, asym in ASYM_TABLES:
            with self.subTest(table=name):
                scalar = list(_build_table(parts, 2048, 32000, asym, False))
                fast = list(_build_table(parts, 2048, 32000, asym, True))
                self.assertEqual(scalar, fast)

    def test_asym_actually_changes_the_waveform(self):
        """Guards the guard: an asym stage silently skipped would make every
        assertion above pass while testing nothing."""
        parts = ((1, 1.0), (3, 0.8), (5, 0.6), (7, 0.4), (9, 0.2))
        plain = list(_build_table(parts, 2048, 32000, 0.0, True))
        shaped = list(_build_table(parts, 2048, 32000, 0.4, True))
        self.assertNotEqual(plain, shaped)


if __name__ == "__main__":
    unittest.main()
