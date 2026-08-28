"""Roland TR-909 Rhythm Composer."""

NAME = 'tr909'
DISPLAY_NAME = 'TR-909'
CATEGORIES = ('Drum',)
VERSION = '0.0.1'
VENDOR = "PyDevices"

MACRO_LABELS = (
    "Level", "Accent", "BD Tune", "BD Attack", "BD Decay", "SD Tune",
    "SD Tone", "SD Snappy", "LT Tune", "MT Tune", "HT Tune", "Tom Decay",
    "Clap/Rim", "CH Decay", "OH Decay", "Cymbal Tune",
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
    0: ("Default", (102, 64, 51, 64, 76, 56, 60, 64, 74, 71, 71, 85, 64, 58,
                 85, 74)),
}

NOTE_MAP = (
    (36, "Bass Drum"),
    (38, "Snare"),
    (37, "Rimshot"),
    (39, "Clap"),
    (41, "Low Tom"),
    (45, "Mid Tom"),
    (48, "Hi Tom"),
    (42, "Closed Hat"),
    (46, "Open Hat"),
    (49, "Crash"),
    (51, "Ride"),
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
SQUARE = make_table([(n, 1.0 / n) for n in range(1, 23, 2)])
NOISE = noise_table(seed=909090)


def create(sample_rate, transport=None):
    SR = sample_rate
    NOISE_HZ = SR / 8192.0
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=2)

    # Master params
    master_level = 0.8
    accent_level = 0.5

    # BD params
    bd_tune = 50.0
    bd_attack = 0.5
    bd_decay = 0.4

    # SD params
    sd_tune = 180.0
    sd_tone = 1500.0
    sd_snappy = 0.5

    # Toms
    lt_tune = 90.0
    mt_tune = 130.0
    ht_tune = 180.0
    tom_decay = 0.4

    # Others
    clap_rim_level = 0.5
    ch_decay = 0.05
    oh_decay = 0.4
    cym_tune = 6000.0

    voices = {}
    serial = 0
    open_hat_keys = []
    MAX_VOICES = 16




    def release_voice(k):
        _support.release_voice(voices, synth, k)


    def steal_oldest():
        _support.steal_oldest(voices, release_voice)


    def trigger_voice(k, notes):
        nonlocal serial
        serial = _support.trigger_voice(voices, synth, serial, MAX_VOICES,
                                        release_voice, k, notes)


    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal master_level, accent_level, bd_tune, bd_attack, bd_decay
        nonlocal sd_tune, sd_tone, sd_snappy, lt_tune, mt_tune, ht_tune, tom_decay
        nonlocal clap_rim_level, ch_decay, oh_decay, cym_tune

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            pitch = data0
            vel = value0
            amp = master_level * (vel + accent_level * (1.0 if vel > 0.8 else 0.0))

            notes_to_play = []

            # BD (35, 36)
            if pitch in (35, 36):
                env = synthio.Envelope(attack_time=0.001, decay_time=bd_decay, release_time=0.05, attack_level=1.0, sustain_level=0.0)
                drop = synthio.LFO(waveform=FALL, once=True, rate=25.0, scale=0.8, interpolate=True)
                lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, bd_tune * 5.0, Q=0.7)
                body = synthio.Note(bd_tune, waveform=SINE, envelope=env, filter=lp, amplitude=amp, bend=drop)

                click_env = synthio.Envelope(attack_time=0.001, decay_time=0.015, release_time=0.01, attack_level=1.0, sustain_level=0.0)
                click_hp = synthio.Biquad(synthio.FilterMode.HIGH_PASS, 4000.0, Q=1.0)
                click = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=click_env, filter=click_hp, amplitude=amp * bd_attack)

                notes_to_play.extend([body, click])

            # SD (38, 40)
            elif pitch in (38, 40):
                body_env = synthio.Envelope(attack_time=0.001, decay_time=0.1, release_time=0.05, attack_level=1.0, sustain_level=0.0)
                drop = synthio.LFO(waveform=FALL, once=True, rate=35.0, scale=0.3, interpolate=True)
                body = synthio.Note(sd_tune, waveform=SINE, envelope=body_env, amplitude=amp*0.8, bend=drop)

                snare_env = synthio.Envelope(attack_time=0.001, decay_time=0.15, release_time=0.1, attack_level=1.0, sustain_level=0.0)
                snare_hp = synthio.Biquad(synthio.FilterMode.HIGH_PASS, sd_tone, Q=1.0)
                snare = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=snare_env, filter=snare_hp, amplitude=amp * sd_snappy)

                notes_to_play.extend([body, snare])

            # Toms (41, 43, 45, 47, 48, 50)
            elif pitch in (41, 43, 45, 47, 48, 50):
                if pitch in (41, 43):
                    tune = lt_tune
                elif pitch in (45, 47):
                    tune = mt_tune
                else:
                    tune = ht_tune

                env = synthio.Envelope(attack_time=0.001, decay_time=tom_decay, release_time=0.1, attack_level=1.0, sustain_level=0.0)
                drop = synthio.LFO(waveform=FALL, once=True, rate=20.0, scale=0.4, interpolate=True)
                note = synthio.Note(tune, waveform=SINE, envelope=env, amplitude=amp, bend=drop)

                noise_env = synthio.Envelope(attack_time=0.001, decay_time=0.05, release_time=0.02, attack_level=1.0, sustain_level=0.0)
                noise_bp = synthio.Biquad(synthio.FilterMode.BAND_PASS, tune * 8.0, Q=1.0)
                noise_click = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=noise_env, filter=noise_bp, amplitude=amp * 0.2)

                notes_to_play.extend([note, noise_click])

            # Hats (42, 44, 46)
            elif pitch in (42, 44, 46):
                is_open = pitch == 46
                if not is_open:
                    for ok in open_hat_keys:
                        release_voice(ok)
                    open_hat_keys.clear()

                env = synthio.Envelope(attack_time=0.001, decay_time=oh_decay if is_open else ch_decay, release_time=0.05, attack_level=1.0, sustain_level=0.0)
                hp = synthio.Biquad(synthio.FilterMode.HIGH_PASS, cym_tune, Q=0.8)
                note = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=env, filter=hp, amplitude=amp * 0.7)
                notes_to_play.append(note)
                if is_open:
                    open_hat_keys.append(k)

            # Cymbals (Crash 49/57, Ride 51/59)
            elif pitch in (49, 51, 57, 59):
                is_ride = pitch in (51, 59)
                decay = 1.5 if is_ride else 0.8
                env = synthio.Envelope(attack_time=0.001, decay_time=decay, release_time=0.3, attack_level=1.0, sustain_level=0.0)
                bp = synthio.Biquad(synthio.FilterMode.BAND_PASS, cym_tune * (1.5 if is_ride else 1.0), Q=0.5)
                hp = synthio.Biquad(synthio.FilterMode.HIGH_PASS, 8000.0, Q=0.7)
                note1 = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=env, filter=bp, amplitude=amp * 0.5)
                note2 = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=env, filter=hp, amplitude=amp * 0.5)
                notes_to_play.extend([note1, note2])

            # Clap (39)
            elif pitch == 39:
                bp = synthio.Biquad(synthio.FilterMode.BAND_PASS, 1200.0, Q=1.0)
                for i, attack in enumerate([0.001, 0.015, 0.03]):
                    env = synthio.Envelope(attack_time=attack, decay_time=0.3, release_time=0.1, attack_level=1.0, sustain_level=0.0)
                    notes_to_play.append(synthio.Note(NOISE_HZ, waveform=NOISE, envelope=env, filter=bp, amplitude=amp * clap_rim_level * (1.0 - i*0.2)))

            # Rimshot (37)
            elif pitch == 37:
                env = synthio.Envelope(attack_time=0.001, decay_time=0.05, release_time=0.02, attack_level=1.0, sustain_level=0.0)
                bp = synthio.Biquad(synthio.FilterMode.BAND_PASS, 1600.0, Q=2.0)
                note1 = synthio.Note(450.0, waveform=TRIANGLE, envelope=env, filter=bp, amplitude=amp * clap_rim_level * 0.5)
                note2 = synthio.Note(1600.0, waveform=TRIANGLE, envelope=env, filter=bp, amplitude=amp * clap_rim_level * 0.5)
                notes_to_play.extend([note1, note2])

            # Fallback (other percussion)
            else:
                env = synthio.Envelope(attack_time=0.001, decay_time=0.1, release_time=0.05, attack_level=1.0, sustain_level=0.0)
                bp = synthio.Biquad(synthio.FilterMode.BAND_PASS, 3000.0, Q=1.0)
                note = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=env, filter=bp, amplitude=amp * 0.5)
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
            elif data0 == 2: bd_tune = logmap(value0, 40.0, 70.0)
            elif data0 == 3: bd_attack = value0
            elif data0 == 4: bd_decay = logmap(value0, 0.1, 1.0)
            elif data0 == 5: sd_tune = logmap(value0, 120.0, 300.0)
            elif data0 == 6: sd_tone = logmap(value0, 800.0, 3000.0)
            elif data0 == 7: sd_snappy = value0
            elif data0 == 8: lt_tune = logmap(value0, 60.0, 120.0)
            elif data0 == 9: mt_tune = logmap(value0, 100.0, 160.0)
            elif data0 == 10: ht_tune = logmap(value0, 140.0, 220.0)
            elif data0 == 11: tom_decay = logmap(value0, 0.1, 0.8)
            elif data0 == 12: clap_rim_level = value0
            elif data0 == 13: ch_decay = logmap(value0, 0.02, 0.15)
            elif data0 == 14: oh_decay = logmap(value0, 0.1, 0.8)
            elif data0 == 15: cym_tune = logmap(value0, 4000.0, 8000.0)

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport, note_map=NOTE_MAP)
    instrument.program_change(0)
    return instrument
