# Draft reply to relic-se on PR #11289

**POSTED 2026-09-04** as https://github.com/adafruit/circuitpython/pull/11289#issuecomment-5540511752 (the text below the `---`, verbatim).

**Post only what is below the `---`.** Measured 2026-09-04 on the workspace's
CircuitPython unix build; the script is in the session scratchpad as
`sustain0.py`. Keep it short — dhalbert's standing feedback on our first five
issues was that a wall of text costs them a long time to read.

The substance, in one line: their direction is right, their patch as written
regresses `sustain_level=0` envelopes, and one extra branch keeps both.

Ordering that makes this true, checked in `shared-module/synthio/__init__.c`:
the `level == 0` reap is at :332, inside the per-channel render loop, and the
"advance envelope states" loop is at :365. The reap therefore runs *before* the
step in the same `synthio_synth_synthesize()` call, so their change only fixes
the re-press if that reap is removed — and removing it is exactly what strands
sustain-zero notes.

---

Agreed on the direction — `level == 0` is the ambiguity that causes this, and
reporting completion from the step is the right place to resolve it.

One catch. It only fixes the re-press if the `level == 0` reap in
`synthio_synth_synthesize` goes away (it runs before the envelope advance, so
otherwise it still claims the channel first). And that reap is doing real work
for envelopes with `sustain_level = 0`: they decay to silence and are never
released, so with completion reported only from RELEASE they would hold their
channel until an explicit note-off that percussion never sends.

Measured on a unix build, drum-shaped envelope (attack 1 ms, decay 20 ms,
`sustain_level=0`), pressing until refused:

```
channels filled: 14
still pressed after decay: 0
a further press after decay is accepted: True
```

With the patch as written those 14 stay pressed, and on a 14-channel build a
percussion kit runs out of voices.

So: return false whenever the level reaches 0 and cannot rise again without a
new press — the decay branch landing on a `sustain_level` of 0 as well as the
release branch.

```c
case SYNTHIO_ENVELOPE_STATE_DECAY:
    state->level = MAX(state->level + def->decay_step, def->sustain_level);
    if (state->level == def->sustain_level) {
        if (state->level == 0) {
            return false;
        }
        state->state = SYNTHIO_ENVELOPE_STATE_SUSTAIN;
    }
    break;
```

Then the ambiguous check can go and both cases are handled at the
source rather than worked around.

Happy to redo the PR that way if you prefer it to the current fix.
