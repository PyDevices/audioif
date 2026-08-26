"""Freeze audioif's pure-Python tier into firmware, on request.

The workspace freeze manifests (``cmods/manifest-micropython.py`` and
``cmods/manifest-circuitpython.py``) include this file for every build they
make, so anything unconditional here lands in every interpreter in the
workspace. ``audioinstruments`` alone is about 236 KB of bytecode at
``opt=3``: worth it on a board actually playing the instruments, and pure
cost everywhere else - including on rp2040-class CircuitPython builds, which
have around 1 MB for the whole firmware.

So, unlike its neighbours (``pdwidgets``, ``palettes``), this one is opt-in::

    AUDIOIF_FREEZE_LIBS=1 ./build_interpreters.sh --only mp-unix

Everywhere else these arrive by MIP, from ``<repo>/lib/<package>``, like the
rest of the PyDevices Python tiers. That is also the safer default while
this tier is still moving: a frozen copy shadows a mip-installed or
VFS-staged one, and what is running stops being what was published - the same
trap ``pydevices``' own manifest already refuses to walk into. Worth revisiting
once the library settles and a board build actually wants the RAM back.

The native modules are not affected either way. ``audiocore``, ``synthio``,
``audiodynamics``, ``audioroute`` and the rest are compiled into the firmware
by ``micropython.mk`` / ``micropython.cmake`` (or, for CircuitPython, by
``apply_cp_patches.sh``); this file only concerns the Python on top of them.
"""

import os

if 0:  # pragma: no cover - the manifest builtins, for linters only

    def package(*args, **kwargs):
        pass


def _wanted():
    value = os.environ.get("AUDIOIF_FREEZE_LIBS", "").strip().lower()
    return value in ("1", "true", "yes", "on")


if _wanted():
    package(  # type: ignore[name-defined]  # noqa: F821
        "audioinstruments", base_path="./lib", opt=3)
    package(  # type: ignore[name-defined]  # noqa: F821
        "audioeffects", base_path="./lib", opt=3)
