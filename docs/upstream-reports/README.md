# Drafts for adafruit/circuitpython

Three bugs this port found in CircuitPython's `shared-module/synthio/Biquad.c`,
written up as issue bodies ready to paste. **Nothing here has been filed.**

| draft | what | shape of the fix |
|---|---|---|
| [peaking-eq-sign.md](peaking-eq-sign.md) | `PEAKING_EQ` computes `b2` with the wrong sign, so a +6 dB bell is a +21 dB bass shelf | one character |
| [biquad-reset.md](biquad-reset.md) | `synthio_biquad_filter_reset()` clears half its struct, so a reset filter plays 1.3 dB of the previous audio out of silence | one line |
| [biquad-band-edges.md](biquad-band-edges.md) | Q15 coefficients and a shared sin/cos polynomial: nothing below ~300 Hz or above ~16 kHz is the filter that was asked for | a design decision, with a real MCU cost |

Each file opens with a short **note to the poster** (strip it before posting),
then a `---` and the issue body itself. The first two are one-liners a
maintainer can apply without a round trip; the third is a limitation report
with a proposed fix and its measured cost, because it is the maintainers' call
whether to take that cost, make it opt-in, or decline.

Every number in them was measured **on a build of upstream `main`** — the
CircuitPython checkout at `cmods/circuitpython`, which this repo treats as a
read-only oracle and never patches. That matters: `docs/upstream-diff.md`
carries a different "before" table for the same bugs, measured on *this port's*
copy, which by then already differed from upstream in ways that move the
numbers. Do not paste this repo's figures into an upstream issue; the ones
here are upstream's own.

The repro scripts run unmodified on a board with an `AudioOut`, and on a unix
build of CircuitPython with this repo's `audiocore.get_buffer` /
`audiocore.reset_buffer` helpers (which is how they were measured here — see
`apply_cp_patches.sh`). A maintainer on a board should replace the
`audiocore.get_buffer` loop with playing into an output and listening or
capturing; the effects are all far above the noise floor.

## Before posting

- Re-check that each bug is still on `main`. All three were verified there on
  **2026-08-27**, against `shared-module/synthio/Biquad.c` and `Biquad.h`.
- The stereo-filter bug this port also carries is **not** in here and must not
  be filed: upstream fixed it after 10.2.1. See `docs/upstream-diff.md`.
