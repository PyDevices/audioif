#!/usr/bin/env python3
"""Hold the three definitions of the voice ceiling to the same number.

`CIRCUITPY_SYNTHIO_MAX_CHANNELS` is written down in three places, and a patch
behaves the same wherever it is built only while they agree:

    src/synthio/__init__.h   the `#ifndef` default, used by any build that
                             defines nothing
    micropython.mk           the Make path (unix, windows)
    micropython.cmake        the CMake path (esp32, rp2)

`micropython.cmake`'s own comment on that line says what this script is for:
*"No gate anywhere exercises this constant: nothing in .github/ or tools/
invokes CMake."* Three numbers that must match and no check over them is the
shape where two of them drift and the third is the one you happen to test.
The ceiling has already moved twice - 2 to 8, 8 to 14, 14 to 64 - and the
14 to 64 move is the one whose note records collapsing "the three-numbers
problem".

This reads the value out of each file rather than being told it, so raising
the ceiling means editing three lines and nothing here.

    scripts/check_voice_ceiling.py            # agree, or exit 1
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: (label, path, pattern). Each pattern must capture the number, and each
#: file must yield exactly one match - two would mean a stale line left
#: beside a new one, which is the drift this exists to catch.
SOURCES = (
    ("header default", "src/synthio/__init__.h",
     r"^\s*#define\s+CIRCUITPY_SYNTHIO_MAX_CHANNELS\s+\(?(\d+)\)?\s*$"),
    ("Make path", "micropython.mk",
     r"^\s*CFLAGS_USERMOD\s*\+=\s*-DCIRCUITPY_SYNTHIO_MAX_CHANNELS=(\d+)\s*$"),
    ("CMake path", "micropython.cmake",
     r"^\s*target_compile_definitions\(usermod_mpaudio INTERFACE\s+"
     r"CIRCUITPY_SYNTHIO_MAX_CHANNELS=(\d+)\)\s*$"),
)


def read(label, relative, pattern):
    path = ROOT / relative
    if not path.exists():
        raise SystemExit("%s: %s is missing" % (label, relative))
    found = re.findall(pattern, path.read_text(), re.MULTILINE)
    if not found:
        raise SystemExit(
            "%s: no CIRCUITPY_SYNTHIO_MAX_CHANNELS in %s - either it was "
            "removed, or the line was reshaped and this pattern needs "
            "updating with it" % (label, relative))
    if len(found) > 1:
        raise SystemExit(
            "%s: %s defines CIRCUITPY_SYNTHIO_MAX_CHANNELS %d times (%s); "
            "one of them is stale" % (label, relative, len(found),
                                      ", ".join(found)))
    return int(found[0])


def main():
    values = [(label, relative, read(label, relative, pattern))
              for label, relative, pattern in SOURCES]
    width = max(len(label) for label, _, _ in values)
    for label, relative, value in values:
        print("%-*s %-24s %d" % (width, label, relative, value))

    distinct = set(value for _, _, value in values)
    if len(distinct) != 1:
        print()
        print("FAIL: the voice ceiling disagrees across %d definitions %s. A "
              "patch built through one path would refuse presses that another "
              "accepts, silently - find_channel_with_note() drops a press "
              "outright when every channel is held." % (len(distinct),
                                                        sorted(distinct)))
        return 1
    print()
    print("PASS: all three agree at %d voices" % distinct.pop())
    return 0


if __name__ == "__main__":
    sys.exit(main())
