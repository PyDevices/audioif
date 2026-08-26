"""Roland JP-8000."""

MACRO_LABELS = (
    "Volume", "Cutoff", "Resonance", "Supersaw Detune", "Supersaw Mix",
    "Env Depth", "Chorus", "Amp Attack", "Amp Decay", "Amp Sustain",
    "Amp Release", "Filter Attack", "Filter Decay", "Filter Sustain",
    "HPF Cutoff", "Master Tune",
)

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ('Init', (102, 108, 18, 42, 102, 64, 0, 1, 11, 64, 9, 1, 11, 64, 0,
                 64)),
}

import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, env_shape_table, key_of,
    make_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

SAW = make_table([(n, 1.0 / n) for n in range(1, 40)])


def create(sample_rate, transport=None):
    SR = sample_rate
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=2)

    # Macros
    volume = 0.8
    cutoff_base = 2500.0
    resonance = 1.0
    supersaw_detune = 0.2
    supersaw_mix = 0.8
    env_depth = 4000.0
    chorus = 0.0

    a_a = 0.01
    a_d = 0.3
    a_s = 0.5
    a_r = 0.3
    f_a = 0.01
    f_d = 0.3
    f_s = 0.5
    hpf = 20.0
    master_tune = 1.0

    voices = {}
    serial = 0
    MAX_VOICES = 8


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, cutoff_base, resonance, supersaw_detune, supersaw_mix, env_depth, chorus
        nonlocal a_a, a_d, a_s, a_r, f_a, f_d, f_s, hpf, master_tune
        nonlocal serial

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            release_voice(k)
            if len(voices) >= MAX_VOICES:
                steal_oldest()

            hz = synthio.midi_to_hz(data0 + value1) * master_tune
            amp = volume * value0

            env = synthio.Envelope(attack_time=a_a, decay_time=a_d, release_time=a_r, attack_level=1.0, sustain_level=a_s)

            env_tbl = env_shape_table(f_a, f_d, f_s)
            f_sweep = synthio.LFO(waveform=env_tbl, once=True, rate=1.0/max(0.01, f_a + f_d), scale=env_depth, interpolate=True)
            cutoff = synthio.Math(synthio.MathOperation.SUM, cutoff_base, f_sweep, 0.0)

            lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, cutoff, Q=resonance)
            # The JP-8000's HPF sits before the resonant VCF in series; synthio only allows one
            # filter per Note, so approximate it by high-passing the two outermost detuned saws
            # (thinning their low end as cutoff rises) while the rest keep the full swept VCF.
            hp = synthio.Biquad(synthio.FilterMode.HIGH_PASS, hpf, Q=0.7)

            notes = []

            # 7-Saw Supersaw
            # 1 center, 3 detuned up, 3 detuned down
            detunes = [
                0.0,
                supersaw_detune * 0.02,
                -supersaw_detune * 0.02,
                supersaw_detune * 0.04,
                -supersaw_detune * 0.04,
                supersaw_detune * 0.06,
                -supersaw_detune * 0.06
            ]
            pans = [0.0, 0.3, -0.3, 0.6, -0.6, 0.9, -0.9]

            base_a = amp * (1.0 / 7.0) * supersaw_mix * 2.0

            for i in range(7):
                d = detunes[i]
                p = pans[i] * (0.5 + chorus * 0.5)
                note_filter = hp if i >= 5 else lp
                n = synthio.Note(hz * (1.0 + d), waveform=SAW, envelope=env, filter=note_filter, amplitude=base_a, panning=p)
                notes.append(n)

            serial += 1
            voices[k] = (tuple(notes), serial)
            for n in notes:
                synth.press(n)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: cutoff_base = 50.0 * (100.0 ** value0)
            elif data0 == 2: resonance = 0.5 + value0 * 3.5
            elif data0 == 3: supersaw_detune = value0 * 0.6
            elif data0 == 4: supersaw_mix = value0
            elif data0 == 5: env_depth = value0 * 8000.0
            elif data0 == 6: chorus = value0
            elif data0 == 7: a_a = 0.001 + value0 * 2.0
            elif data0 == 8: a_d = 0.05 + value0 * 3.0
            elif data0 == 9: a_s = value0
            elif data0 == 10: a_r = 0.01 + value0 * 4.0
            elif data0 == 11: f_a = 0.001 + value0 * 2.0
            elif data0 == 12: f_d = 0.05 + value0 * 3.0
            elif data0 == 13: f_s = value0
            elif data0 == 14: hpf = 20.0 + value0 * 1000.0
            elif data0 == 15: master_tune = 0.95 + value0 * 0.1

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    instrument.program_change(0)
    return instrument
