"""Test-only ulab bridge. This directory is excluded from distributions."""

import numpy as _np


def array(value, dtype=None, *args, **kwargs):
    # ulab rounds floating-point values when converting them to integer
    # arrays; NumPy's astype-style conversion truncates toward zero.
    if dtype is _np.int16:
        source = _np.asarray(value)
        if _np.issubdtype(source.dtype, _np.floating):
            value = _np.rint(source)
    return _np.array(value, dtype=dtype, *args, **kwargs)


def linspace(start, stop, num=50, endpoint=True, dtype=None):
    return _np.linspace(start, stop, num=num, endpoint=endpoint, dtype=dtype)


concatenate = _np.concatenate
frombuffer = _np.frombuffer
int16 = _np.int16
ones = _np.ones
pi = _np.pi
sin = _np.sin
zeros = _np.zeros
