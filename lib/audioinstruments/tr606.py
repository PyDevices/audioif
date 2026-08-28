"""Roland TR-606 Drumatix."""

NAME = 'tr606'
DISPLAY_NAME = 'TR-606'
CATEGORIES = ('Drum',)
VERSION = '0.0.1'
VENDOR = "PyDevices"

MACRO_LABELS = (
    "Level", "Accent", "BD Level", "BD Decay", "BD Pitch", "SD Level",
    "SD Snappy", "SD Pitch", "LT Pitch", "HT Pitch", "Cym Level",
    "Cym Decay", "Cym Tone", "Hat Level", "CH Decay", "OH Decay",
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
    11: "UNIPOLAR",
    12: "UNIPOLAR",
    13: "UNIPOLAR",
    14: "UNIPOLAR",
    15: "UNIPOLAR",
}

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ("Default", (102, 64, 98, 61, 64, 98, 76, 70, 65, 72, 88, 69, 90, 88,
                 58, 78)),
}

NOTE_MAP = (
    (36, "Bass Drum"),
    (38, "Snare"),
    (41, "Low Tom"),
    (48, "Hi Tom"),
    (42, "Closed Hat"),
    (46, "Open Hat"),
    (49, "Cymbal"),
)

import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, FALL, key_of, logmap,
    make_table, noise_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

