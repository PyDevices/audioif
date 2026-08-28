"""Moog Taurus bass pedals."""

NAME = 'taurus'
DISPLAY_NAME = 'Taurus'
CATEGORIES = ('Synth',)
VERSION = '0.0.1'
VENDOR = "PyDevices"

MACRO_LABELS = (
    "Volume", "Osc B Detune", "Glide", "Cutoff", "Resonance", "Env Mod",
    "Beat Freq", "Amp Attack", "Amp Decay", "Amp Sustain", "Amp Release",
    "Master Tune",
)
MACRO_MODES = {
    0: "UNIPOLAR",
    1: "UNIPOLAR",
    2: "UNIPOLAR",
    3: "UNIPOLAR",
    4: "UNIPOLAR",
    5: "UNIPOLAR",
    6: "UNIPOLAR",
    7: "UNIPOLAR",
    8: "UNIPOLAR",
    9: "UNIPOLAR",
    10: "UNIPOLAR",
    11: "BIPOLAR",
}

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ("Default", (102, 64, 0, 83, 12, 51, 64, 1, 30, 64, 31, 64)),
}

import array
import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, FALL, key_of,
    make_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

SAW = make_table([(n, 1.0 / n) for n in range(1, 40)], fast=False)
SINE = make_table(((1, 1.0),), fast=False)


def create(sample_rate, transport=None):
    SR = sample_rate
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=2)

    # Macros
    volume = 0.8
    osc_b_detune = 0.01
    glide = 0.0
    cutoff_val = 1000.0
    res = 1.0
    env_mod = 2000.0
    beat_freq = 0.5
    amp_a = 0.01
    amp_d = 1.0
    amp_s = 0.5
    amp_r = 1.0
    master_tune = 1.0

    voices = {}
    serial = 0
    last_pitch = None
    MAX_VOICES = 1 # Monophonic bass pedals


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, osc_b_detune, glide, cutoff_val, res, env_mod, beat_freq
        nonlocal amp_a, amp_d, amp_s, amp_r, master_tune
        nonlocal serial, last_pitch

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            if len(voices) >= MAX_VOICES:
                steal_oldest()

            hz = synthio.midi_to_hz(data0 + value1) * master_tune
            amp = volume * value0

            bend = None
            if last_pitch is not None and glide > 0.001:
                last_hz = synthio.midi_to_hz(last_pitch) * master_tune
                ratio = last_hz / hz
                glide_table = array.array("h", (int(32767 * (ratio - 1.0)), 0))
                bend = synthio.LFO(waveform=glide_table, once=True, rate=1.0 / glide, interpolate=True)
            last_pitch = data0

            env = synthio.Envelope(attack_time=amp_a, decay_time=amp_d, release_time=amp_r, attack_level=1.0, sustain_level=amp_s)

            f_sweep = synthio.LFO(waveform=FALL, once=True, rate=1.0/amp_d, scale=env_mod, interpolate=True)
            cutoff = synthio.Math(synthio.MathOperation.SUM, cutoff_val, f_sweep, 0.0)

            lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, cutoff, Q=res)

            # Taurus is famous for two VCOs detuned to create a slow beat; express the
            # beat control as an actual target Hz (not a fixed ratio) so the wobble rate
            # stays audible and consistent across the bass register instead of scaling
            # away at low notes or turning into a dissonant interval at high ones.
            beat_hz = 0.15 + beat_freq * 1.5
            actual_detune = osc_b_detune + (beat_hz / hz)

            n1 = synthio.Note(hz, waveform=SAW, envelope=env, filter=lp, amplitude=amp * 0.45, bend=bend)
            n2 = synthio.Note(hz * (1.0 + actual_detune), waveform=SAW, envelope=env, filter=lp, amplitude=amp * 0.45, bend=bend)
            # Taurus pedals are defined by huge sub content; add a fixed sub-octave sine
            # under the two detuned saws for the low-end weight the real pedal has.
            n3 = synthio.Note(hz * 0.5, waveform=SINE, envelope=env, filter=lp, amplitude=amp * 0.5, bend=bend)

            serial += 1
            voices[k] = ((n1, n2, n3), serial)
            synth.press(n1)
            synth.press(n2)
            synth.press(n3)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: osc_b_detune = value0 * 0.02
            elif data0 == 2: glide = value0
            elif data0 == 3: cutoff_val = 50.0 * (100.0 ** value0)
            elif data0 == 4: res = 0.5 + value0 * 5.5
            elif data0 == 5: env_mod = value0 * 5000.0
            elif data0 == 6: beat_freq = value0
            elif data0 == 7: amp_a = 0.001 + value0 * 2.0
            elif data0 == 8: amp_d = 0.05 + value0 * 4.0
            elif data0 == 9: amp_s = value0
            elif data0 == 10: amp_r = 0.01 + value0 * 4.0
            elif data0 == 11: master_tune = 0.95 + value0 * 0.1

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    instrument.program_change(0)
    return instrument
