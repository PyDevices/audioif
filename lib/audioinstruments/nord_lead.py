"""Clavia Nord Lead."""

NAME = 'Nord Lead'
CATEGORIES = ('Synth',)
VERSION = '0.0.1'
VENDOR = "PyDevices"

MACRO_LABELS = (
    "Volume", "Cutoff", "Resonance", "FM Amount", "Osc Sync", "Morph 1",
    "Morph 2", "Morph 3", "Morph 4", "Amp Attack", "Amp Decay",
    "Amp Sustain", "Amp Release", "Filter Attack", "Filter Decay",
    "Filter Sustain",
)

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ('Init', (102, 113, 18, 0, 0, 0, 0, 0, 0, 1, 11, 64, 9, 1, 11, 64)),
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


def create(sample_rate, transport=None):
    SR = sample_rate
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=2)

    # Macros
    volume = 0.8
    cutoff_base = 3000.0
    resonance = 1.0
    fm_amount = 0.0
    osc_sync = 0.0
    morph1 = 0.0
    morph2 = 0.0
    morph3 = 0.0
    morph4 = 0.0
    amp_a = 0.01
    amp_d = 0.3
    amp_s = 0.5
    amp_r = 0.3
    filt_a = 0.01
    filt_d = 0.3
    filt_s = 0.5

    voices = {}
    serial = 0
    MAX_VOICES = 12


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, cutoff_base, resonance, fm_amount, osc_sync, morph1, morph2, morph3, morph4
        nonlocal amp_a, amp_d, amp_s, amp_r, filt_a, filt_d, filt_s
        nonlocal serial

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            release_voice(k)
            if len(voices) >= MAX_VOICES:
                steal_oldest()

            hz = synthio.midi_to_hz(data0 + value1)
            amp = volume * value0

            env = synthio.Envelope(attack_time=amp_a, decay_time=amp_d, release_time=amp_r, attack_level=1.0, sustain_level=amp_s)

            # Morph parameters dynamically alter the tone
            actual_cutoff = cutoff_base * (1.0 + morph1 * 2.0)
            actual_res = resonance * (1.0 + morph2)

            env_tbl = env_shape_table(filt_a, filt_d, filt_s)
            f_sweep = synthio.LFO(waveform=env_tbl, once=True, rate=1.0/max(0.01, filt_a + filt_d), scale=4000.0 * (1.0 + morph3), interpolate=True)
            cutoff = synthio.Math(synthio.MathOperation.SUM, actual_cutoff, f_sweep, 0.0)

            lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, cutoff, Q=actual_res)

            o1 = synthio.Note(hz, waveform=SAW, envelope=env, filter=lp, amplitude=amp * 0.5)
            # FM emulation via detune/amplitude, plus Osc Sync: true audio-rate hard sync isn't
            # achievable in synthio (no per-sample phase reset), so approximate its buzzy,
            # harmonically-locked character by snapping osc2 toward an integer multiple of osc1's
            # frequency as Osc Sync increases, and brightening its waveform to match.
            base_ratio = 1.0 + fm_amount * 2.0 + morph4
            if osc_sync > 0.01:
                ratio = round(base_ratio)
                if ratio < 1:
                    ratio = 1
                sync_ratio = base_ratio + (ratio - base_ratio) * osc_sync
                o2_wave = SAW
            else:
                sync_ratio = base_ratio
                o2_wave = SQUARE
            o2 = synthio.Note(hz * sync_ratio, waveform=o2_wave, envelope=env, filter=lp, amplitude=amp * 0.5 * (0.5 + fm_amount))

            serial += 1
            voices[k] = ((o1, o2), serial)
            synth.press(o1)
            synth.press(o2)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: cutoff_base = 50.0 * (100.0 ** value0)
            elif data0 == 2: resonance = 0.5 + value0 * 3.5
            elif data0 == 3: fm_amount = value0
            elif data0 == 4: osc_sync = value0
            elif data0 == 5: morph1 = value0
            elif data0 == 6: morph2 = value0
            elif data0 == 7: morph3 = value0
            elif data0 == 8: morph4 = value0
            elif data0 == 9: amp_a = 0.001 + value0 * 2.0
            elif data0 == 10: amp_d = 0.05 + value0 * 3.0
            elif data0 == 11: amp_s = value0
            elif data0 == 12: amp_r = 0.01 + value0 * 4.0
            elif data0 == 13: filt_a = 0.001 + value0 * 2.0
            elif data0 == 14: filt_d = 0.05 + value0 * 3.0
            elif data0 == 15: filt_s = value0

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    instrument.program_change(0)
    return instrument
