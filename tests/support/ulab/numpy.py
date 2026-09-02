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


# Names below were checked one at a time against real ulab, by
# introspection on the workspace MicroPython (2026-09-02) -- not assumed.
# The allowlist is the point of this module: a name ulab lacks is absent
# here too, so a test importing this bridge fails the way a board would.
# It is a SUBSET, though, and adding to it is normal: absence here means
# "not yet needed", not "ulab lacks it". Verify before you add, and never
# add a name real ulab does not have.
#
# ulab HAS: arange max maximum sqrt (as well as everything already listed).
# ulab LACKS: abs, fabs -- which is the whole reason _build_table's asym
# stage uses maximum(acc, -acc). See test_cpython_asym_table.py.
arange = _np.arange
max = _np.max  # noqa: A001 - mirrors ulab's own name
maximum = _np.maximum
sqrt = _np.sqrt

concatenate = _np.concatenate
frombuffer = _np.frombuffer
int16 = _np.int16
ones = _np.ones
pi = _np.pi
sin = _np.sin
zeros = _np.zeros
