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

## Release outcome

The rollout is released. `pydevices-audioif` 0.0.1 and `pydevices` 0.3.7 are
both on TestPyPI, and all seven repositories are merged to `main`.

1. The `.github` changes are merged and tagged `publishing-v4`. The audioif
   caller is pinned to that tag; the other six callers stay on `publishing-v3`,
   which is safe because `expected-wheel-count` defaults to `0`. Each tag's
   nested `uses:` refs point at their own tag, so a v3 caller runs a wholly v3
   chain.
2. `audioif` merged to `main` with all ten Linux and Windows CI jobs green.
3. The organization `TESTPYPI_API_TOKEN` is visible to `audioif`: the release
   workflow's credentials preflight passed.
4. Release `v0.0.1` published exactly the 16 expected wheels, and
   `scripts/test_testpypi_install.py` passes on fresh Linux and Windows hosts.
5. The Pyodide piano demo installs `pydevices-audioif` through micropip,
   constructs a `synthio.Synthesizer`, and feeds real PCM into Web Audio -- a
   headless run scheduled 706 buffers at 24 kHz, 268 of them non-silent with a
   peak amplitude of 0.33 after tapping keys. **Android playback is the one
   piece still unvalidated**; the wheels build and publish, but neither the
   x86_64 emulator nor an arm64 device has been exercised.
6. `pydevices` `v0.3.7` published to TestPyPI, and the MIP index now serves
   `pydevices` and `pydevices-desktop` at 0.3.7.
7. The examples, Android, workspace, and portal branches are merged, and the
   org portal is live with audioif 0.0.1. The examples `requirements.txt`
   carries unpinned names rather than floors, so there was nothing to bump;
   `scripts/refresh-requirements.py` now updates floors in place instead of
   regenerating the file, which had silently dropped `--extra-index-url`,
   `pydevices-usdl2`, and `pydevices-uwin32`.

One unrelated pre-existing issue surfaced while validating: the PyScript
autotest quit handshake never emits `EXAMPLE_RESULT`, reporting the chord as
`BrowserBack`. It reproduces on demos that do not use audioif, so it is not a
regression from this work.

## Parity hashing note

The oracle hashes above are taken over LF-terminated probe output. Windows
CPython writes CRLF from the probe subprocesses, so `verify_effects.py` and
`verify_streaming.py` normalize line endings before hashing. Without that
normalization every Windows job fails with
`97000851a8e33b0911ee0494dcbb94f09fe911490a0c78183b2ff861c6ae3383` even
though the PCM is byte-identical.

Published TestPyPI artifacts are immutable. Any correction after 0.0.1 must
use a new patch version.
