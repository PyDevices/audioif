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

