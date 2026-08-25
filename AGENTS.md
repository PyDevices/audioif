# AGENTS.md — audioif

CircuitPython's audio system (`audiocore`, `synthio`, `audiomixer`, effects,
`audiomp3`), ported to MicroPython as `USER_C_MODULES` usermods. Import
names match CircuitPython exactly (`import audiocore`, `import synthio`, …)
for source compatibility; only this repo's own name differs.

## Layout

- Root: `micropython.mk` (unix/windows, Make-based ports), `micropython.cmake`
  (esp32/rp2, CMake-based ports) — build glue for `USER_C_MODULES` discovery
- `src/` — one directory per module (`audiocore/`, `synthio/`, `audiomixer/`,
  `audiospeed/`, `audiofreeverb/`, `audiofilters/`, `audiodelays/`,
  `audiomp3/`), plus `src/cp_compat/` (CircuitPython-only core primitives
  ported as standalone compat shims, each individually verified against
  mainline MicroPython before use — not assumed missing)
- `docs/porting-plan.md` — the full phased porting history, architecture,
  and target layout
- `docs/upstream-diff.md` — every deliberate deviation from upstream
  CircuitPython, with rationale (verbatim-kept quirks vs. genuine port bugs
  found and fixed)
- `tests/parity/` — oracle-diff scripts, run unchanged against both this
  port and `bin/circuitpython`
- `tests/vendor/` — vendored third-party test fixtures (e.g. `synthtools`)

## Sibling dependencies (cloned, not vendored)

- `ulab` (numpy-alike) — pinned to the exact revision CircuitPython itself
  vendors
- `cmods/mp3` (upstream `adafruit/Adafruit_MP3`, the Helix MP3 decoder core
  `audiomp3` wraps) — RPSL 1.0/RCSL 1.0 licensed, *not* MIT; carried
  unmodified per upstream's own terms, same as CircuitPython itself. Kept
  as a separate sibling clone rather than folded into this (MIT) repo's own
  tree.

Both are expected as siblings in the parent workspace (`cmods/` in
`pydevices`), same pattern as `pygraphics`/`displayif`.

## Testing

- Oracle diffing is the core discipline: every parity script under
  `tests/parity/` runs unchanged against this port and `bin/circuitpython`,
  rendering PCM and diffing byte-for-byte (or documenting the exact,
  bounded exception in `docs/upstream-diff.md`).
- Full regression after any change: rebuild interpreters
  (`build_interpreters.sh` in the parent workspace), run the tier 0-5
  parity suite plus `tests/parity/synthtools_acceptance.py`, and the LVGL
  smoke test.
- See `docs/porting-plan.md`'s "Testing strategy" section for the complete
  methodology.
