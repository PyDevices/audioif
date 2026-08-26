"""Fender Rhodes electric piano."""

MACRO_LABELS = (
    "Volume", "Tine Level", "Body Level", "Tremolo Rate", "Tremolo Depth",
    "Overdrive", "Tone", "Amp Attack", "Amp Decay", "Amp Sustain",
    "Amp Release", "Key-Off Noise", "Master Tune",
)

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ('Init', (102, 51, 64, 37, 0, 0, 64, 2, 48, 25, 25, 13, 64)),
}

import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, key_of, make_table,
    noise_table, ring_depth_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

# Body (warm fundamental)
WAVE_BODY = make_table(((1, 1.0), (3, 0.1)), fast=False)
# Tine (metallic bell attack)
WAVE_TINE = make_table(((1, 1.0), (4, 0.8), (7, 0.5), (14, 0.2)), fast=False)

NOISE = noise_table(seed=1234)
SINE = make_table(((1, 1.0),), fast=False)


def create(sample_rate, transport=None):
    SR = sample_rate
    NOISE_HZ = SR / 8192.0
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=2)

    # Macros
    volume = 0.8
    tine_lvl = 0.8
    body_lvl = 1.0
    trem_rate = 3.0
    trem_depth = 0.0
    overdrive = 1.0
    tone = 3000.0
    amp_a = 0.01
    amp_d = 2.0
    amp_s = 0.2
    amp_r = 0.5
    key_off = 0.1
    master_tune = 1.0

    voices = {}
    serial = 0
    MAX_VOICES = 16


    def release_voice(k):
        voice = _support.release_voice(voices, synth, k)
        if voice is not None and key_off > 0.01:
            env = synthio.Envelope(attack_time=0.001, decay_time=0.1, release_time=0.1, attack_level=1.0, sustain_level=0.0)
            bp = synthio.Biquad(synthio.FilterMode.BAND_PASS, 500.0, Q=1.0)
            n = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=env, filter=bp, amplitude=volume * key_off * 0.2)
            synth.press(n)
            synth.release(n)  # let the envelope play out

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, tine_lvl, body_lvl, trem_rate, trem_depth, overdrive, tone
        nonlocal amp_a, amp_d, amp_s, amp_r, key_off, master_tune
        nonlocal serial

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            release_voice(k)
            if len(voices) >= MAX_VOICES:
                steal_oldest()

            hz = synthio.midi_to_hz(data0 + value1) * master_tune
            amp = volume * value0 * overdrive

            env = synthio.Envelope(attack_time=amp_a, decay_time=amp_d, release_time=amp_r, attack_level=1.0, sustain_level=amp_s)
            tine_env = synthio.Envelope(attack_time=0.001, decay_time=0.3, release_time=0.1, attack_level=1.0, sustain_level=0.0)

            lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, tone, Q=0.7)

            # True stereo tremolo needs per-channel phase; ring-mod tremolo on
            # a shared modulator plus opposite panning gets an auto-pan feel.
            trem_wave = ring_depth_table(trem_depth) if trem_depth > 0.01 else None

            # Note panning
            pan_l = -0.3
            pan_r = 0.3

            o_body = synthio.Note(hz, waveform=WAVE_BODY, envelope=env, filter=lp, amplitude=amp * body_lvl * 0.5, ring_frequency=trem_rate, ring_waveform=trem_wave, panning=pan_l)
            o_tine = synthio.Note(hz, waveform=WAVE_TINE, envelope=tine_env, filter=lp, amplitude=amp * tine_lvl * 0.4, ring_frequency=trem_rate, ring_waveform=trem_wave, panning=pan_r)

            serial += 1
            voices[k] = ((o_body, o_tine), serial)
            synth.press(o_body)
            synth.press(o_tine)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: tine_lvl = value0 * 2.0
            elif data0 == 2: body_lvl = value0 * 2.0
            elif data0 == 3: trem_rate = 0.1 + value0 * 10.0
            elif data0 == 4: trem_depth = value0
            elif data0 == 5: overdrive = 1.0 + value0 * 2.0
            elif data0 == 6: tone = 500.0 + value0 * 5000.0
            elif data0 == 7: amp_a = 0.001 + value0 * 0.5
            elif data0 == 8: amp_d = 0.5 + value0 * 4.0
            elif data0 == 9: amp_s = value0
            elif data0 == 10: amp_r = 0.1 + value0 * 2.0
            elif data0 == 11: key_off = value0
            elif data0 == 12: master_tune = 0.95 + value0 * 0.1

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    instrument.program_change(0)
    return instrument
