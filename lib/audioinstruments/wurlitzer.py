"""Wurlitzer 200A electric piano."""

NAME = 'wurlitzer'
DISPLAY_NAME = 'Wurlitzer 200A'
CATEGORIES = ('Piano',)
VERSION = '0.0.1'
VENDOR = "PyDevices"

MACRO_LABELS = (
    "Volume", "Bite", "Bark", "Tremolo Rate", "Tremolo Depth", "Amp Attack",
    "Amp Decay", "Amp Sustain", "Amp Release", "Master Tune",
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
    9: "BIPOLAR",
}

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ("Default", (102, 32, 64, 50, 0, 2, 42, 25, 19, 64)),
}

import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, key_of, make_table,
    ring_depth_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

# Reeds are grittier than tines
WAVE_REED = make_table(((1, 1.0), (2, 0.4), (3, 0.2), (4, 0.1), (5, 0.05)), asym=0.25, fast=False)
WAVE_BITE = make_table(((1, 1.0), (3, 0.8), (5, 0.6), (7, 0.4), (9, 0.2)), asym=0.4, fast=False)
SINE = make_table(((1, 1.0),), fast=False)


def create(sample_rate, transport=None):
    SR = sample_rate
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=2)

    # Macros
    volume = 0.8
    bite = 0.5
    bark = 0.5
    trem_rate = 4.0
    trem_depth = 0.0
    amp_a = 0.01
    amp_d = 1.5
    amp_s = 0.2
    amp_r = 0.4
    master_tune = 1.0

    voices = {}
    serial = 0
    MAX_VOICES = 16


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, bite, bark, trem_rate, trem_depth
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
            bite_env = synthio.Envelope(attack_time=0.001, decay_time=0.2, release_time=0.1, attack_level=1.0, sustain_level=0.0)

            # Velocity affects filter cutoff heavily for the "bark"
            cutoff = 1000.0 + (value0 * bark * 5000.0)
            lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, cutoff, Q=0.8)

            trem_wave = ring_depth_table(trem_depth) if trem_depth > 0.01 else None

            o_reed = synthio.Note(hz, waveform=WAVE_REED, envelope=env, filter=lp, amplitude=amp * 0.6, ring_frequency=trem_rate, ring_waveform=trem_wave)
            o_bite = synthio.Note(hz, waveform=WAVE_BITE, envelope=bite_env, filter=lp, amplitude=amp * bite * 0.4, ring_frequency=trem_rate, ring_waveform=trem_wave)

            serial += 1
            voices[k] = ((o_reed, o_bite), serial)
            synth.press(o_reed)
            synth.press(o_bite)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: bite = value0 * 2.0
            elif data0 == 2: bark = value0
            elif data0 == 3: trem_rate = 0.1 + value0 * 10.0
            elif data0 == 4: trem_depth = value0
            elif data0 == 5: amp_a = 0.001 + value0 * 0.5
            elif data0 == 6: amp_d = 0.5 + value0 * 3.0
            elif data0 == 7: amp_s = value0
            elif data0 == 8: amp_r = 0.1 + value0 * 2.0
            elif data0 == 9: master_tune = 0.95 + value0 * 0.1

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    instrument.program_change(0)
    return instrument
