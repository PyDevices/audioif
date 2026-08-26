"""Korg MS2000."""

MACRO_LABELS = (
    "Volume", "Osc Waveform", "Cutoff", "Resonance", "Mod Seq Rate",
    "Mod Seq Depth", "Distortion", "Amp Attack", "Amp Decay", "Amp Sustain",
    "Amp Release", "Master Tune",
)

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ('Init', (102, 0, 102, 18, 50, 64, 0, 1, 19, 102, 16, 64)),
}

import array
import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, key_of, make_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

SAW = make_table([(n, 1.0 / n) for n in range(1, 40)], fast=False)
SQUARE = make_table([(n, 1.0 / n) for n in range(1, 40, 2)], fast=False)
# "DWGS" digital wave approx
DWGS = make_table(((1, 1.0), (3, 0.5), (4, 0.4), (7, 0.2)), fast=False)

# 8-step waveform table stands in for the MS2000's 16-step Mod Sequencer:
# a real step sequencer object (not an LFO shape) that steps a value once
# per beat division and holds it - built here as a stepped LFO waveform
LFO_STEP = array.array("h", bytearray(2048 * 2))
for i in range(2048):
    # Create an 8-step sequence
    step_idx = (i * 8) // 2048
    val = [32767, 16000, 32767, -32767, -16000, 0, 16000, -32767][step_idx]
    LFO_STEP[i] = val


def create(sample_rate, transport=None):
    SR = sample_rate
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=2)

    # Macros
    volume = 0.8
    osc_wave = 0.0 # 0=Saw, 1=Square, 2=DWGS
    cutoff_val = 2000.0
    res = 1.0
    mod_seq_rate = 4.0
    mod_seq_depth = 0.5
    distortion = 0.0
    amp_a = 0.01
    amp_d = 0.5
    amp_s = 0.8
    amp_r = 0.5
    master_tune = 1.0

    voices = {}
    serial = 0
    MAX_VOICES = 4


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, osc_wave, cutoff_val, res, mod_seq_rate, mod_seq_depth, distortion
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

            # Mod Sequence: the MS2000's Mod Sequencer is a real 16-step value
            # sequencer, not an LFO shape - approximated here as an 8-step
            # stepped table driving the filter cutoff, one step per beat
            # division set by Mod Seq Rate, depth set by Mod Seq Depth
            mod_lfo = synthio.LFO(waveform=LFO_STEP, rate=mod_seq_rate, scale=mod_seq_depth * 3000.0) if mod_seq_depth > 0.01 else 0.0
            cutoff = synthio.Math(synthio.MathOperation.SUM, cutoff_val, mod_lfo, 0.0) if mod_seq_depth > 0.01 else cutoff_val

            lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, cutoff, Q=res)

            wave = SAW
            if osc_wave > 0.6: wave = DWGS
            elif osc_wave > 0.3: wave = SQUARE

            notes = [synthio.Note(hz, waveform=wave, envelope=env, filter=lp, amplitude=amp * 0.7)]
            # Distortion: fold in an unfiltered octave-up square for extra edge,
            # the way the MS2000's digital drive stage adds grit above the filter
            if distortion > 0.01:
                notes.append(synthio.Note(hz * 2.0, waveform=SQUARE, envelope=env, amplitude=amp * distortion * 0.2))

            serial += 1
            voices[k] = (tuple(notes), serial)
            for n in notes:
                synth.press(n)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: osc_wave = value0
            elif data0 == 2: cutoff_val = 50.0 * (100.0 ** value0)
            elif data0 == 3: res = 0.5 + value0 * 3.5
            elif data0 == 4: mod_seq_rate = 0.1 + value0 * 10.0
            elif data0 == 5: mod_seq_depth = value0
            elif data0 == 6: distortion = value0 * 2.0
            elif data0 == 7: amp_a = 0.001 + value0 * 2.0
            elif data0 == 8: amp_d = 0.05 + value0 * 3.0
            elif data0 == 9: amp_s = value0
            elif data0 == 10: amp_r = 0.01 + value0 * 4.0
            elif data0 == 11: master_tune = 0.95 + value0 * 0.1

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    instrument.program_change(0)
    return instrument
