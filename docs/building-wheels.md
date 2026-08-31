# Building and publishing wheels

`pydevices-audioif` is a native CPython distribution. Build a local source
archive and wheel with:

```sh
python -m build
```

A GitHub Release `vX.Y.Z` — matching the `VERSION` file, which is also where
`_audioif.__version__` comes from — invokes the organization `publishing-v6`
workflow (the pin is the `@publishing-v6` ref in
`.github/workflows/publish-release-packages.yml`) with
`build-kind: native-and-wasm`. It builds and validates exactly 16 wheels:

- CPython 3.10–3.14, manylinux_2_28 x86_64 and Windows AMD64.
- CPython 3.13–3.14, Android API 21 arm64_v8a/x86_64 and Pyodide wasm32.

## macOS: enabled, CI-proven

macOS is enabled at the org's **CI-proven** tier ("PyDevices ships
everything for macOS that CI can prove" — see the organization
`platform-support-tiers.md`): the `test-cpython.yml` workflow builds,
installs, and runs the full unit/contract/parity suite and
`tools/validate_api.py` on `macos-latest`, and its `macos-wheels` job
runs the same cibuildwheel the release path uses — compiling the native
extension for CPython 3.10–3.14 and running the import smoke test in
each wheel — on every push, publishing nothing. Hardware audio output
on a real Mac remains **community-verified**: no Mac is on our bench,
and a field report is what promotes that claim.

**Arch choice: `macosx_arm64` only.** The runner is Apple Silicon; an
x86_64 (or universal2) wheel cross-compiled there could not run its
test-command, and an untested wheel is a claim, not a capability. An
Intel-Mac field report is what would add x86_64.

**Release-time gap, precisely:** this repository's cibuildwheel config
no longer skips macOS, but the organization wheel matrix
(`reusable-build-native-and-wasm-wheels.yml`) still runs only
`ubuntu-latest` and `windows-latest`. Until `macos-latest` is added to
that matrix, releases still produce 16 wheels; when it lands, the five
`macosx_arm64` wheels join and `expected-wheel-count` in
`publish-release-packages.yml` must move to 21 (the comment there says
the same).

The remaining exclusions, each with its cause rather than by silence:

- **musllinux** — skipped by `pyproject.toml`'s cibuildwheel `skip` list
  since the first release; no deeper cause was recorded — needs a
  decision.
- **win32** (32-bit Windows) — every Windows target here is 64-bit: the
  wheel matrix builds AMD64 only and the validation hosts are 64-bit;
  nothing in this repository has ever been built or tested 32-bit. Also in
  the cibuildwheel `skip` list.
- **Linux ARM** — cibuildwheel `archs` pins `x86_64`; building ARM wheels
  on GitHub's x86_64 runners would need QEMU emulation, which the matrix
  does not configure. Whether the build cost is worth paying is unrecorded
  — needs a decision.
- **MicroPython `.mpy`** — the native modules are firmware: MicroPython and
  CircuitPython build them from `src/` as a usermod, so there is nothing
  for MIP to carry (recorded in `publish-release-packages.yml`). The
  pure-Python tier publishes to MIP as source; compiling it to `.mpy`
  would pin it to one bytecode version per MicroPython release, and no
  decision to take that on has been made.

After TestPyPI publication, run
`python scripts/test_testpypi_install.py` on fresh Linux and Windows hosts.
