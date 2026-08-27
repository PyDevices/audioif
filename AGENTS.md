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
  `audiomp3/`, `audiodynamics/`, `audioroute/`, `audiomath/`, `audioecho/`),
  plus `src/cp_compat/`
  (CircuitPython-only core primitives ported as standalone compat shims, each
  individually verified against mainline MicroPython before use — not assumed
  missing) and `src/shared/` (runtime-neutral DSP the MicroPython usermod and
  the CPython extension both compile)
- `src/cpython/` — the whole CPython target: `_audioif.c`, the extension built
  in place, and the twelve modules that wrap it (`audiocore.py`, `synthio.py`,
  …). They install as top-level modules, so it is `import audiocore` no matter
  which of the three runtimes is underneath. Nothing puts this directory on
  `sys.path`: audioif is a dependency, imported from wherever it is installed.
- `lib/` — the pure-Python tiers, published to boards by MIP from
  `<repo>/lib/<package>` and to PyPI in the same wheel:
  `lib/audioinstruments/` (53 `synthio` instruments), `lib/audioeffects/`
  (41 effect classes) and `lib/audiorender/` (whole-composition offline
  rendering — numpy, desktop-only, never frozen)
- `apply_cp_patches.sh` + `src/circuitpython_spike/` — add `audiodynamics`,
  `audioroute`, `audiomath` and `audioecho` to a CircuitPython tree. None of
  the four is a CircuitPython port: the first two come from micropython-vst3's
  `vstaudio` engine and the last two are audioif's own, so CircuitPython gains
  them here rather than the other way round.
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
- Two tiers have a different oracle, because CircuitPython is not where they
  came from. Both are the micropython-vst3 sibling checkout, and neither
  touches it:
  - `python3 tests/parity/run_instruments_parity.py --verify --batch all`
    renders each original `vstaudio` instrument script and holds the ported
    module to it. Comparison is always within one interpreter — `ulab`'s
    vectorized sine and libm's are different functions.
  - `python3 tests/parity/verify_dsp.py` does the same for `audiodynamics` and
    `audioroute` against `vstaudio_dsp.c` compiled unmodified by
    `tests/parity/build_vstaudio_oracle.sh`. One hash covers every
    interpreter here: the arithmetic is all in `src/shared/`, so two
    interpreters disagreeing would itself be the finding. `audiomath` rides
    along in the same file with no oracle at all — captured from the port,
    it pins cross-interpreter agreement rather than fidelity to something
    older.
- Those two oracles are the *original* scripts and `vstaudio_dsp.c`, which
  micropython-vst3 no longer carries — it imports these packages now. Both
  are read out of its git history, so they stay fixed no matter what that
  checkout does next. What covers the cutover itself is
  `python3 tests/parity/capture_render_reference.py --verify`: it renders
  the plug-in's six soundtrack pieces and compares them with what they
  sounded like beforehand. Slow (~15 min) and not part of the default gate,
  but **re-capture it after any DSP change here** or it stops meaning
  anything.
- `python3 -m flake8` is the lint gate (`.flake8`, defect checks only —
  layout is deliberately not gated). It runs in CI on every push.
- Full regression after any change: rebuild interpreters
  (`build_interpreters.sh` in the parent workspace), run the tier 0-5
  parity suite plus `tests/parity/synthtools_acceptance.py`, and the LVGL
  smoke test.
- See `docs/porting-plan.md`'s "Testing strategy" section for the complete
  methodology.
