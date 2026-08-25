# CPython audioif 0.0.1 handoff

## Current state

The CircuitPython-compatible audio stack has been ported to CPython and is
ready for the coordinated release workflow. CircuitPython 10.2.1 remains the
read-only behavioral and PCM oracle; no CircuitPython source changes are part
of this work.

The CPython distribution is `pydevices-audioif==0.0.1`. It publishes the
private `_audioif` extension and these seven public compatibility modules:

- `audiocore`
- `synthio`
- `audiomixer`
- `audiofilters`
- `audiodelays`
- `audiofreeverb`
- `audiospeed`

It intentionally does not publish `audioif` or `audiomp3`, has no runtime
dependencies, and requires Python 3.10 or newer.

## Implementation summary

- Shared native DSP/state implementations are consumed by both the retained
  MicroPython bindings and the new CPython extension.
- `_audioif` uses multi-phase module initialization, heap types, and GC
  traversal/clearing for native objects that retain Python references.
- `audiocore.get_buffer()` returns result code `0`, `1`, or `2` with an owned
  byte-format `memoryview`.
- Synthesizer, MIDI, mixer, filters, delays, Freeverb, and SpeedChanger are
  implemented with CircuitPython-compatible public imports and deterministic
  output.
- Deinitialization releases exporter/source graphs and rejects subsequent
  public access. Enum representations and `Envelope` tuple behavior match the
  oracle surface used by the compatibility tests.
- Packaging includes `VERSION`, PEP 517/setuptools configuration, the native
  headers needed by source-distribution builds, wheel documentation, and a
  standalone fresh-TestPyPI smoke script.

## Oracle and validation results

Committed fixture hashes were produced from the untouched CircuitPython
10.2.1 oracle and are checked in CI:

- synthtools acceptance:
  `adc66c885cd07aeeb7245505c33faf34ea8ef4449f43ba7b1694691a30cc1305`
- effects:
  `fe1e6b8c997ee7c5dfacb7eb8193a98c74c0896189e4afffd88c98ca0acdd2cd`
- streaming/mixer:
  `74f62c068765c7e3fb134acd9acab1091f7a7c087a715a233ef63167d18f2fdc`
- MIDI:
  `3399ca41c8178aae99405ce54c82b167e9fa02f83890a9de0f07b1ffb28d0d65`

The following validation was completed locally:

- CPython 3.10 through 3.14: API, lifecycle/GC, synthtools, effects,
  streaming/mixer, and MIDI tests pass.
- MicroPython Unix and Windows: all four hashes match the oracle.
- Windows MicroPython parity and LVGL smoke output were written beneath
  `%TEMP%` and launched through PowerShell.
- MicroPython Unix, Windows, and WASM interpreters rebuilt successfully; Unix
  and Windows LVGL smoke tests pass.
- The end-to-end `Synthesizer -> Mixer -> effect -> AudioOut -> emulated WAV`
  render is byte-identical across CPython, MicroPython, and CircuitPython.
- `pydevices`: 395 tests pass, with 21 environment-dependent skips.
- `pydevices-examples`: 24 tests and the generated-gallery check pass.
- Android recipes compile, portal generation is idempotent, changed workflow
  YAML parses, all changed repositories pass `git diff --check`, and the
  source distribution plus local wheel pass `twine check`.
- An isolated CPython 3.14 wheel install imports exactly the intended modules;
  `audioif` and `audiomp3` remain unavailable.

## Related repository changes

The rollout spans these repositories, using the branch
`codex/audioif-cpython-rollout` in each:

- `audioif`: shared core, CPython API, tests, package, and release caller.
- `pydevices`: version 0.3.7, `audiodev` integration, backend selection,
  documentation, tests, and rebuilt MicroPython binaries.
- `pydevices-examples`: audioif requirement/refresh order, portable waveform
  generation, and Pyodide dependency discovery.
- `android-template` and `android-runner`: pinned audioif recipe and build
  requirement.
- `.github`: exact wheel-count workflow input, publishing documentation,
  workspace install tooling, and portal metadata.
- `PyDevices.github.io`: regenerated portal and refreshed MicroPython WASM
  artifacts. The existing MicroPython hero runtime is retained.

## Wheel and release matrix

The native release is configured to validate exactly 16 wheels:

- CPython 3.10-3.14: manylinux_2_28 x86_64 and Windows AMD64.
- CPython 3.13-3.14: Android API 21 arm64_v8a and x86_64.
- CPython 3.13-3.14: Pyodide wasm32.

macOS, musllinux, win32, Linux ARM, and MIP publication are excluded.

## Remaining release work

1. Done. The `.github` changes are merged to `main` and tagged
   `publishing-v4` (`7bd6919`); the audioif caller is pinned to that tag.
   `publishing-v3` was left in place so earlier release retries stay
   reproducible. The other six callers remain on v3, which is safe because
   `expected-wheel-count` defaults to `0`.
2. Done. The `audioif` branch merged to `main` after CI went green on all ten
   Linux and Windows jobs.
3. Confirm the organization `TESTPYPI_API_TOKEN` is visible to `audioif`.
   The release workflow contains a credentials preflight; the current local
   GitHub token cannot inspect organization Actions secrets.
4. Publish GitHub release `v0.0.1`, require exactly 16 collected wheels, and
   run `python scripts/test_testpypi_install.py` on fresh Linux and Windows
   hosts.
5. Validate the installed Pyodide piano/Web Audio path and Android x86_64
   emulator plus arm64 device playback.
6. Merge and publish `pydevices` `v0.3.7`; both 0.0.1 and 0.3.7 were confirmed
   unused before implementation.
7. Merge the examples, Android, workspace, and generated portal branches, then
   refresh example package floors after TestPyPI contains 0.0.1 and 0.3.7.

## Parity hashing note

The oracle hashes above are taken over LF-terminated probe output. Windows
CPython writes CRLF from the probe subprocesses, so `verify_effects.py` and
`verify_streaming.py` normalize line endings before hashing. Without that
normalization every Windows job fails with
`97000851a8e33b0911ee0494dcbb94f09fe911490a0c78183b2ff861c6ae3383` even
though the PCM is byte-identical.

Published TestPyPI artifacts are immutable. Any correction after 0.0.1 must
use a new patch version.
