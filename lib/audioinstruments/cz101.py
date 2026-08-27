"""Casio CZ-101 phase distortion synthesizer."""

NAME = 'CZ-101'
CATEGORIES = ('Synth',)
VERSION = '0.0.1'
VENDOR = "PyDevices"

MACRO_LABELS = (
    "Volume", "PD Env Depth", "PD Attack", "PD Decay", "Resonance (Fake)",
    "Vibrato Rate", "Vibrato Depth", "Amp Attack", "Amp Decay",
    "Amp Sustain", "Amp Release", "Master Tune",
)

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ('Init', (102, 64, 6, 29, 18, 62, 0, 1, 19, 64, 9, 64)),
}

import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, env_shape_table, key_of,
    make_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

# True phase distortion warps a sine read-pointer's speed rather than filtering a
# spectrum; synthio has no per-sample phase control, so we approximate the audible
# result (a harmonic-rich tone whose brightness sweeps like the DCW envelope) with
# a harmonic-rich sawtooth run through a swept resonant low-pass below.
WAVE_PD = make_table([(n, 1.0 / n) for n in range(1, 40)], fast=False)
SINE = make_table(((1, 1.0),), fast=False)


def create(sample_rate, transport=None):
    SR = sample_rate
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=2)

    # Macros
    volume = 0.8
    pd_depth = 4000.0
    pd_a = 0.05
    pd_d = 0.5
    res = 1.0
    vib_rate = 5.0
    vib_depth = 0.0
    amp_a = 0.01
    amp_d = 0.5
    amp_s = 0.5
    amp_r = 0.3
    master_tune = 1.0

    voices = {}
    serial = 0
    MAX_VOICES = 8


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, pd_depth, pd_a, pd_d, res, vib_rate, vib_depth
        nonlocal amp_a, amp_d, amp_s, amp_r, master_tune
        nonlocal serial

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            release_voice(k)
            if len(voices) >= MAX_VOICES:
                steal_oldest()

            hz = synthio.midi_to_hz(data0 + value1) * master_tune
            amp = volume * value0

            env = synthio.Envelope(attack_time=amp_a, decay_time=amp_d, release_time=amp_r, attack_level=1.0, sustain_level=amp_s)

            # DCW envelope modulates the "distortion" (cutoff of the rich wave) with a
            # one-shot attack->decay->0 shape, mirroring the CZ's DCW envelope stage.
            env_tbl = env_shape_table(pd_a, pd_d, 0.0)
            f_sweep = synthio.LFO(waveform=env_tbl, once=True, rate=1.0/max(0.01, pd_a + pd_d), scale=pd_depth, interpolate=True)

            lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, synthio.Math(synthio.MathOperation.SUM, 200.0, f_sweep, 0.0), Q=res)

            vib_lfo = synthio.LFO(waveform=SINE, rate=vib_rate, scale=vib_depth * 0.025) if vib_depth > 0.01 else None

            n = synthio.Note(hz, waveform=WAVE_PD, envelope=env, filter=lp, amplitude=amp * 0.8, bend=vib_lfo)

            serial += 1
            voices[k] = ((n,), serial)
            synth.press(n)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: pd_depth = value0 * 8000.0
            elif data0 == 2: pd_a = 0.001 + value0 * 1.0
            elif data0 == 3: pd_d = 0.05 + value0 * 2.0
            elif data0 == 4: res = 0.5 + value0 * 3.5
            elif data0 == 5: vib_rate = 0.1 + value0 * 10.0
            elif data0 == 6: vib_depth = value0
            elif data0 == 7: amp_a = 0.001 + value0 * 2.0
            elif data0 == 8: amp_d = 0.05 + value0 * 3.0
            elif data0 == 9: amp_s = value0
            elif data0 == 10: amp_r = 0.01 + value0 * 4.0
            elif data0 == 11: master_tune = 0.95 + value0 * 0.1

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    instrument.program_change(0)
    return instrument
