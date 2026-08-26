"""Waldorf Microwave."""

MACRO_LABELS = (
    "Volume", "Wavetable Pos", "Cutoff", "Resonance", "Env to WT",
    "Env to Filter", "Filter Attack", "Amp Attack", "Amp Decay",
    "Amp Sustain", "Amp Release", "Master Tune",
)

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ('Init', (102, 0, 102, 18, 127, 64, 1, 1, 19, 102, 16, 64)),
}

import array
import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, env_shape_table, key_of,
    make_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

# Aggressive digital waves
WAVE_1 = make_table(((1, 1.0), (4, 0.8), (8, 0.4)), fast=False)
WAVE_2 = make_table(((1, 1.0), (3, 0.7), (5, 0.9), (7, 0.2)), fast=False)


def create(sample_rate, transport=None):
    SR = sample_rate
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=2)

    # Macros
    volume = 0.8
    wt_pos = 0.0
    cutoff_val = 2000.0
    res = 1.0
    env_wt = 1.0
    env_flt = 4000.0
    f_a = 0.01
    amp_a = 0.01
    amp_d = 0.5
    amp_s = 0.8
    amp_r = 0.5
    master_tune = 1.0

    voices = {}
    serial = 0
    MAX_VOICES = 8


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, wt_pos, cutoff_val, res, env_wt, env_flt
        nonlocal f_a, amp_a, amp_d, amp_s, amp_r, master_tune
        nonlocal serial

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            release_voice(k)
            if len(voices) >= MAX_VOICES:
                steal_oldest()

            hz = synthio.midi_to_hz(data0 + value1) * master_tune
            amp = volume * value0

            env = synthio.Envelope(attack_time=amp_a, decay_time=amp_d, release_time=amp_r, attack_level=1.0, sustain_level=amp_s)

            # Envelope modulates cutoff
            env_tbl = env_shape_table(f_a, amp_d, 0.0)
            f_sweep = synthio.LFO(waveform=env_tbl, once=True, rate=1.0/max(0.01, f_a + amp_d), scale=env_flt, interpolate=True)
            cutoff = synthio.Math(synthio.MathOperation.SUM, cutoff_val, f_sweep, 0.0)
            lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, cutoff, Q=res)

            # Env to Wavetable: the mix position sweeps from wt_pos to mix_end
            # over the amp decay time, driven by a live Math crossfade (Note
            # amplitude accepts a BlockInput, so this actually animates).
            mix_end = min(1.0, max(0.0, wt_pos + env_wt))

            ramp = synthio.LFO(waveform=array.array("h", (0, 32767)), once=True,
                                rate=1.0 / max(0.01, amp_d), interpolate=True)
            mix_pos = synthio.Math(synthio.MathOperation.LERP, wt_pos, mix_end, ramp)
            inv_pos = synthio.Math(synthio.MathOperation.ADD_SUB, 1.0, 0.0, mix_pos)
            amp1 = synthio.Math(synthio.MathOperation.PRODUCT, inv_pos, amp * 0.7, 1.0)
            amp2 = synthio.Math(synthio.MathOperation.PRODUCT, mix_pos, amp * 0.7, 1.0)

            notes = [
                synthio.Note(hz, waveform=WAVE_1, envelope=env, filter=lp, amplitude=amp1),
                synthio.Note(hz, waveform=WAVE_2, envelope=env, filter=lp, amplitude=amp2),
            ]

            serial += 1
            voices[k] = (tuple(notes), serial)
            for n in notes:
                synth.press(n)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: wt_pos = value0
            elif data0 == 2: cutoff_val = 50.0 * (100.0 ** value0)
            elif data0 == 3: res = 0.5 + value0 * 3.5
            elif data0 == 4: env_wt = -1.0 + value0 * 2.0
            elif data0 == 5: env_flt = value0 * 8000.0
            elif data0 == 6: f_a = 0.001 + value0 * 2.0
            elif data0 == 7: amp_a = 0.001 + value0 * 2.0
            elif data0 == 8: amp_d = 0.05 + value0 * 3.0
            elif data0 == 9: amp_s = value0
            elif data0 == 10: amp_r = 0.01 + value0 * 4.0
            elif data0 == 11: master_tune = 0.95 + value0 * 0.1

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    instrument.program_change(0)
    return instrument
