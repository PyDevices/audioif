"""Roland D-50 linear synthesizer."""

NAME = 'D-50'
CATEGORIES = ('Synth',)
VERSION = '0.0.1'
VENDOR = "PyDevices"

MACRO_LABELS = (
    "Volume", "Transient Mix", "Synth Mix", "Transient Tune", "Cutoff",
    "Resonance", "Chorus", "Amp Attack", "Amp Decay", "Amp Sustain",
    "Amp Release", "Master Tune",
)

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ('Init', (102, 102, 102, 16, 113, 18, 64, 1, 30, 102, 31, 64)),
}

import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, key_of, make_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

# D-50 Transient PCM approximation (inharmonic bell/chiff)
WAVE_TRANS = make_table(((1, 1.0), (3.14, 0.8), (5.5, 0.5), (9.2, 0.3)), fast=False)
# D-50 Synth body (PWM/Saw)
WAVE_SYNTH = make_table([(n, 1.0 / n) for n in range(1, 40)], fast=False)
SINE = make_table(((1, 1.0),), fast=False)


def create(sample_rate, transport=None):
    SR = sample_rate
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=2)

    # Macros
    volume = 0.8
    trans_mix = 0.8
    synth_mix = 0.8
    trans_tune = 1.0
    cutoff_val = 3000.0
    res = 1.0
    chorus = 0.5
    amp_a = 0.01
    amp_d = 1.0
    amp_s = 0.8
    amp_r = 1.0
    master_tune = 1.0

    voices = {}
    serial = 0
    MAX_VOICES = 8


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, trans_mix, synth_mix, trans_tune, cutoff_val, res, chorus
        nonlocal amp_a, amp_d, amp_s, amp_r, master_tune
        nonlocal serial

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            release_voice(k)
            if len(voices) >= MAX_VOICES:
                steal_oldest()

            hz = synthio.midi_to_hz(data0 + value1) * master_tune
            amp = volume * value0

            # Synth body envelope
            env_synth = synthio.Envelope(attack_time=amp_a, decay_time=amp_d, release_time=amp_r, attack_level=1.0, sustain_level=amp_s)
            # Transient envelope (very fast decay)
            env_trans = synthio.Envelope(attack_time=0.001, decay_time=0.1, release_time=0.05, attack_level=1.0, sustain_level=0.0)

            lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, cutoff_val, Q=res)

            notes = []
            if trans_mix > 0.01:
                notes.append(synthio.Note(hz * trans_tune, waveform=WAVE_TRANS, envelope=env_trans, filter=lp, amplitude=amp * trans_mix * 0.7))

            if synth_mix > 0.01:
                if chorus > 0.01:
                    # Built in chorus typical of LA synthesis
                    notes.append(synthio.Note(hz, waveform=WAVE_SYNTH, envelope=env_synth, filter=lp, amplitude=amp * synth_mix * 0.4, panning=-0.4))
                    notes.append(synthio.Note(hz * 1.003, waveform=WAVE_SYNTH, envelope=env_synth, filter=lp, amplitude=amp * synth_mix * 0.4, panning=0.4))
                else:
                    notes.append(synthio.Note(hz, waveform=WAVE_SYNTH, envelope=env_synth, filter=lp, amplitude=amp * synth_mix * 0.7))

            serial += 1
            voices[k] = (tuple(notes), serial)
            for n in notes:
                synth.press(n)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: trans_mix = value0
            elif data0 == 2: synth_mix = value0
            elif data0 == 3: trans_tune = 0.5 + value0 * 4.0
            elif data0 == 4: cutoff_val = 50.0 * (100.0 ** value0)
            elif data0 == 5: res = 0.5 + value0 * 3.5
            elif data0 == 6: chorus = value0
            elif data0 == 7: amp_a = 0.001 + value0 * 2.0
            elif data0 == 8: amp_d = 0.05 + value0 * 4.0
            elif data0 == 9: amp_s = value0
            elif data0 == 10: amp_r = 0.01 + value0 * 4.0
            elif data0 == 11: master_tune = 0.95 + value0 * 0.1

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    instrument.program_change(0)
    return instrument
