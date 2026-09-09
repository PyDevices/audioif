# What audioif is held to

Decided with Brad on 2026-09-09, replacing every earlier arrangement. One page,
because the previous answer was spread across a golden file, an oracle binary,
a build script, three deviation sections and a rule about a binary nobody was
allowed to rebuild — and nobody could state it in a sentence.

## The rule

**A node that CircuitPython also has must render the same bytes CircuitPython
renders, under the same conditions.** Same sample rate, same channel count,
same options, and the same compile-time configuration — if the CircuitPython
build we compare against has `CIRCUITPY_SYNTHIO_MAX_CHANNELS=14`, then the
MicroPython build and the CPython extension are built at 14 for the comparison
too. Differences in configuration are not findings; they are setup errors.

**A node that is ours alone has no such reference, so it is held to two things
instead:** that all three of our targets render it identically, and that its
behaviour meets stated numeric traits. Neither is a stored byte.

Nothing here is compared against a previous version of our own output.

## Why not our own past

Because it is not a standard, it is a memory of a decision. Three ways it fails,
all of them observed in this repository rather than imagined:

* **A stored digest can be re-blessed.** `--capture` moves both sides of the
  comparison at once, the gate goes green, and nothing was checked. That is
  audioif#27, and `verify_mixdown_knee.py`'s anti-launder tripwire exists
  because of it.
* **A stored digest can be green while the code is wrong.** On 2026-09-09 the
  MicroPython flanger overflowed `int32_t` in its wet interpolation on
  full-scale material and disagreed with the CPython twin on every setting
  tried. Every stored fixture in `flanger_probe.py` matched to the byte
  throughout. Only comparing the two targets against each other found it.
* **A reference can outlive the thing it referenced.** The vstaudio oracle
  pinned `audiodynamics` and `audioroute` to micropython-vst3's
  `vstaudio_dsp.c` at revision `ac87f13`. That file was deleted from
  micropython-vst3 in `6ea60d3` — "Drop the effects library and the DSP that
  moved to audioif" — and the plug-in links audioif now. The relationship
  reversed: vstaudio is a consumer of this package, not a grader of it.

## Which nodes are which

The dividing line is not "did we write the C". It is whether **upstream
CircuitPython** ships the module. Both kinds are present in
`cmods/circuitpython`, and `git ls-files` tells them apart: ours are patched in
by `apply_cp_patches.sh` and are untracked there.

| CircuitPython's own — held to CP's bytes | Ours alone — no external reference |
|---|---|
| `audiocore` | `audiobiquad` |
| `audiodelays` | `audioconvolve` |
| `audiofilters` | `audiodynamics` |
| `audiofreeverb` | `audioecho` |
| `audiomixer` | `audioladder` |
| `audiomp3` | `audiomath` |
| `audiospeed` | `audioroute` |
| `synthio` | `audioshaper` |
| | `audioverb` |

Nine of the seventeen are ours, and they are most of the effects palette — which
is why "match CircuitPython" cannot be the only rule, and why the second half of
this page is not an afterthought.

Two of ours came from micropython-vst3's engine (`audiodynamics`, `audioroute`)
and the rest have no ancestor anywhere. Neither fact changes anything: what
matters is that no independent implementation exists to compare against today.

## What holds our own nodes up

**1. Three-target agreement, with nothing stored.** The CPython extension,
desktop MicroPython, and the patched CircuitPython build must render a probe
identically. All three compile the same kernel under `src/shared/`, so this is
a real check on the three compilations and on anything that is
architecture-dependent, undefined, or width-sensitive — the class of defect that
found the flanger overflow. It cannot be laundered, because there is no file to
re-capture.

**Its honest limit, stated so nobody relies on it for more than it gives:** a
change to the shared kernel moves all three together and stays green. Three-way
agreement sees divergence between targets. It cannot see drift over time. That
is what the next item is for.

**2. Numeric traits with planted faults.** A stated property with a bar —
"a 100 Hz low-pass attenuates 1 kHz by at least N dB", "a reset node renders
exact zero on silence from its first block", "the settled reduction at ratio R
is 20·(1−1/R) dB ± 0.01" — and beside it a deliberately broken build that must
fail the check. This is measuring against physics and arithmetic, which survive a
refactor and do not survive a regression. It is the effects program's own method
and it is the right one here.

