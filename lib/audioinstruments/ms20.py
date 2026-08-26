"""Korg MS-20."""

MACRO_LABELS = (
    "Volume", "HPF Cutoff", "HPF Peak", "LPF Cutoff", "LPF Peak",
    "Osc2 Pitch", "EG2 Sweep", "EG2 Attack", "EG2 Decay", "EG2 Sustain",
    "EG2 Release", "Ring Mod", "Noise Level", "VCA Attack", "VCA Release",
    "Master Tune",
)

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ('Init', (102, 44, 13, 102, 8, 64, 48, 1, 11, 64, 9, 0, 0, 1, 9, 64)),
}

import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, env_shape_table, key_of,
    make_table, noise_table, ring_depth_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

SAW = make_table([(n, 1.0 / n) for n in range(1, 40)])
SQUARE = make_table([(n, 1.0 / n) for n in range(1, 40, 2)])
NOISE = noise_table(seed=1234567)


def create(sample_rate, transport=None):
    SR = sample_rate
    NOISE_HZ = SR / 8192.0
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=2)

    # Macros
    volume = 0.8
    hpf_cutoff = 100.0
    hpf_peak = 1.0
    lpf_cutoff = 2000.0
    lpf_peak = 1.0
    osc2_pitch = 1.0
    eg2_sweep = 3000.0
    eg2_a = 0.01
    eg2_d = 0.3
    eg2_s = 0.5
    eg2_r = 0.3
    ring_mod = 0.0
    noise_lvl = 0.0
    vca_a = 0.01
    vca_r = 0.3
    master_tune = 1.0

    voices = {}
    serial = 0
    MAX_VOICES = 1
    last_pitch = None


    def release_voice(k):
        voice = _support.release_voice(voices, synth, k)
        if voice is not None and voice[2] is not None:
            rel_filter = _support.release_filter(voice[2])
            for note in voice[3]:
                note.filter = rel_filter

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, hpf_cutoff, hpf_peak, lpf_cutoff, lpf_peak, osc2_pitch, eg2_sweep
        nonlocal eg2_a, eg2_d, eg2_s, eg2_r, ring_mod, noise_lvl, vca_a, vca_r, master_tune
        nonlocal serial, last_pitch

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            if len(voices) >= MAX_VOICES:
                steal_oldest()

            hz = synthio.midi_to_hz(data0 + value1) * master_tune
            amp = volume * value0

            env = synthio.Envelope(attack_time=vca_a, decay_time=eg2_d, release_time=vca_r, attack_level=1.0, sustain_level=1.0)

            env_tbl = env_shape_table(eg2_a, eg2_d, eg2_s)
            f_sweep = synthio.LFO(waveform=env_tbl, once=True, rate=1.0/max(0.01, eg2_a + eg2_d), scale=eg2_sweep, interpolate=True)
            lpf_freq = synthio.Math(synthio.MathOperation.SUM, lpf_cutoff, f_sweep, 0.0)

            # The MS-20's iconic HPF -> LPF chain can't be built as a single
            # series filter per Note, so osc1 runs through the resonant LPF and
            # osc2 through the resonant HPF, mixed the way the real panel's two
            # filters would be blended.
            lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, lpf_freq, Q=lpf_peak)
            hp = synthio.Biquad(synthio.FilterMode.HIGH_PASS, hpf_cutoff, Q=hpf_peak)

            ring_wave = ring_depth_table(ring_mod) if ring_mod > 0.01 else None

            o1 = synthio.Note(hz, waveform=SAW, envelope=env, filter=lp, amplitude=amp * 0.5,
                               ring_frequency=hz, ring_waveform=ring_wave)
            o2 = synthio.Note(hz * osc2_pitch, waveform=SQUARE, envelope=env, filter=hp, amplitude=amp * 0.5,
                               ring_frequency=hz, ring_waveform=ring_wave)
            notes = [o1, o2]
            lp_notes = [o1]
            if noise_lvl > 0.01:
                noise_note = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=env, filter=lp,
                                          amplitude=amp * noise_lvl * 0.4)
                notes.append(noise_note)
                lp_notes.append(noise_note)

            # EG2 Release: retarget the LPF-routed notes to a real release sweep
            # at note-off (only the LPF gets the EG2 sweep, so only those notes
            # need it; the HPF stays fixed). Note.filter is mutable
            # post-construction, so this reassigns it rather than trying to
            # represent an indefinite sustain hold in the one-shot attack/decay
            # LFO above.
            filt_release = (lpf_cutoff, eg2_sweep * eg2_s, eg2_r, lpf_peak)

            serial += 1
            voices[k] = (tuple(notes), serial, filt_release, tuple(lp_notes))
            for n in notes:
                synth.press(n)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: hpf_cutoff = 20.0 * (100.0 ** value0)
            elif data0 == 2: hpf_peak = 0.5 + value0 * 5.0
            elif data0 == 3: lpf_cutoff = 50.0 * (100.0 ** value0)
            elif data0 == 4: lpf_peak = 0.5 + value0 * 8.0 # MS-20 is very resonant
            elif data0 == 5: osc2_pitch = 1.0 + (value0 - 0.5)
            elif data0 == 6: eg2_sweep = value0 * 8000.0
            elif data0 == 7: eg2_a = 0.001 + value0 * 2.0
            elif data0 == 8: eg2_d = 0.05 + value0 * 3.0
            elif data0 == 9: eg2_s = value0
            elif data0 == 10: eg2_r = 0.01 + value0 * 4.0
            elif data0 == 11: ring_mod = value0
            elif data0 == 12: noise_lvl = value0
            elif data0 == 13: vca_a = 0.001 + value0 * 2.0
            elif data0 == 14: vca_r = 0.01 + value0 * 4.0
            elif data0 == 15: master_tune = 0.95 + value0 * 0.1

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    instrument.program_change(0)
    return instrument
