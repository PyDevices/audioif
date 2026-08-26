"""ARP 2600."""

MACRO_LABELS = (
    "Volume", "VCF Cutoff", "Resonance", "FM Amount", "Reverb Mix",
    "Osc 2 Detune", "Osc 3 Detune", "Env 1 Attack", "Env 1 Release",
    "Env 2 Attack", "Env 2 Decay", "Env 2 Sustain", "Env 2 Release",
    "VCA Attack", "VCA Release", "Master Tune",
)

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ('Init', (102, 102, 18, 0, 0, 64, 32, 1, 16, 1, 11, 64, 9, 1, 9, 64)),
}

import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, env_shape_table, key_of,
    make_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

SAW = make_table([(n, 1.0 / n) for n in range(1, 40)])
SQUARE = make_table([(n, 1.0 / n) for n in range(1, 40, 2)])
TRIANGLE = make_table([(n, (1.0 / (n*n)) * (-1)**((n-1)//2)) for n in range(1, 11, 2)])


def create(sample_rate, transport=None):
    SR = sample_rate
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=2)

    # Macros
    volume = 0.8
    cutoff_base = 2000.0
    resonance = 1.0
    fm_amt = 0.0
    reverb_mix = 0.0
    osc2_detune = 1.0
    osc3_detune = 0.5

    e1_a = 0.01
    e1_r = 0.5
    e2_a = 0.01
    e2_d = 0.3
    e2_s = 0.5
    e2_r = 0.3
    vca_a = 0.01
    vca_r = 0.3
    master_tune = 1.0

    voices = {}
    serial = 0
    MAX_VOICES = 1


    def release_voice(k):
        voice = _support.release_voice(voices, synth, k)
        if voice is not None and voice[2] is not None:
            rel_filter = _support.release_filter(voice[2])
            for note in voice[3]:
                note.filter = rel_filter

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, cutoff_base, resonance, fm_amt, reverb_mix, osc2_detune, osc3_detune
        nonlocal e1_a, e1_r, e2_a, e2_d, e2_s, e2_r, vca_a, vca_r, master_tune
        nonlocal serial

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            if len(voices) >= MAX_VOICES:
                steal_oldest()

            hz = synthio.midi_to_hz(data0 + value1) * master_tune
            amp = volume * value0

            env = synthio.Envelope(attack_time=vca_a, decay_time=e2_d, release_time=vca_r, attack_level=1.0, sustain_level=1.0)

            env_tbl = env_shape_table(e2_a, e2_d, e2_s)
            f_sweep = synthio.LFO(waveform=env_tbl, once=True, rate=1.0/max(0.01, e2_a + e2_d), scale=4000.0, interpolate=True)
            cutoff = synthio.Math(synthio.MathOperation.SUM, cutoff_base, f_sweep, 0.0)

            lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, cutoff, Q=resonance)

            o1 = synthio.Note(hz, waveform=SAW, envelope=env, filter=lp, amplitude=amp * 0.4)
            o2 = synthio.Note(hz * osc2_detune, waveform=SQUARE, envelope=env, filter=lp, amplitude=amp * 0.3)
            # Env 1 (Attack/Release) patched to osc3's pitch input, scaled by FM Amount: the ARP
            # 2600 is semi-modular, and "envelope -> VCO frequency" is one of its classic patches
            # (laser/zap sounds). synthio can't do audio-rate FM, so approximate it as a one-shot
            # pitch-bend sweep shaped by Env 1.
            fm_tbl = env_shape_table(e1_a, e1_r, 0.0)
            fm_lfo = synthio.LFO(waveform=fm_tbl, once=True, rate=1.0/max(0.01, e1_a + e1_r), scale=fm_amt * 2.0, interpolate=True) if fm_amt > 0.01 else None
            o3 = synthio.Note(hz * osc3_detune, waveform=TRIANGLE, envelope=env, filter=lp, amplitude=amp * 0.3, bend=fm_lfo)

            filtered_notes = [o1, o2, o3]
            notes = list(filtered_notes)

            # Reverb Mix: the 2600 itself is dry; approximate a reverb-style tail with a quietly
            # mixed, softly filtered, longer-release copy of the voice rather than true convolution.
            if reverb_mix > 0.01:
                wash_env = synthio.Envelope(attack_time=vca_a, decay_time=e2_d, release_time=vca_r + reverb_mix * 2.0, attack_level=1.0, sustain_level=1.0)
                wash_filt = synthio.Biquad(synthio.FilterMode.LOW_PASS, cutoff_base * 0.4, Q=0.7)
                wash = synthio.Note(hz * 1.003, waveform=TRIANGLE, envelope=wash_env, filter=wash_filt, amplitude=amp * reverb_mix * 0.25, panning=0.6)
                notes.append(wash)

            # Env 2 Release: retarget o1/o2/o3's shared filter to a real release
            # sweep at note-off (Note.filter is mutable post-construction), since
            # the one-shot attack/decay LFO above can't represent an indefinite
            # sustain hold followed by a release triggered by an unknown-in-
            # advance note-off time.
            filt_release = (cutoff_base, 4000.0 * e2_s, e2_r, resonance)

            serial += 1
            voices[k] = (tuple(notes), serial, filt_release, tuple(filtered_notes))
            for n in notes:
                synth.press(n)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: cutoff_base = 50.0 * (100.0 ** value0)
            elif data0 == 2: resonance = 0.5 + value0 * 3.5
            elif data0 == 3: fm_amt = value0
            elif data0 == 4: reverb_mix = value0
            elif data0 == 5: osc2_detune = 0.5 + value0
            elif data0 == 6: osc3_detune = 0.25 + value0
            elif data0 == 7: e1_a = 0.001 + value0 * 2.0
            elif data0 == 8: e1_r = 0.01 + value0 * 4.0
            elif data0 == 9: e2_a = 0.001 + value0 * 2.0
            elif data0 == 10: e2_d = 0.05 + value0 * 3.0
            elif data0 == 11: e2_s = value0
            elif data0 == 12: e2_r = 0.01 + value0 * 4.0
            elif data0 == 13: vca_a = 0.001 + value0 * 2.0
            elif data0 == 14: vca_r = 0.01 + value0 * 4.0
            elif data0 == 15: master_tune = 0.95 + value0 * 0.1

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    instrument.program_change(0)
    return instrument
