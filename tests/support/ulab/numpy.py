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
    """ulab's linspace, arithmetic included, not NumPy's.

    Ported from ulab code/numpy/create.c: `create_linspace` derives the step,
    then `create_linspace_arange`/`ARANGE_LOOP` fills the array by RUNNING
    ACCUMULATION and writes the final element as `stop` directly rather than
    accumulating into it. Narrowing to an integer dtype is a C cast, so it
    truncates toward zero; NumPy's `dtype=` rounds.

    All three differences bite. On a 256-point ramp from +28000 to -28000,
    NumPy's rounding alone puts 127 of 256 values one LSB out; the accumulation
    accounts for two more, and the special-cased last element for one. It showed
    up as `synthtools_acceptance`'s `bend` and `bass` checksums disagreeing
    between the CPython twin and desktop MicroPython -- which looked like a DSP
    divergence, and was this. Verified element-for-element against real ulab on
    the workspace MicroPython over a randomised sweep, 2026-09-09.

    `mp_float_t` is double on the desktop ports, so plain Python floats are the
    right width here.
    """
    count = int(num)
    # ulab refuses fewer than two points outright, so the bridge does too --
    # a board would raise here and a test must not sail past it.
    if count < 2:
        raise ValueError("number of points must be at least 2")
    if dtype is None:
        return _np.linspace(start, stop, num=count, endpoint=endpoint)
    start = float(start)
    stop = float(stop)
    if endpoint:
        step = (stop - start) / (count - 1)
    else:
        step = (stop - start) / count
        stop = start + step * (count - 1)
    values = []
    value = start
    for _ in range(count - 1):
        values.append(_trunc_toward_zero(value))
        value += step
    values.append(_trunc_toward_zero(stop))
    return _np.array(values, dtype=dtype)


def _trunc_toward_zero(value):
    """A C cast to an integer type: toward zero, not NumPy's round-half-even."""
    return int(value)


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
