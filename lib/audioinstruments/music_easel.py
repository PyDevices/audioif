"""Buchla Music Easel."""

MACRO_LABELS = (
    "Volume", "Timbre Wavefold", "FM Index", "Mod Osc Freq", "LPG Strike",
    "LPG Decay", "Amp Attack", "Amp Sustain", "Amp Release", "Master Tune",
)

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ('Init', (102, 64, 64, 64, 102, 29, 1, 102, 16, 64)),
}

import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, FALL, key_of,
    make_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

# Complex wave approximation
WAVE_COMPLEX = make_table(((1, 1.0), (2, 0.4), (3, 0.8), (4, 0.2)), fast=False)
SINE = make_table(((1, 1.0),), fast=False)


def create(sample_rate, transport=None):
    SR = sample_rate
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=2)

    # Macros
    volume = 0.8
    timbre = 0.5
    fm_idx = 0.5
    mod_freq = 0.5
    lpg_strike = 0.8
    lpg_decay = 0.5
    amp_a = 0.01
    amp_s = 0.8
    amp_r = 0.5
    master_tune = 1.0

    voices = {}
    serial = 0
    MAX_VOICES = 1


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, timbre, fm_idx, mod_freq, lpg_strike, lpg_decay
        nonlocal amp_a, amp_s, amp_r, master_tune
        nonlocal serial

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            if len(voices) >= MAX_VOICES:
                steal_oldest()

            hz = synthio.midi_to_hz(data0 + value1) * master_tune
            amp = volume * value0

            # A vactrol-driven LPG ties amplitude and filter cutoff to one envelope; more
            # Strike means a harder snap (shorter decay, more percussive, brighter jolt),
            # scaled continuously rather than as an on/off switch.
            actual_decay = 0.05 + lpg_decay * (1.0 - 0.7 * lpg_strike)
            sustain_level = amp_s * (1.0 - lpg_strike)

            env = synthio.Envelope(attack_time=amp_a, decay_time=actual_decay, release_time=amp_r, attack_level=1.0, sustain_level=sustain_level)

            strike_depth = 2000.0 + lpg_strike * 9000.0
            f_sweep = synthio.LFO(waveform=FALL, once=True, rate=1.0/actual_decay, scale=strike_depth, interpolate=True)
            cutoff = synthio.Math(synthio.MathOperation.SUM, 200.0, f_sweep, 0.0)

            lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, cutoff, Q=0.5) # LPG has very low Q

            # FM emulation via vibrato on pitch
            fm_lfo = synthio.LFO(waveform=SINE, rate=1.0 + mod_freq * 1000.0, scale=fm_idx * 0.1) if fm_idx > 0.01 else None

            # We blend a sine with the complex wave depending on timbre
            n1 = synthio.Note(hz, waveform=SINE, envelope=env, filter=lp, amplitude=amp * (1.0 - timbre), bend=fm_lfo)
            n2 = synthio.Note(hz, waveform=WAVE_COMPLEX, envelope=env, filter=lp, amplitude=amp * timbre, bend=fm_lfo)

            serial += 1
            voices[k] = ((n1, n2), serial)
            synth.press(n1)
            synth.press(n2)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: timbre = value0
            elif data0 == 2: fm_idx = value0
            elif data0 == 3: mod_freq = value0
            elif data0 == 4: lpg_strike = value0
            elif data0 == 5: lpg_decay = 0.05 + value0 * 2.0
            elif data0 == 6: amp_a = 0.001 + value0 * 2.0
            elif data0 == 7: amp_s = value0
            elif data0 == 8: amp_r = 0.01 + value0 * 4.0
            elif data0 == 9: master_tune = 0.95 + value0 * 0.1

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    instrument.program_change(0)
    return instrument
