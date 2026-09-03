## v0.2.0 (2026-09-03)

- test-cpython: the matrix comment no longer names a validator that left with the components
- synthio: one polyphony ceiling, 14, on every build path
- docs: the instrument and effect libraries live in audiocomponents
- packaging: nothing here freezes or ships the component packages
- publish: audioif no longer publishes the component packages or MIP
- tests: component tests and the instruments gate go to audiocomponents
- ci: bump the actions group across 1 directory with 2 updates (#10)
- README: the standalone claim holds for Make ports; CMake ports still need a sibling ulab
- verify_effects: re-accept aarch64 under the byte-checksum format, from the CI report
- parity: the acceptance gate now sees byte order, not just a sum
- parity: the effects gate hashes bytes, not just their sum
- parity: the biquad gate now covers Note.filter, Q and A, and sees byte order
- audiomixer: a source that promises data and delivers none must not hang
- parity: retire the 40 instruments af837de changed on purpose
- parity: re-capture 19 cpython digests stranded by b420dac
- AGENTS.md: the stored parity digests stay (#26 reversed) and why
- AGENTS.md: two kinds of golden, two rules
- parity: verify_acceptance no longer discards the caller's PYTHONPATH
- docs: fix the four audit defects in the readability batch, and my own aarch64 note
- parity scripts: drop hardcoded cmods paths
- apply_cp_patches.sh: drop the cmods-specific sibling fallback
- docs: reword cmods-workspace mentions to a generic term
- readme: document a standalone MicroPython build recipe
- readme: add Installation section to audiorender
- readmes: add Installation sections to audioeffects and audioinstruments
- readme: restructure for scannability, add direct audioif install line
- docs: note where the component docs will live
- spec: record why patch values are integers, and that it is settled
- instruments: log-map time and filter-frequency macros, and re-derive patch 0
- build: the excess voices are REFUSED, not stolen - fix both comments
- cpython: give a released note's channel back before its tail ends
- wheels: record what the ARM lane found, and the rule it settled
- verify_effects: per-architecture exact baselines, no tolerance anywhere
- verify_effects: report WHAT differs, not just that a hash moved
- wheels: add Linux aarch64 (CI-proven), keep musllinux skipped
- _support: asym wavetables crash on ulab -- np.abs does not exist there
- cpython: make envelope reassignment live, matching the oracle
- synthio: implement ring modulation on the CPython target
- upstream: synthio re-press fix submitted as circuitpython#11289
- PR: describe the test we actually ship, not the two-note bisection
- PR: cut the body to house style, 163 words to 75
- PR draft: record the independent mechanism check against upstream main
- check_attribution: drop an unused import that would have reddened CI
- Attribution: catch the 12 my first sweep missed, and guard it in CI
- Prepare upstream PR for synthio note re-press dropping at envelope level 0
- upstream-diff: we filed five and four are merged, not 'none has been filed'
- Restore upstream copyright attribution to every ported file
- synthio: a re-pressed finished note is a new hit, not a swell
- synthio: oracle-exact press semantics on CPython; Note.filter cascades
- ci: let Dependabot watch this repo's GitHub Actions
- upstream ledger: band-edges reframed and posted on #11269; PR waits on maintainer appetite
- upstream ledger: all four fix PRs merged upstream (#11275-#11278)
- upstream ledger: four fix PRs filed (adafruit/circuitpython #11275-#11278); band-edges awaits its design framing

## v0.1.1 (2026-08-31)

- release chain: publishing-v7 -> publishing-v8

## v0.1.0 (2026-08-31)

- Prepare upstream PRs for dds-oscillator-off-by-one, distortion-soft-clip-union, biquad-reset
- docs: prepared upstream PR for peaking-eq-sign (#11265) -- patch and paste-ready body
- docs: the two-layer sound guarantee -- the CircuitPython-parity core is the floor, the components evolve
- docs: the sound-stability contract on all three front pages
- release chain: pin publishing-v7, expect 21 wheels (macOS arm64 joins)
- docs: racks are delivered — shipped-status recordings and the 46-class count everywhere
- audioeffects: effect racks — Rack mechanism plus ShimmerHall and AirSpace, ported from micropython-vst3
- setup.py: -ffp-contract=off on macOS so arm64 wheels match the parity oracle
- CI: turn on the macOS lane — test matrix, wheel-build proof, arm64 config
- CI: add a single-precision cell to the clean build, complete the smoke imports
- patches: give the Adafruit_MP3 patch its provenance header and fix the dead path
- audioinstruments README: match the documented API to the implemented one
- docs: correct stale claims -- publishing pin, wheel exclusions, Android, effect count, parity locality
- README: fix the quickstart install and the wheel-contents claim
- docs: record the specified-but-unshipped component surface honestly
- CI: run every tests/test_*.py, not just test_cpython_*
- Fix MultiTapDelay tap_levels type mismatch on MCU float builds

## v0.0.5 (2026-08-29)

- Adopt publishing-v6 (MIP second-publication race fix)
- clean-build: USER_C_MODULES is the parent directory of the module
- Standalone builds: pinned deps, owned patch queue, clean-build CI
- Declare the CircuitPython oracle pin in a checked-in file

