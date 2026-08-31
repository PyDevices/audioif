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

The exclusions, each with its cause rather than by silence:

- **macOS** — the organization wheel matrix
  (`reusable-build-native-and-wasm-wheels.yml`) has no macOS runner, and no
  macOS host exists in this workspace to validate a wheel on; an
  unvalidated wheel would be a claim, not a capability. Whether to add a
  runner is a cost/validation decision that is unrecorded — needs a
  decision.
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
