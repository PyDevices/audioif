"""ARP/Eminent Solina String Ensemble."""

NAME = 'Solina'
CATEGORIES = ('Synth',)
VERSION = '0.0.1'
VENDOR = "PyDevices"

MACRO_LABELS = (
    "Volume", "Violin Mix", "Viola Mix", "Cello Mix", "Chorus Depth",
    "Attack", "Release", "Crescendo", "Master Tune",
)

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ('Init', (102, 127, 64, 64, 127, 6, 16, 0, 64)),
}

import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, key_of, make_table,
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
    violin = 1.0
    viola = 0.5
    cello = 0.5
    chorus_depth = 1.0
    att = 0.1
    rel = 0.5
    crescendo = 0.0
    master_tune = 1.0

    voices = {}
    serial = 0
    MAX_VOICES = 6


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, violin, viola, cello, chorus_depth, att, rel, crescendo, master_tune
        nonlocal serial

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            release_voice(k)
            if len(voices) >= MAX_VOICES:
                steal_oldest()

            hz = synthio.midi_to_hz(data0 + value1) * master_tune
            amp = volume * value0

            # Crescendo makes attack slower based on velocity or macro
            actual_att = att + (crescendo * 2.0)
            env = synthio.Envelope(attack_time=actual_att, decay_time=0.1, release_time=rel, attack_level=1.0, sustain_level=1.0)

            lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, 5000.0, Q=0.5)

            notes = []

            # Solina ensemble chorus emulation (3-4 detuned/modulated saws per voice)
            # We apply slow separate LFOs to each to simulate BBD ensemble
            rates = [0.6, 6.0, 4.0]
            pans = [-0.5, 0.0, 0.5]

            for reg_mult, reg_vol in [(1.0, violin), (0.5, viola), (0.25, cello)]:
                if reg_vol > 0.01:
                    for i in range(3):
                        mod_lfo = synthio.LFO(waveform=SINE, rate=rates[i], scale=chorus_depth * 0.008)
                        n = synthio.Note(hz * reg_mult, waveform=SAW, envelope=env, filter=lp, amplitude=amp * reg_vol * 0.15, bend=mod_lfo, panning=pans[i])
                        notes.append(n)

            serial += 1
            voices[k] = (tuple(notes), serial)
            for n in notes:
                synth.press(n)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: violin = value0
            elif data0 == 2: viola = value0
            elif data0 == 3: cello = value0
            elif data0 == 4: chorus_depth = value0
            elif data0 == 5: att = 0.001 + value0 * 2.0
            elif data0 == 6: rel = 0.01 + value0 * 4.0
            elif data0 == 7: crescendo = value0
            elif data0 == 8: master_tune = 0.95 + value0 * 0.1

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    instrument.program_change(0)
    return instrument