SINE = make_table(((1, 1.0),))
TRIANGLE = make_table([(n, (1.0 / (n*n)) * (-1)**((n-1)//2)) for n in range(1, 11, 2)])
NOISE = noise_table(seed=606060)


def create(sample_rate, channel_count=2, transport=None):
    SR = sample_rate
    NOISE_HZ = SR / 8192.0
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=channel_count)

    # Master params
    master_level = 0.8
    accent_level = 0.5

    # Voice Levels
    bd_level = 1.0
    sd_level = 1.0
    cym_level = 0.8
    hat_level = 0.8

    # BD params
    bd_decay = 0.3
    bd_pitch = 60.0

    # SD params
    sd_snappy = 0.6
    sd_pitch = 220.0

    # Toms
    lt_pitch = 100.0
    ht_pitch = 160.0

    # Others
    cym_decay = 0.6
    cym_tone = 6000.0
    ch_decay = 0.05
    oh_decay = 0.3

    voices = {}
    serial = 0
    open_hat_keys = []
    MAX_VOICES = 12




    def release_voice(k):
        _support.release_voice(voices, synth, k)


    def steal_oldest():
        _support.steal_oldest(voices, release_voice)


    def trigger_voice(k, notes):
        nonlocal serial
        serial = _support.trigger_voice(voices, synth, serial, MAX_VOICES,
                                        release_voice, k, notes)


    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal master_level, accent_level
        nonlocal bd_level, bd_decay, bd_pitch
        nonlocal sd_level, sd_snappy, sd_pitch
        nonlocal lt_pitch, ht_pitch
        nonlocal cym_level, cym_decay, cym_tone, hat_level, ch_decay, oh_decay

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            pitch = data0
            vel = value0
            base_amp = master_level * (vel + accent_level * (1.0 if vel > 0.8 else 0.0))

            notes_to_play = []

            # BD (35, 36)
            if pitch in (35, 36):
                amp = base_amp * bd_level
                env = synthio.Envelope(attack_time=0.001, decay_time=bd_decay, release_time=0.05, attack_level=1.0, sustain_level=0.0)
                drop = synthio.LFO(waveform=FALL, once=True, rate=25.0, scale=0.3, interpolate=True)
                lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, bd_pitch * 4.0, Q=0.7)
                body = synthio.Note(bd_pitch, waveform=SINE, envelope=env, filter=lp, amplitude=amp, bend=drop)
                notes_to_play.append(body)

            # SD (38, 40)
            elif pitch in (38, 40):
                amp = base_amp * sd_level
                body_env = synthio.Envelope(attack_time=0.001, decay_time=0.1, release_time=0.05, attack_level=1.0, sustain_level=0.0)
                drop = synthio.LFO(waveform=FALL, once=True, rate=40.0, scale=0.15, interpolate=True)
                body = synthio.Note(sd_pitch, waveform=TRIANGLE, envelope=body_env, amplitude=amp*0.8, bend=drop)

                snare_env = synthio.Envelope(attack_time=0.001, decay_time=0.15, release_time=0.05, attack_level=1.0, sustain_level=0.0)
                snare_hp = synthio.Biquad(synthio.FilterMode.HIGH_PASS, 2000.0, Q=1.0)
                snare = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=snare_env, filter=snare_hp, amplitude=amp * sd_snappy)

                notes_to_play.extend([body, snare])

            # Toms (41, 43, 45, 47, 48, 50)
            elif pitch in (41, 43, 45, 47, 48, 50):
                amp = base_amp * 0.8
                tune = lt_pitch if pitch < 48 else ht_pitch

                env = synthio.Envelope(attack_time=0.001, decay_time=0.3, release_time=0.1, attack_level=1.0, sustain_level=0.0)
                drop = synthio.LFO(waveform=FALL, once=True, rate=20.0, scale=0.2, interpolate=True)
                note = synthio.Note(tune, waveform=SINE, envelope=env, amplitude=amp, bend=drop)
                notes_to_play.append(note)

            # Hats (42, 44, 46)
            elif pitch in (42, 44, 46):
                amp = base_amp * hat_level
                is_open = pitch == 46
                if not is_open:
                    for ok in open_hat_keys:
                        release_voice(ok)
                    open_hat_keys.clear()

                env = synthio.Envelope(attack_time=0.001, decay_time=oh_decay if is_open else ch_decay, release_time=0.05, attack_level=1.0, sustain_level=0.0)
                hp = synthio.Biquad(synthio.FilterMode.HIGH_PASS, cym_tone * 1.5, Q=0.8)
                note = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=env, filter=hp, amplitude=amp * 0.7)
                notes_to_play.append(note)
                if is_open:
                    open_hat_keys.append(k)

            # Cymbal (49, 51, 57, 59)
            elif pitch in (49, 51, 57, 59):
                amp = base_amp * cym_level
                env = synthio.Envelope(attack_time=0.001, decay_time=cym_decay, release_time=0.2, attack_level=1.0, sustain_level=0.0)
                bp = synthio.Biquad(synthio.FilterMode.BAND_PASS, cym_tone, Q=0.5)
                hp = synthio.Biquad(synthio.FilterMode.HIGH_PASS, cym_tone * 1.5, Q=0.7)
                note1 = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=env, filter=bp, amplitude=amp * 0.5)
                note2 = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=env, filter=hp, amplitude=amp * 0.5)
                notes_to_play.extend([note1, note2])

            # Fallback (other percussion)
            else:
                amp = base_amp * 0.6
                env = synthio.Envelope(attack_time=0.001, decay_time=0.1, release_time=0.05, attack_level=1.0, sustain_level=0.0)
                bp = synthio.Biquad(synthio.FilterMode.BAND_PASS, 3000.0, Q=1.0)
                note = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=env, filter=bp, amplitude=amp)
                notes_to_play.append(note)

            if notes_to_play:
                trigger_voice(k, notes_to_play)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)
            if k in open_hat_keys:
                open_hat_keys.remove(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: master_level = value0
            elif data0 == 1: accent_level = value0
            elif data0 == 2: bd_level = logmap(value0, 0.1, 2.0)
            elif data0 == 3: bd_decay = logmap(value0, 0.1, 1.0)
            elif data0 == 4: bd_pitch = logmap(value0, 40.0, 90.0)
            elif data0 == 5: sd_level = logmap(value0, 0.1, 2.0)
            elif data0 == 6: sd_snappy = value0
            elif data0 == 7: sd_pitch = logmap(value0, 150.0, 300.0)
            elif data0 == 8: lt_pitch = logmap(value0, 70.0, 140.0)
            elif data0 == 9: ht_pitch = logmap(value0, 120.0, 200.0)
            elif data0 == 10: cym_level = logmap(value0, 0.1, 2.0)
            elif data0 == 11: cym_decay = logmap(value0, 0.2, 1.5)
            elif data0 == 12: cym_tone = logmap(value0, 3000.0, 8000.0)
            elif data0 == 13: hat_level = logmap(value0, 0.1, 2.0)
            elif data0 == 14: ch_decay = logmap(value0, 0.02, 0.15)
            elif data0 == 15: oh_decay = logmap(value0, 0.1, 0.6)

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport, note_map=NOTE_MAP)
    return instrument
