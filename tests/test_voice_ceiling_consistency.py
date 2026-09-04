"""The voice ceiling lives in five places. This asserts they agree.

Why this test exists, and why it is not paranoia:

Every parity gate in this repository is **byte-identical at N=14, 36 and 56**
-- measured, not assumed. The four verify_* gates and the rest of this suite
render material that never fills 14 channels and never crosses the mix-down
knee at +/-28000, so none of them can observe a change to
CIRCUITPY_SYNTHIO_MAX_CHANNELS at all.

That means a ceiling change applied to three of the five sites ships GREEN.
Nothing else in CI would say a word. This test is the only thing standing
between a half-applied ceiling and a release.

The five sites are genuinely independent -- three build paths plus two
constants inside the CPython target, which does not read the header
(setup.py builds _audioif from src/cpython/ and src/shared/ only, never from
src/synthio/). There is no mechanism making them agree; only this check.

DELIBERATELY NOT INCLUDED: `_audioif.c`'s `0x0fffffff / (32768 * 2 - 28000)`
is SYNTHIO_MIX_DOWN_SCALE(2) faithfully mirroring upstream CircuitPython's
own two-channel default in a code path that is not ours to re-tune. It is a
literal 2 that must stay 2. If you are here because you changed the ceiling
and this test still passed, check that you did not "fix" that line too.
"""

import hashlib
import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]

#: The pinned CircuitPython oracle binary, and its hash.
#:
#: The oracle is built at 14 and must never be rebuilt (AGENTS.md, "The
#: CircuitPython oracle -- extend, never modify"). The hole this closes: a
#: CFLAGS_EXTRA rebuild of the oracle needs no edit to any tracked file,
#: leaves `git -C cmods/circuitpython status` clean, and overwrites the
#: gitignored binary in place. Every existing check would pass on a silently
#: different oracle. Comparing the bytes is the only thing that notices.
ORACLE = ROOT.parent / "cmods" / "bin" / "circuitpython"
ORACLE_SHA256 = (
    "9c1f5d34f6b092b53df59cc55ffe6a5ff5f0c3e614b5e3a3583ab8a03465fe3a")


def _search(relative, pattern):
    """The single integer `pattern` captures in `relative`, or a failure."""
    path = ROOT / relative
    text = path.read_text()
    found = re.findall(pattern, text, re.M)
    if len(found) != 1:
        raise AssertionError(
            "%s: expected exactly one match for %r, found %d. The ceiling "
            "moved or the file was restructured; fix this test deliberately "
            "rather than loosening the pattern." % (relative, pattern,
                                                    len(found)))
    return int(found[0]), path


#: (label, path, regex capturing the ceiling as group 1).
SITES = (
    ("header default",
     "src/synthio/__init__.h",
     r"^#define CIRCUITPY_SYNTHIO_MAX_CHANNELS \((\d+)\)"),
    ("Make ports",
     "micropython.mk",
     r"^CFLAGS_USERMOD \+= -DCIRCUITPY_SYNTHIO_MAX_CHANNELS=(\d+)"),
    ("CMake ports",
     "micropython.cmake",
     r"INTERFACE CIRCUITPY_SYNTHIO_MAX_CHANNELS=(\d+)\)"),
    ("CPython target, admission",
     "src/cpython/synthio.py",
     r"^    max_polyphony = (\d+)"),
    ("CPython target, extension default",
     "src/cpython/_audioif.c",
     r"^    unsigned int max_polyphony = (\d+);"),
)


class VoiceCeilingConsistency(unittest.TestCase):

    def test_all_five_sites_agree(self):
        values = {}
        for label, relative, pattern in SITES:
            value, path = _search(relative, pattern)
            values[label] = (value, "%s" % relative)

        distinct = {v for v, _ in values.values()}
        if len(distinct) != 1:
            lines = ["the voice ceiling disagrees across its five sites:"]
            for label, (value, where) in values.items():
                lines.append("    %-34s %3d   (%s)" % (label, value, where))
            lines.append("")
            lines.append(
                "    A patch behaves differently depending on how audioif was "
                "built. No other gate here can see this -- every "
                "parity gate is byte-identical across ceiling values -- so if "
                "you are reading this message, this test is the only reason "
                "you know.")
            raise AssertionError("\n".join(lines))

    def test_cpython_admission_and_extension_default_agree(self):
        """These two are one number wearing two hats, and they can drift.

        `synthio.py`'s value gates admission AND is passed to
        `_audioif.mixdown_i32` as the limiter's divisor. `_audioif.c`'s is the
        default for callers who pass nothing. If they diverge, a caller using
        the default limits to a different voice count than the engine admits.
        """
        admission, _ = _search(SITES[3][1], SITES[3][2])
        default, _ = _search(SITES[4][1], SITES[4][2])
        self.assertEqual(
            admission, default,
            "src/cpython/synthio.py:max_polyphony (%d) and "
            "src/cpython/_audioif.c's default (%d) must match: the first "
            "feeds mixdown_i32 as the limiter divisor, the second is what a "
            "caller gets who passes nothing."
            % (admission, default))

    def test_oracle_binary_is_the_pinned_one(self):
        if not ORACLE.exists():
            self.skipTest("oracle binary absent at %s" % ORACLE)
        digest = hashlib.sha256(ORACLE.read_bytes()).hexdigest()
        self.assertEqual(
            digest, ORACLE_SHA256,
            "\n    the CircuitPython oracle binary is not the pinned build."
            "\n      expected %s"
            "\n      got      %s"
            "\n"
            "\n    Every parity golden in this repository is measured against "
            "this binary. A rebuild with different flags -- a raised "
            "CIRCUITPY_SYNTHIO_MAX_CHANNELS, say -- changes what 'parity' "
            "means while leaving every tracked file untouched and every git "
            "tree clean. That is why this compares bytes and not a commit."
            "\n"
            "\n    If you rebuilt it deliberately, that is a decision for "
            "Brad and it needs its own commit saying why, with this hash "
            "updated in the same change." % (ORACLE_SHA256, digest))


if __name__ == "__main__":
    unittest.main()
