"""Roland TB-303 Bass Line."""

NAME = 'tb303'
DISPLAY_NAME = 'TB-303'
CATEGORIES = ('Synth',)
VERSION = '0.0.1'
VENDOR = "PyDevices"

MACRO_LABELS = (
    "Volume", "Tuning", "Cutoff", "Resonance", "Env Mod", "Decay", "Accent",
    "Overdrive", "Master Tune",
)
MACRO_MODES = {
    0: "UNIPOLAR",
    1: "BIPOLAR",
    2: "UNIPOLAR",
    3: "UNIPOLAR",
    4: "UNIPOLAR",
    5: "UNIPOLAR",
    6: "UNIPOLAR",
    7: "UNIPOLAR",
    8: "BIPOLAR",
}

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ("Default", (102, 64, 64, 42, 64, 29, 0, 0, 64)),
}

import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, FALL, key_of,
    make_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

SAW = make_table([(n, 1.0 / n) for n in range(1, 40)], fast=False)


def create(sample_rate, channel_count=2, transport=None):
    SR = sample_rate
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=channel_count)

    # Macros
    volume = 0.8
    tuning = 1.0
    cutoff_val = 500.0
    res = 2.0
    env_mod = 4000.0
    decay_time = 0.5
    accent = 0.0
    overdrive = 1.0
    master_tune = 1.0

    voices = {}
    serial = 0
    MAX_VOICES = 1 # Monosynth


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, tuning, cutoff_val, res, env_mod, decay_time, accent, overdrive, master_tune
        nonlocal serial

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            if len(voices) >= MAX_VOICES:
                steal_oldest()

            hz = synthio.midi_to_hz(data0 + value1) * master_tune * tuning

            # The 303's accent circuit feeds extra voltage into both the VCF envelope
            # generator and the VCA at once, snapping the filter open harder and louder
            # together - scale continuously with the accent knob, not a hard switch.
            actual_decay = decay_time * (1.0 - 0.7 * accent)
            actual_env_mod = env_mod * (1.0 + 1.2 * accent)

            amp = volume * value0 * overdrive * (1.0 + 0.5 * accent)

            env = synthio.Envelope(attack_time=0.01, decay_time=actual_decay, release_time=0.1, attack_level=1.0, sustain_level=0.1)

            f_sweep = synthio.LFO(waveform=FALL, once=True, rate=1.0/actual_decay, scale=actual_env_mod, interpolate=True)
            cutoff = synthio.Math(synthio.MathOperation.SUM, cutoff_val, f_sweep, 0.0)

            lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, cutoff, Q=res)

            n = synthio.Note(hz, waveform=SAW, envelope=env, filter=lp, amplitude=amp * 0.5)

            serial += 1
            voices[k] = ((n,), serial)
            synth.press(n)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: tuning = 0.5 + value0
            elif data0 == 2: cutoff_val = 50.0 * (100.0 ** value0)
            elif data0 == 3: res = 0.5 + value0 * 4.5
            elif data0 == 4: env_mod = value0 * 8000.0
            elif data0 == 5: decay_time = 0.05 + value0 * 2.0
            elif data0 == 6: accent = value0
            elif data0 == 7: overdrive = 1.0 + value0 * 3.0
            elif data0 == 8: master_tune = 0.95 + value0 * 0.1

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    return instrument
