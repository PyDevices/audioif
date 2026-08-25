#!/usr/bin/env python3
"""Smoke a fresh pydevices-audioif install from TestPyPI."""

from array import array
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


with tempfile.TemporaryDirectory(prefix="audioif-testpypi-") as directory:
    root = Path(directory)
    venv.EnvBuilder(with_pip=True).create(root)
    python = root / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    subprocess.run([
        str(python), "-m", "pip", "install",
        "--index-url", "https://test.pypi.org/simple/",
        "--extra-index-url", "https://pypi.org/simple/",
        "pydevices-audioif==0.0.1",
    ], check=True)
    code = """
from array import array
import audiocore, synthio
s = synthio.Synthesizer(sample_rate=8000)
s.press(69)
r, b = audiocore.get_buffer(s)
assert r == 1 and b.format == 'B' and len(b) == 512
assert audiocore.get_buffer(audiocore.RawSample(array('h', [1, 2])))[0] == 0
"""
    subprocess.run([str(python), "-c", code], check=True)
