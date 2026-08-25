# Building and publishing wheels

`pydevices-audioif` is a native CPython distribution. Build a local source
archive and wheel with:

```sh
python -m build
```

GitHub Release `v0.0.1` invokes the organization `publishing-v3` workflow
with `build-kind: native-and-wasm`. It builds and validates exactly 16 wheels:

- CPython 3.10–3.14, manylinux_2_28 x86_64 and Windows AMD64.
- CPython 3.13–3.14, Android API 21 arm64_v8a/x86_64 and Pyodide wasm32.

macOS, musllinux, win32, Linux ARM, and MicroPython `.mpy` publication are
intentionally excluded. After TestPyPI publication, run
`python scripts/test_testpypi_install.py` on fresh Linux and Windows hosts.
