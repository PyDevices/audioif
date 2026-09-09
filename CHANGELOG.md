## Unreleased

- Every node type releases: `deinit()` on the twelve that had none, and the deinitialised guard on the one funnel every pull goes through
- `audioroute.Splitter` can be released, and releasing it releases its taps
- A released `SplitterTap` refuses a rewind on the CPython target instead of quietly succeeding
- clean-build: MicroPython v1.29.0, and the deinit surface is gated on a real native build

## v0.3.0 (2026-09-09)

- Give the CPython target CircuitPython 10.3.0's new delay, speed and filter-chain nodes.
- Enable audiospeed on coverage, with the warning downgraded for its objects only
- Neither audiospeed nor audiofilewriter can be reached on unix coverage
- Compile audiospeed and audiofilewriter into the unix coverage build
- --dry-run now checks the anchors it claims it would insert after
- --status exits nonzero when the tree is not in the applied state
- apply_cp_patches: the mid/side kernel is listed in the CircuitPython variant Makefile too
- flake8: .deps on its own line
- parity: the mid/side probe runs on MicroPython too, and flake8 skips the vendored ulab
- build: every merged source block in micropython.mk opens its own SRC_USERMOD_C list
- build: the ladder's sources get their own SRC_USERMOD_C block again
- mpaudio_modules: the own-module roll call names all six, not four
- Effects Phase 1 integration: re-capture the DSP golden with the oracle
- Smoke audioshaper in the clean-build workflow, and name it in the porting plan
- Record audioshaper: what the palette could not do, and what the node measures
- apply_cp_patches.sh carries audioshaper into a CircuitPython tree
- porting-plan: the palette lacked a frequency divider, not just a stream multiply
- The hysteresis half-width is a coercivity, not a post-gain number
- Cover MidSide's surface where Dynamics' and Splitter's is covered
- Give audiomath an analog octave divider, so a sub-octave is not a pitch shift
- Reading a coefficient should not move an LFO along
- Record MidSide where the other four own nodes are recorded
- Give audioroute a mid/side matrix, so a drive can work on the middle of an image
- Write down what audiobiquad is for, and where the numbers came from
- A parity probe and a golden for audioshaper.Waveshaper
- Cite the Freeverb kernel by line, and say precisely where its all-passes sit
- audiobiquad reaches CircuitPython too, additively
- The tilt converts dB through expf, not powf, and the plan names tier 7's sixth
- audioshaper.Waveshaper: the curve arrives as data, and the shaping happens above the sample rate
- Record audioverb in upstream-diff, README and the module lists, and test it
- audiobiquad on MicroPython: the same two kernels, the same block reads
- Golden the ladder, and assert in numbers that the bytes are a ladder
- audioverb reaches CircuitPython too, through the additive path
- audioverb.Tank: a reverberation tank whose network comes from Python
- Give the palette a filter whose tail actually reaches zero
- audioladder on the other three targets: MicroPython, and the CP tree
- A transistor ladder, solved rather than delayed, on the CPython target
- audiodynamics: record the twenty-one options as a deviation, with the measurements
- audiodynamics: a parity probe for the twenty-one options, and its golden
- audiodynamics: the new options on all four targets, and an external key input
- audiodynamics: twenty-one additive options on the shared dynamics kernel
- Say what the loop shift costs in repeat time, in all three places it is documented
- Record the four FeedbackDelay options: what they were asked for, what they measure
- A parity probe and a golden for the four new FeedbackDelay options
- Four options on audioecho.FeedbackDelay, all off by default
- upstream-diff: the audible half of the ceiling raise is refused voices, not the knee
- upstream-diff: the voice ceiling is 64 where CircuitPython builds 14
- Re-pin the CircuitPython oracle to the bytes it has, with the provenance the relink never recorded
- Clean the single-precision narrowing, so the float CI cell can run at -Werror
- A fifth parity gate whose material crosses the mix-down knee
- build: micropython.cmake finds ulab in .deps/ or a sibling, so the standalone claim holds on CMake ports
- packaging: numpy is the [render] extra, so a bare install is honest about audiorender
- Move the attribution out of LICENSE so GitHub can detect MIT
- PR #11289: the reply is posted
- PR #11289: draft reply to relic-se, with the measurement behind it
- synthio: raise the voice ceiling from 14 to 64
- tests: assert the five voice-ceiling sites agree, and pin the oracle's bytes
- parity: re-capture the vst3 render reference against audiocomponents at the v0.2.0 core
- lib: delete audioinstruments and audioeffects -- they live in audiocomponents

- audiodynamics: twenty-one additive options and an external key input, for the effects program (#38)
- audioroute: MidSide, a zero-latency mid/side matrix, exact identity at width=1
- audioshaper: a new audioif-own module -- a table waveshaper, oversampled x2/x4/x8, with an off-by-default hysteresis option
- packaging: numpy is the `render` extra, so a bare install says honestly what audiorender needs

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