A trait without a planted fault is not a check; it is a hope. See
`docs/program-pattern.md` §4 in the anchor, and `tests/parity/deinit_surface_probe.py`
for the shape — its `--fault` mode is run by CI first, and CI fails if the fault
*passes*.

## What this retires

Agreed 2026-09-09; the removals follow this page rather than precede it, so
until each line below is struck the old machinery is still present. This list
is the checklist, not a report.


* ~~**The vstaudio oracle**~~ — **done.** `tests/parity/vstaudio_oracle/`,
  `tests/parity/build_vstaudio_oracle.sh` and the pinned `VSTAUDIO_REV` are
  deleted, along with `golden/dsp_nodes.json`. `verify_dsp.py` is now the
  comparison itself: it runs every probe on every interpreter given and requires
  the outputs to be byte-identical, with **no stored digest**, and it **refuses
  a run with fewer than two interpreters** rather than passing one that cannot
  fail. A probe that cannot be covered yet is `PENDING` against a named issue -
  visible and counted, neither silently skipped nor standing red. Proved able to
  fail: reverting the flanger's 64-bit widening and rebuilding gives
  `FAIL flanger_probe.py cpython and micropython differ at output byte 1160`.

  The gate moved workflow with its meaning. It needs two interpreters, so it
  runs in `clean-build.yml`, which builds one. `test-cpython.yml` and the
  release job keep what a single interpreter *can* say - that every probe runs -
  across four operating systems and five Pythons, which catches an import
  error or an arithmetic assumption that only holds on x86_64.
* **`cmods/bin/circuitpython` as an untouchable artefact** — *not yet done.* The
  rule that it must never be rebuilt existed because it was a reference of
  record for `audiodynamics` and `audioroute`. It is not one any more, and
  CircuitPython should be built at whatever configuration a comparison needs.
  What stands in the way is mechanical: the unix `coverage` variant hardcodes
  `-DCIRCUITPY_SYNTHIO_MAX_CHANNELS=14` into CFLAGS instead of taking the make
  variable, and `build_cp.sh` has no passthrough for extra make arguments. **The
  never-rebuild rule stays in force until that is done and the CP-shared gates
  are re-read against the new binary** — the binary is still the reference for
  every node CircuitPython does have.
* **The 14 → 64 voice-ceiling deviation** recorded in `docs/upstream-diff.md`
  earlier the same day — *not yet done*, and blocked on the same rebuild. It
  only exists because the two sides are built at different ceilings. Build them
  the same and there is no deviation to record; that section says so and stands
  until then.
* ~~**Stored digests as a reference of record**~~ — **done** for the DSP nodes:
  `golden/dsp_nodes.json` is deleted and `verify_dsp` compares interpreters
  against each other. The CP-shared gates (`verify_acceptance`,
  `verify_effects`, `verify_streaming`, `verify_biquad`, `verify_mixdown_knee`)
  still carry stored files, and those are a different case: they hold this port
  to *CircuitPython's* answer, which is the rule, not to our own past. Probes
  stay — they are how a
  render is made reproducible and comparable. What goes is treating the stored
  value as the thing that must be matched, rather than as a convenience for
  running the comparison.

`docs/upstream-diff.md` does **not** retire. Deliberate departures from
CircuitPython in nodes CircuitPython has are exactly what it is for, and under
this rule each one is a decision that must be written there or it is a bug.

## What a divergence means now

* **CP-shared node, we differ from CircuitPython.** Either a bug of ours, or a
  bug of theirs worth an upstream report (`docs/upstream-reports/`), or a
  deliberate departure that goes in `docs/upstream-diff.md`. Three outcomes, and
  choosing between them is the work. What it is never is "re-record ours".
* **Our own node, the three targets disagree.** Ours, always. One of the three
  compilations is wrong, or the kernel relies on something undefined.
* **Our own node, a trait fails.** Ours, and the trait is the specification —
  unless the trait was wrong, in which case say so, change it, and say why.

## The one thing this page does not cover

Nothing establishes that a node of ours *sounds right*, or that its algorithm is
the one intended. Three-target agreement proves consistency, traits prove stated
properties. Neither proves a design. That comes from a dossier, a reference
recording, or Brad's ear, and it belongs to the effects program's gates rather
than to this page.
