"""Roland CR-78 CompuRhythm."""

NAME = 'CR-78'
CATEGORIES = ('Drum',)
VERSION = '0.0.1'
VENDOR = "PyDevices"

MACRO_LABELS = (
    "Level", "Accent", "BD Decay", "BD Pitch", "SD Snappy", "SD Pitch",
    "Rim Level", "Bongo Hi", "Bongo Lo", "Claves Level", "Cowbell Level",
    "Guiro Level", "Tamb Level", "Maracas Level", "Metal Beat", "Hat Tone",
)

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ('Init', (102, 64, 49, 76, 51, 61, 102, 74, 62, 102, 102, 102, 102,
                 102, 102, 78)),
}

NOTE_MAP = (
    (36, "Bass Drum"),
    (38, "Snare"),
    (37, "Rimshot"),
    (42, "Closed Hat"),
    (46, "Open Hat"),
    (49, "Cymbal"),
    (54, "Tambourine"),
    (55, "Metal Beat"),
    (56, "Cowbell"),
    (58, "Guiro"),
    (60, "Bongo Hi"),
    (61, "Bongo Lo"),
    (70, "Maracas"),
    (75, "Claves"),
)

import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, key_of, logmap,
    make_table, noise_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

SINE = make_table(((1, 1.0),))
SQUARE = make_table([(n, 1.0 / n) for n in range(1, 15, 2)])
NOISE = noise_table(seed=13579)


