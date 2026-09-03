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
  `<repo>/lib/<package>`. `lib/audioinstruments/` (53 `synthio`
  instruments) and `lib/audioeffects/` (46 effect classes, effect racks
  included) are standalone
  PyPI distributions (`pydevices-audioinstruments`,
  `pydevices-audioeffects`, each with its own `pyproject.toml`, depending
  on `pydevices-audioif`) and are deliberately NOT in this repo's wheel —
  the same files in two distributions would collide. `lib/audiorender/`
  (whole-composition offline rendering — numpy, desktop-only, never
  frozen) still ships inside the `pydevices-audioif` wheel.
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
  - `.venv/bin/python tests/parity/run_instruments_parity.py --verify --batch all \
    --micropython ../cmods/bin/micropython --circuitpython ../cmods/bin/circuitpython`
    renders each original `vstaudio` instrument script and holds the ported
    module to it. Comparison is always within one interpreter — `ulab`'s
    vectorized sine and libm's are different functions.
  - `.venv/bin/python tests/parity/verify_dsp.py --micropython ../cmods/bin/micropython \
    --circuitpython ../cmods/bin/circuitpython \
    --oracle ../cmods/micropython/ports/unix/build-vstaudio-oracle/micropython`
    does the same for `audiodynamics` and
    `audioroute` against `vstaudio_dsp.c` compiled unmodified by
    `MP_UNIX=../cmods/micropython/ports/unix ULAB_DIR=../cmods/ulab
    tests/parity/build_vstaudio_oracle.sh`. One hash covers every
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
- **The parity/oracle gates are workspace-local by design.** They need
  built interpreters (`bin/circuitpython`, the workspace MicroPython) and
  golden captures that live outside this repository, so external
  contributors cannot run them and CI does not try. **Since 2026-09-03 the
  scripts' zero-argument defaults no longer point into `cmods/`** — a
  standalone user should not be steered into a directory only this
  workspace has — so in *this* workspace every parity command needs the
  explicit `--micropython`/`--circuitpython`/`--oracle` (or `CP_DIR`,
  `MP_UNIX`, `ULAB_DIR`) override shown above. Run one bare and it does not
  fail loudly: `run_instruments_parity.py` prints `skipping micropython`
  and verifies only the cpython leg. That is not a pass. What CI
  covers instead is the structural contract: `test_audio_component_api`,
  `test_metadata_contract`, `tools/validate_api.py`, and the CPython
  fixture tests in `tests/test_cpython_*.py`.

## The CircuitPython oracle — extend, never modify

`cmods/circuitpython` (sibling checkout, detached at tag `10.2.1`) is the
**oracle** every parity golden is measured against. The rule, for any agent
working here:

- **Never edit files in `cmods/circuitpython` directly**, and never commit,
  pull, or move its pin. A modified oracle silently redefines what "parity"
  means and invalidates every golden without failing anything.
- **Extending CircuitPython is fine and is the designed path**: new modules
  live in this repo under `src/circuitpython_spike/`, and
  `apply_cp_patches.sh` copies them (plus `src/shared/` DSP) into the CP
  tree. The script is **additive-only by design** — it adds files and
  registers them in build glue; the sole stock-file rewrite it performs is
  the fenced audiocore `'B'`-memoryview patch. Do not add non-additive
  rewrites to it: `cmods/build_cp.sh` auto-applies the script before
  building `bin/circuitpython`, so a behavioral rewrite would leak *into*
  the oracle.
- Fixes to bugs that also exist upstream go in **this repo's targets only**
  (MicroPython/CPython/`src/shared/`), recorded in `docs/upstream-diff.md`
  — never into the CP tree. Approved deviations from the oracle are
  enumerated there; **ask before adding one**.
- Quick self-check after any CP-adjacent work:
  `CP_DIR=../cmods/circuitpython ./apply_cp_patches.sh --status` must account
  for every difference (bare, the script no longer finds the tree here and
  says `CircuitPython tree not found (set CP_DIR)`), and
  `git -C ../cmods/circuitpython status` must show only the known additive
  set (new module dirs, build glue, the fenced audiocore rewrite) — no
  changes under `shared-module/`/`shared-bindings/` for `synthio`,
  `audiofilters`, `audiocore` (beyond the fence), `audiomixer`, or
  `audiodelays`.
