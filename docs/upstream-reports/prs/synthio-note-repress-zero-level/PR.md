# PR for adafruit/circuitpython

No existing upstream issue -- this defect wasn't among the five filed
2026-08-28 (#11265-#11269). Following tannewt's stated preference for
small fixes ("please open a PR instead of an issue... we can just merge
it"), this goes straight to a PR with no issue to link.

Branch: `fix-note-repress-envelope-zero` (one commit; the patch file
beside this document). Verified against upstream `main` at `801d77a3`
on 2026-09-02.

## Title

```
Fix synthio dropping a note re-pressed after its envelope hit 0
```

## Body

```markdown
A note that's re-pressed while it's still sitting on its channel, but
has already decayed to 0 (note-off immediately followed by note-on on
the same voice), gets silently dropped instead of re-attacking.

`synthio_span_change_note()`'s fast path for "note already on this
channel" re-enters `ATTACK` without touching `level`. That's right for
a note that's still sounding -- it swells back up from where it is.
But if `level` is already 0, the render loop's own `level == 0` check
(its "note is truly finished" test) reaps the channel before the
envelope is ever stepped, so the re-press never sounds. Press two
notes, release both, re-press both: `len(synth.pressed)` goes
`2 -> 0 -> 1`, not back to `2`.

Fix: when the fast path finds a note at level 0, run it through the
same envelope init a fresh press already uses, instead of only setting
the state.

Includes a regression test
(`tests/circuitpython/synthio_note_repress_after_decay.py`) with that
exact scenario; it fails on current `main` and passes with the fix.
```

## Why it matters (not for the PR body -- context for us)

An instrument that models one strike as a couple of notes sharing a
trigger (body + click, say) presses more than one note per hit. A
note-off followed by a fast re-strike lands in this window often enough
to be audible as a missing layer on the repeat, not just a synthetic
corner case.

## Verification transcript (2026-09-02, upstream main 801d77a3)

### The bug, still present on current main

```
$ grep -n "level == 0\|truly finished\|synthio_span_change_note\|re-enter attack\|synthio_envelope_state_init\b" shared-module/synthio/__init__.c
128:static void synthio_envelope_state_init(synthio_envelope_state_t *state, synthio_envelope_definition_t *def) {
369:        if (synth->envelope_state[chan].level == 0) {
370:            // note is truly finished, but we only just noticed
497:bool synthio_span_change_note(synthio_synth_t *synth, mp_obj_t old_note, mp_obj_t new_note) {
500:        // note already playing, re-enter attack phase
510:            synthio_envelope_state_init(&synth->envelope_state[channel], synthio_synth_get_note_envelope(synth, new_note));
```

The fast path at line 497-503 (unfixed):

```c
bool synthio_span_change_note(synthio_synth_t *synth, mp_obj_t old_note, mp_obj_t new_note) {
    int channel;
    if (new_note != SYNTHIO_SILENCE && (channel = find_channel_with_note(synth, new_note)) != -1) {
        // note already playing, re-enter attack phase
        synth->envelope_state[channel].state = SYNTHIO_ENVELOPE_STATE_ATTACK;
        return true;
    }
```

`synthio_envelope_state_init()` (line 128-134) is what a press on an
already-reclaimed slot uses; it steps the envelope once, synchronously,
before the render loop ever looks -- which is why a normal first press
never trips the reaper. The re-press fast path above skips that.

### `synth.pressed` before the fix (unmodified main, unix coverage build)

```
$ ports/unix/build-coverage/micropython repro.py
after press: 2
click level right after release: 0.0 state: synthio.EnvelopeState.RELEASE
after release: 0
pressed right after re-press call: 2
after one more render: 1 [110.0]
```

(`repro.py`: two notes, 110 Hz with a 1 s release and 2000 Hz with a 0 s
release; press both, release both, re-press both. The 2000 Hz "click"
note is dropped -- `pressed` is 1, and only the 110 Hz note answers.)

### After the fix (same build, same script)

```
after press: 2
click level right after release: 0.0 state: synthio.EnvelopeState.RELEASE
after release: 0
pressed right after re-press call: 2
after one more render: 2 [110.0, 2000.0]
```

### The re-press now matches a genuine fresh press, step for step

`repro2.py` compares the envelope trajectory (state, level) over four
renders for (a) a brand-new `Note` pressed for the first time and
(b) the same shape of note released to level 0 and re-pressed, with the
fix applied:

```
pre-repress state/level: synthio.EnvelopeState.RELEASE 0.0
fresh press trajectory:   [('ATTACK', 0.2133), ('ATTACK', 0.32), ('ATTACK', 0.4266), ('ATTACK', 0.5333)]
re-press trajectory:      [('ATTACK', 0.2133), ('ATTACK', 0.32), ('ATTACK', 0.4266), ('ATTACK', 0.5333)]
match: True
```

### Regression test round-trip

```
$ MICROPY_MICROPYTHON=../ports/unix/build-coverage/micropython ./run-tests.py circuitpython/synthio_note_repress_after_decay.py
pass  circuitpython/synthio_note_repress_after_decay.py   (fixed binary)
```

Stashing the fix and rebuilding reproduces the unfixed `.exp` mismatch
(`pressed after one more render: 0`, `None 0.00` x3) -- fails on
unmodified `main`, passes with the fix.

Ran alongside its neighbors, same build:
`synthio_note_info.py`, `synthio_oscillator_loop_end.py`,
`audiofilter_filter_reset_buffer.py`, `synthio_biquad_peaking.py` all
still pass. `synthio_biquad.py` fails identically on unmodified `main`
in this WSL environment (full-precision float prints vs. the
checked-in `.exp`, unrelated to this change -- confirmed by stashing
the fix and re-running: same failure, same build).

### The alternative we tried and rejected: gating the reaper instead

Our first instinct was to leave the fast path alone and instead skip
reaping a level-0 note while its state is `ATTACK` (i.e. gate the
`level == 0` check in the render loop on `state != ATTACK`, rather than
fixing the press path). Implemented as a one-line experiment
(`synth->envelope_state[chan].level == 0 && ...state != SYNTHIO_ENVELOPE_STATE_ATTACK`)
and measured with the same `repro2.py` trajectory comparison:

```
pre-repress state/level: synthio.EnvelopeState.RELEASE 0.0
fresh press trajectory:   [('ATTACK', 0.2133), ('ATTACK', 0.32), ('ATTACK', 0.4266), ('ATTACK', 0.5333)]
re-press trajectory:      [('ATTACK', 0.1067), ('ATTACK', 0.2133), ('ATTACK', 0.32), ('ATTACK', 0.4266)]
match: False
```

It never resets `level`/`substep` the way `synthio_envelope_state_init()`
does, so it's missing the synchronous first step every other press gets
-- the re-pressed note comes in a full envelope step behind a fresh
press, permanently, for as long as it's held. Rejected; not part of
this patch, and not part of the PR body (only mentioned here in case a
reviewer suggests the same shortcut).

### Pre-commit

`pre-commit run --files shared-module/synthio/__init__.c
tests/circuitpython/synthio_note_repress_after_decay.py
tests/circuitpython/synthio_note_repress_after_decay.py.exp`:
end-of-file, trailing-whitespace, codespell, ruff, ruff-format all
passed. `Translations` fails in this environment for unrelated reasons
(`xgettext` and `polib` aren't installed) -- it emptied
`locale/circuitpython.pot`, reverted, not part of the commit.
`Formatting` (uncrustify 0.78.1, built from source, run against
upstream's `tools/uncrustify.cfg` which triggers several
deprecated-option warnings on this uncrustify version) ran clean on the
touched lines but also collapsed a space in an unrelated line 60 lines
away (`time * sample_rate` -> `time *sample_rate`); hand-reverted, not
part of the commit -- same tool quirk noted in earlier runs, always
diff after this hook.

### Build

`git clone --depth 50`, `python3 tools/ci_fetch_deps.py tests`,
`make -C mpy-cross -j8 && make -C ports/unix VARIANT=coverage -j8`.
Clean build both before and after the fix.

## Publish commands (Brad runs these; nothing has been pushed)

From a checkout with this branch (the scratch clone lives at
`/tmp/claude-1000/-home-brad-gh-pydevices/1139bed2-49e9-471e-8f3f-9ff13eab29f0/scratchpad/upstream/circuitpython`,
but a scratch dir may be gone -- `git am` the patch onto fresh `main`
instead):

```sh
git clone https://github.com/adafruit/circuitpython.git
cd circuitpython
git checkout -b fix-note-repress-envelope-zero
git am /path/to/audioif/docs/upstream-reports/prs/synthio-note-repress-zero-level/0001-Fix-synthio-dropping-a-note-re-pressed-after-its-env.patch

gh repo fork adafruit/circuitpython --remote --remote-name fork
git push fork fix-note-repress-envelope-zero
gh pr create --repo adafruit/circuitpython \
  --title "Fix synthio dropping a note re-pressed after its envelope hit 0" \
  --body-file <body extracted from the Body section above>
```

No issue exists to link with `Fixes #nnnn`. If Brad would rather file a
short issue first (house pattern: "a two-sentence issue plus the PR"),
two sentences that would do it:

> Pressing a note that's still on its channel but has already decayed
> to envelope level 0 is silently dropped instead of re-attacking --
> `synthio_span_change_note()`'s fast path re-enters ATTACK without
> resetting `level`, and the render loop reaps anything at level 0
> before stepping it. PR to follow.