def create(sample_rate, transport=None):
    SR = sample_rate
    NOISE_HZ = SR / 8192.0
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=2)

    # Master params
    master_level = 0.8
    accent_level = 0.5

    # Params
    bd_decay = 0.2
    bd_pitch = 65.0
    sd_snappy = 0.4
    sd_pitch = 240.0
    rim_level = 0.8
    bongo_hi = 450.0
    bongo_lo = 280.0
    claves_level = 0.8
    cowbell_level = 0.8
    guiro_level = 0.8
    tamb_level = 0.8
    maracas_level = 0.8
    metal_beat = 0.8
    hat_tone = 7000.0

    voices = {}
    serial = 0
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
        nonlocal master_level, accent_level, bd_decay, bd_pitch, sd_snappy, sd_pitch
        nonlocal rim_level, bongo_hi, bongo_lo, claves_level, cowbell_level
        nonlocal guiro_level, tamb_level, maracas_level, metal_beat, hat_tone

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            pitch = data0
            vel = value0
            amp = master_level * (vel + accent_level * (1.0 if vel > 0.8 else 0.0))

            notes_to_play = []

            # BD
            if pitch in (35, 36):
                env = synthio.Envelope(attack_time=0.001, decay_time=bd_decay, release_time=0.05, attack_level=1.0, sustain_level=0.0)
                lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, bd_pitch * 2.0, Q=0.8)
                note = synthio.Note(bd_pitch, waveform=SINE, envelope=env, filter=lp, amplitude=amp)
                notes_to_play.append(note)

            # SD
            elif pitch in (38, 40):
                body_env = synthio.Envelope(attack_time=0.001, decay_time=0.08, release_time=0.05, attack_level=1.0, sustain_level=0.0)
                body = synthio.Note(sd_pitch, waveform=SQUARE, envelope=body_env, amplitude=amp*0.5)

                snare_env = synthio.Envelope(attack_time=0.001, decay_time=0.1, release_time=0.05, attack_level=1.0, sustain_level=0.0)
                snare_hp = synthio.Biquad(synthio.FilterMode.HIGH_PASS, 3000.0, Q=1.0)
                snare = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=snare_env, filter=snare_hp, amplitude=amp * sd_snappy)

                notes_to_play.extend([body, snare])

            # Bongos (High 60, Low 61)
            elif pitch in (60, 61):
                tune = bongo_hi if pitch == 60 else bongo_lo
                env = synthio.Envelope(attack_time=0.001, decay_time=0.2, release_time=0.05, attack_level=1.0, sustain_level=0.0)
                note = synthio.Note(tune, waveform=SINE, envelope=env, amplitude=amp)
                notes_to_play.append(note)

            # Rim (37)
            elif pitch == 37:
                env = synthio.Envelope(attack_time=0.001, decay_time=0.02, release_time=0.02, attack_level=1.0, sustain_level=0.0)
                bp = synthio.Biquad(synthio.FilterMode.BAND_PASS, 1200.0, Q=2.0)
                note = synthio.Note(1200.0, waveform=SQUARE, envelope=env, filter=bp, amplitude=amp * rim_level)
                notes_to_play.append(note)

            # Claves (75)
            elif pitch == 75:
                env = synthio.Envelope(attack_time=0.001, decay_time=0.05, release_time=0.02, attack_level=1.0, sustain_level=0.0)
                bp = synthio.Biquad(synthio.FilterMode.BAND_PASS, 2200.0, Q=3.0)
                note = synthio.Note(2200.0, waveform=SINE, envelope=env, filter=bp, amplitude=amp * claves_level)
                notes_to_play.append(note)

            # Cowbell (56)
            elif pitch == 56:
                env = synthio.Envelope(attack_time=0.001, decay_time=0.2, release_time=0.1, attack_level=1.0, sustain_level=0.0)
                bp = synthio.Biquad(synthio.FilterMode.BAND_PASS, 800.0, Q=1.5)
                note = synthio.Note(800.0, waveform=SQUARE, envelope=env, filter=bp, amplitude=amp * cowbell_level)
                notes_to_play.append(note)

            # Guiro (58) - a scraping ratchet, not a single swell: stack short
            # staggered noise clicks so the ridges of the scrape are audible
            elif pitch == 58:
                bp = synthio.Biquad(synthio.FilterMode.BAND_PASS, 3500.0, Q=1.0)
                for i, attack in enumerate((0.001, 0.02, 0.04, 0.06, 0.08)):
                    env = synthio.Envelope(attack_time=attack, decay_time=0.03, release_time=0.02, attack_level=1.0, sustain_level=0.0)
                    notes_to_play.append(synthio.Note(NOISE_HZ, waveform=NOISE, envelope=env, filter=bp, amplitude=amp * guiro_level * (1.0 - i * 0.12)))

            # Tambourine (54)
            elif pitch == 54:
                env = synthio.Envelope(attack_time=0.001, decay_time=0.15, release_time=0.05, attack_level=1.0, sustain_level=0.0)
                hp = synthio.Biquad(synthio.FilterMode.HIGH_PASS, 6000.0, Q=0.8)
                note = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=env, filter=hp, amplitude=amp * tamb_level)
                notes_to_play.append(note)

            # Maracas (70)
            elif pitch == 70:
                env = synthio.Envelope(attack_time=0.001, decay_time=0.05, release_time=0.02, attack_level=1.0, sustain_level=0.0)
                hp = synthio.Biquad(synthio.FilterMode.HIGH_PASS, 5000.0, Q=1.0)
                note = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=env, filter=hp, amplitude=amp * maracas_level)
                notes_to_play.append(note)

            # Metal Beat (e.g. 55)
            elif pitch == 55:
                env = synthio.Envelope(attack_time=0.001, decay_time=0.08, release_time=0.02, attack_level=1.0, sustain_level=0.0)
                hp = synthio.Biquad(synthio.FilterMode.HIGH_PASS, 4000.0, Q=1.5)
                note = synthio.Note(600.0, waveform=SQUARE, envelope=env, filter=hp, amplitude=amp * metal_beat)
                notes_to_play.append(note)

            # Hats / Cymbal (42, 44, 46, 49, 51)
            elif pitch in (42, 44, 46, 49, 51, 57, 59):
                if pitch in (42, 44):
                    decay = 0.05
                elif pitch == 46:
                    decay = 0.3
                else:
                    decay = 0.8
                env = synthio.Envelope(attack_time=0.001, decay_time=decay, release_time=0.1, attack_level=1.0, sustain_level=0.0)
                hp = synthio.Biquad(synthio.FilterMode.HIGH_PASS, hat_tone, Q=0.7)
                note = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=env, filter=hp, amplitude=amp * 0.7)
                notes_to_play.append(note)

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

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: master_level = value0
            elif data0 == 1: accent_level = value0
            elif data0 == 2: bd_decay = logmap(value0, 0.1, 0.6)
            elif data0 == 3: bd_pitch = logmap(value0, 40.0, 90.0)
            elif data0 == 4: sd_snappy = value0
            elif data0 == 5: sd_pitch = logmap(value0, 150.0, 400.0)
            elif data0 == 6: rim_level = value0
            elif data0 == 7: bongo_hi = logmap(value0, 300.0, 600.0)
            elif data0 == 8: bongo_lo = logmap(value0, 200.0, 400.0)
            elif data0 == 9: claves_level = value0
            elif data0 == 10: cowbell_level = value0
            elif data0 == 11: guiro_level = value0
            elif data0 == 12: tamb_level = value0
            elif data0 == 13: maracas_level = value0
            elif data0 == 14: metal_beat = value0
            elif data0 == 15: hat_tone = logmap(value0, 4000.0, 10000.0)

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport, note_map=NOTE_MAP)
    instrument.program_change(0)
    return instrument
