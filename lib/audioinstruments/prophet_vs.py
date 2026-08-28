"""Sequential Circuits Prophet VS vector synthesizer."""

NAME = 'prophet_vs'
DISPLAY_NAME = 'Prophet VS'
CATEGORIES = ('Synth',)
VERSION = '0.0.1'
VENDOR = "PyDevices"

MACRO_LABELS = (
    "Volume", "Joystick X", "Joystick Y", "Cutoff", "Resonance",
    "Env Amount", "Chorus", "Filter Attack", "Filter Decay",
    "Filter Sustain", "Filter Release", "Amp Attack", "Amp Decay",
    "Amp Sustain", "Amp Release", "Master Tune",
)
MACRO_MODES = {
    0: "UNIPOLAR",
    1: "BIPOLAR",
    2: "BIPOLAR",
    3: "UNIPOLAR",
    4: "UNIPOLAR",
    5: "UNIPOLAR",
    6: "UNIPOLAR",
    7: "UNIPOLAR",
    8: "UNIPOLAR",
    9: "UNIPOLAR",
    10: "UNIPOLAR",
    11: "UNIPOLAR",
    12: "UNIPOLAR",
    13: "UNIPOLAR",
    14: "UNIPOLAR",
    15: "BIPOLAR",
}

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ("Default", (102, 64, 64, 108, 18, 48, 0, 1, 19, 64, 16, 1, 19, 102, 16,
                 64)),
}

import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, env_shape_table, key_of,
    make_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

# 4 distinct wavetables for vector synthesis
WAVE_A = make_table([(n, 1.0 / n) for n in range(1, 20)]) # Saw-ish
WAVE_B = make_table([(n, 1.0 / n) for n in range(1, 20, 2)]) # Square-ish
WAVE_C = make_table([(n, 1.0 / (n*n)) for n in range(1, 20, 2)]) # Triangle-ish
WAVE_D = make_table(((1, 1.0), (3, 0.5), (5, 0.25), (7, 0.1), (9, 0.05))) # Bell-ish
SINE = make_table(((1, 1.0),), fast=False)


def create(sample_rate, channel_count=2, transport=None):
    SR = sample_rate
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=channel_count)

    # Macros
    volume = 0.8
    joy_x = 0.5
    joy_y = 0.5
    cutoff_base = 2500.0
    resonance = 1.0
    env_amount = 3000.0
    chorus = 0.0

    f_a = 0.01
    f_d = 0.5
    f_s = 0.5
    f_r = 0.5
    a_a = 0.01
    a_d = 0.5
    a_s = 0.8
    a_r = 0.5
    master_tune = 1.0

    voices = {}
    serial = 0
    MAX_VOICES = 8


    def release_voice(k):
        voice = _support.release_voice(voices, synth, k)
        if voice is not None and voice[2] is not None:
            rel_filter = _support.release_filter(voice[2])
            for note in voice[3]:
                note.filter = rel_filter

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, joy_x, joy_y, cutoff_base, resonance, env_amount, chorus
        nonlocal f_a, f_d, f_s, f_r, a_a, a_d, a_s, a_r, master_tune
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
            f_sweep = synthio.LFO(waveform=env_tbl, once=True, rate=1.0/max(0.01, f_a + f_d), scale=env_amount, interpolate=True)
            cutoff = synthio.Math(synthio.MathOperation.SUM, cutoff_base, f_sweep, 0.0)

            lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, cutoff, Q=resonance)

            # Vector mixing math
            # A: top left (1-x, 1-y), B: top right (x, 1-y), C: bottom left (1-x, y), D: bottom right (x, y)
            mix_a = (1.0 - joy_x) * (1.0 - joy_y)
            mix_b = joy_x * (1.0 - joy_y)
            mix_c = (1.0 - joy_x) * joy_y
            mix_d = joy_x * joy_y

            # Chorus: an animated pitch wobble reads as chorus, not just stereo width, so add a
            # slow bend LFO on top of the static spread.
            chorus_lfo = synthio.LFO(waveform=SINE, rate=0.6, scale=chorus * 0.006) if chorus > 0.01 else None

            notes = []
            if mix_a > 0.01:
                notes.append(synthio.Note(hz, waveform=WAVE_A, envelope=env, filter=lp, amplitude=amp * mix_a, panning=-chorus, bend=chorus_lfo))
            if mix_b > 0.01:
                notes.append(synthio.Note(hz * 1.002, waveform=WAVE_B, envelope=env, filter=lp, amplitude=amp * mix_b, panning=chorus, bend=chorus_lfo))
            if mix_c > 0.01:
                notes.append(synthio.Note(hz * 0.998, waveform=WAVE_C, envelope=env, filter=lp, amplitude=amp * mix_c, panning=-chorus*0.5, bend=chorus_lfo))
            if mix_d > 0.01:
                notes.append(synthio.Note(hz * 1.001, waveform=WAVE_D, envelope=env, filter=lp, amplitude=amp * mix_d, panning=chorus*0.5, bend=chorus_lfo))

            # Filter Release: retarget the shared filter to a real release sweep
            # at note-off (Note.filter is mutable post-construction), since the
            # one-shot attack/decay LFO above can't represent an indefinite
            # sustain hold followed by a release triggered by an unknown-in-
            # advance note-off time.
            filt_release = (cutoff_base, env_amount * f_s, f_r, resonance)

            serial += 1
            voices[k] = (tuple(notes), serial, filt_release,
                       tuple(notes))
            for n in notes:
                synth.press(n)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: joy_x = value0
            elif data0 == 2: joy_y = value0
            elif data0 == 3: cutoff_base = 50.0 * (100.0 ** value0)
            elif data0 == 4: resonance = 0.5 + value0 * 3.5
            elif data0 == 5: env_amount = value0 * 8000.0
            elif data0 == 6: chorus = value0
            elif data0 == 7: f_a = 0.001 + value0 * 2.0
            elif data0 == 8: f_d = 0.05 + value0 * 3.0
            elif data0 == 9: f_s = value0
            elif data0 == 10: f_r = 0.01 + value0 * 4.0
            elif data0 == 11: a_a = 0.001 + value0 * 2.0
            elif data0 == 12: a_d = 0.05 + value0 * 3.0
            elif data0 == 13: a_s = value0
            elif data0 == 14: a_r = 0.01 + value0 * 4.0
            elif data0 == 15: master_tune = 0.95 + value0 * 0.1

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    return instrument
