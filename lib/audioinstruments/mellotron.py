"""Mellotron M400."""

NAME = 'mellotron'
DISPLAY_NAME = 'Mellotron M400'
CATEGORIES = ('Sampler',)
VERSION = '0.0.1'
VENDOR = "PyDevices"

MACRO_LABELS = (
    "Volume", "Tone", "Flutter Rate", "Flutter Depth", "Attack", "Release",
    "Tape Hiss", "Master Tune",
)
MACRO_MODES = {
    0: "UNIPOLAR",
    1: "UNIPOLAR",
    2: "UNIPOLAR",
    3: "UNIPOLAR",
    4: "UNIPOLAR",
    5: "UNIPOLAR",
    6: "UNIPOLAR",
    7: "BIPOLAR",
}

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ('Default', (102, 80, 37, 13, 77, 55, 13, 64)),
}

import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, key_of, logmap, make_table,
    noise_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

WAVE_FLUTE = make_table(((1, 1.0), (2, 0.4), (3, 0.2)), fast=False)
NOISE = noise_table(seed=1234)
SINE = make_table(((1, 1.0),), fast=False)


def create(sample_rate, channel_count=2, transport=None):
    SR = sample_rate
    NOISE_HZ = SR / 8192.0
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=channel_count)

    # Macros
    volume = 0.8
    tone = 2000.0
    flutter_rate = 3.0
    flutter_depth = 0.1
    att = 0.1
    rel = 0.1
    tape_hiss = 0.1
    master_tune = 1.0

    voices = {}
    serial = 0
    MAX_VOICES = 8
    hiss_note = None


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def update_hiss():
        nonlocal hiss_note
        # Tape hiss continues as long as a note is pressed (tape engaged).
        if len(voices) > 0 and tape_hiss > 0.01:
            target_amp = volume * tape_hiss * 0.1
            if hiss_note is None:
                env = synthio.Envelope(attack_time=0.1, decay_time=0.1, release_time=0.1, attack_level=1.0, sustain_level=1.0)
                lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, 4000.0, Q=0.5)
                hiss_note = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=env, filter=lp, amplitude=target_amp)
                synth.press(hiss_note)
            else:
                hiss_note.amplitude = target_amp
        else:
            if hiss_note is not None:
                synth.release(hiss_note)
                hiss_note = None

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, tone, flutter_rate, flutter_depth, att, rel, tape_hiss, master_tune
        nonlocal serial

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            release_voice(k)
            if len(voices) >= MAX_VOICES:
                steal_oldest()

            hz = synthio.midi_to_hz(data0 + value1) * master_tune
            amp = volume * value0

            env = synthio.Envelope(attack_time=att, decay_time=0.1, release_time=rel, attack_level=1.0, sustain_level=1.0)

            # Tape wow/flutter
            flutter_lfo = synthio.LFO(waveform=SINE, rate=flutter_rate, scale=flutter_depth * 0.012) if flutter_depth > 0.01 else None

            # Bandpass filter for lo-fi tape sound
            bp = synthio.Biquad(synthio.FilterMode.BAND_PASS, tone, Q=0.8)

            n = synthio.Note(hz, waveform=WAVE_FLUTE, envelope=env, filter=bp, amplitude=amp * 0.6, bend=flutter_lfo)

            serial += 1
            voices[k] = ((n,), serial)
            synth.press(n)
            update_hiss()

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)
            update_hiss()

        elif event_type == EVENT_PARAMETER:
            if data0 == 0:
                volume = value0
                update_hiss()
            elif data0 == 1: tone = logmap(value0, 500.0, 4500.0)
            elif data0 == 2: flutter_rate = 0.1 + value0 * 10.0
            elif data0 == 3: flutter_depth = value0
            elif data0 == 4: att = logmap(value0, 0.001, 2.001)
            elif data0 == 5: rel = logmap(value0, 0.01, 2.01)
            elif data0 == 6: 
                tape_hiss = value0
                update_hiss()
            elif data0 == 7: master_tune = 0.95 + value0 * 0.1

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    return instrument
