"""Oberheim DMX."""

NAME = 'DMX'
CATEGORIES = ('Drum',)
VERSION = '0.0.1'
VENDOR = "PyDevices"

MACRO_LABELS = (
    "Level", "BD Pitch", "BD Decay", "SD Pitch", "SD Snappy", "Rim Pitch",
    "Clap Decay", "LT Pitch", "MT Pitch", "HT Pitch", "Tambourine",
    "Shaker", "Cowbell", "Cymbal Pitch", "CH Decay", "OH Decay",
)

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ('Init', (102, 64, 67, 56, 76, 80, 89, 84, 97, 84, 102, 102, 68, 56,
                 58, 78)),
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
    (49, "Cymbal"),
    (54, "Tambourine"),
    (56, "Cowbell"),
    (70, "Shaker"),
)

import array
import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, FALL, key_of, logmap,
    make_table, noise_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

def crush_noise(length=8192, seed=1234567, levels=48, hold=3):
    # low-bit-depth, low-sample-rate stair-stepped noise - the DMX's crunchy,
    # gritty sample chip character, distinct from LinnDrum's cleaner samples.
    # sequential LCG state, doesn't vectorize with ulab
    out = array.array("h", bytearray(length * 2))
    state = seed
    step_size = 65536 // levels
    held = 0
    for i in range(length):
        if i % hold == 0:
            state = (state * 1103515245 + 12345) & 0x7FFFFFFF
            raw = ((state >> 15) & 0xFFFF) - 32768
            held = (raw // step_size) * step_size
        out[i] = held
    return out




SINE = make_table(((1, 1.0), (2, 0.1)))
TRIANGLE = make_table([(n, (1.0 / (n*n)) * (-1)**((n-1)//2)) for n in range(1, 11, 2)])
SQUARE = make_table([(n, 1.0 / n) for n in range(1, 15, 2)])
NOISE = noise_table(seed=121212)
GRIT = crush_noise(seed=121212)


def create(sample_rate, transport=None):
    SR = sample_rate
    NOISE_HZ = SR / 8192.0
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=2)

    # Master params
    master_level = 0.8

    # BD
    bd_pitch = 60.0
    bd_decay = 0.3

    # SD
    sd_pitch = 180.0
    sd_snappy = 0.6

    # Rim
    rim_pitch = 1000.0

    # Clap
    clap_decay = 0.35

    # Toms
    lt_pitch = 100.0
    mt_pitch = 150.0
    ht_pitch = 200.0

    # Perc
    tamb_level = 0.8
    shaker_level = 0.8
    cowbell_pitch = 800.0

    # Hats/Cymbal
    cymbal_pitch = 6000.0
    ch_decay = 0.05
    oh_decay = 0.3

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
        nonlocal master_level, bd_pitch, bd_decay, sd_pitch, sd_snappy, rim_pitch, clap_decay
        nonlocal lt_pitch, mt_pitch, ht_pitch, tamb_level, shaker_level, cowbell_pitch
        nonlocal cymbal_pitch, ch_decay, oh_decay

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            pitch = data0
            amp = master_level * value0

            notes_to_play = []

            # BD (35, 36) - sampled, not a swept VCO: tone plus a gritty low-bit
            # transient instead of an 808-style pitch drop
            if pitch in (35, 36):
                env = synthio.Envelope(attack_time=0.001, decay_time=bd_decay, release_time=0.05, attack_level=1.0, sustain_level=0.0)
                lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, bd_pitch * 3.0, Q=0.8)
                body = synthio.Note(bd_pitch, waveform=SINE, envelope=env, filter=lp, amplitude=amp)
                grit_env = synthio.Envelope(attack_time=0.001, decay_time=0.04, release_time=0.02, attack_level=1.0, sustain_level=0.0)
                grit_lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, bd_pitch * 7.0, Q=0.7)
                grit = synthio.Note(NOISE_HZ, waveform=GRIT, envelope=grit_env, filter=grit_lp, amplitude=amp * 0.4)
                notes_to_play.extend([body, grit])

            # SD (38, 40) - crunchy low-bit-depth snap is the DMX's signature
            elif pitch in (38, 40):
                body_env = synthio.Envelope(attack_time=0.001, decay_time=0.1, release_time=0.05, attack_level=1.0, sustain_level=0.0)
                body = synthio.Note(sd_pitch, waveform=TRIANGLE, envelope=body_env, amplitude=amp * 0.7)

                snare_env = synthio.Envelope(attack_time=0.001, decay_time=0.15, release_time=0.05, attack_level=1.0, sustain_level=0.0)
                snare_hp = synthio.Biquad(synthio.FilterMode.HIGH_PASS, 1800.0, Q=1.0)
                snare = synthio.Note(NOISE_HZ, waveform=GRIT, envelope=snare_env, filter=snare_hp, amplitude=amp * sd_snappy)

                notes_to_play.extend([body, snare])

            # Rimshot (37)
            elif pitch == 37:
                env = synthio.Envelope(attack_time=0.001, decay_time=0.03, release_time=0.01, attack_level=1.0, sustain_level=0.0)
                bp = synthio.Biquad(synthio.FilterMode.BAND_PASS, rim_pitch, Q=1.5)
                note = synthio.Note(rim_pitch, waveform=SQUARE, envelope=env, filter=bp, amplitude=amp)
                notes_to_play.append(note)

            # Clap (39)
            elif pitch == 39:
                bp = synthio.Biquad(synthio.FilterMode.BAND_PASS, 1200.0, Q=1.0)
                for i, attack in enumerate([0.001, 0.015, 0.03]):
                    env = synthio.Envelope(attack_time=attack, decay_time=clap_decay, release_time=0.1, attack_level=1.0, sustain_level=0.0)
                    notes_to_play.append(synthio.Note(NOISE_HZ, waveform=NOISE, envelope=env, filter=bp, amplitude=amp * (1.0 - i*0.2)))

            # Toms (41, 43, 45, 47, 48, 50)
            elif pitch in (41, 43, 45, 47, 48, 50):
                if pitch in (41, 43):
                    tune = lt_pitch
                elif pitch in (45, 47):
                    tune = mt_pitch
                else:
                    tune = ht_pitch

                env = synthio.Envelope(attack_time=0.001, decay_time=0.3, release_time=0.1, attack_level=1.0, sustain_level=0.0)
                drop = synthio.LFO(waveform=FALL, once=True, rate=20.0, scale=0.15, interpolate=True)
                note = synthio.Note(tune, waveform=TRIANGLE, envelope=env, amplitude=amp, bend=drop)
                notes_to_play.append(note)

            # Cowbell (56)
            elif pitch == 56:
                env = synthio.Envelope(attack_time=0.001, decay_time=0.25, release_time=0.1, attack_level=1.0, sustain_level=0.0)
                bp = synthio.Biquad(synthio.FilterMode.BAND_PASS, cowbell_pitch, Q=1.5)
                note = synthio.Note(cowbell_pitch, waveform=SQUARE, envelope=env, filter=bp, amplitude=amp * 0.8)
                note2 = synthio.Note(cowbell_pitch * 1.4, waveform=SQUARE, envelope=env, filter=bp, amplitude=amp * 0.6)
                notes_to_play.extend([note, note2])

            # Tambourine (54) & Shaker (70, 82)
            elif pitch in (54, 70, 82):
                is_tamb = pitch == 54
                a = amp * (tamb_level if is_tamb else shaker_level)
                env = synthio.Envelope(attack_time=0.001, decay_time=0.1 if is_tamb else 0.05, release_time=0.05, attack_level=1.0, sustain_level=0.0)
                hp = synthio.Biquad(synthio.FilterMode.HIGH_PASS, 6000.0 if is_tamb else 7000.0, Q=0.8)
                note = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=env, filter=hp, amplitude=a)
                notes_to_play.append(note)

            # Hats (42, 44, 46)
            elif pitch in (42, 44, 46):
                is_open = pitch == 46
                if not is_open:
                    for ok in open_hat_keys:
                        release_voice(ok)
                    open_hat_keys.clear()

                env = synthio.Envelope(attack_time=0.001, decay_time=oh_decay if is_open else ch_decay, release_time=0.05, attack_level=1.0, sustain_level=0.0)
                hp = synthio.Biquad(synthio.FilterMode.HIGH_PASS, cymbal_pitch, Q=0.8)
                note = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=env, filter=hp, amplitude=amp * 0.7)
                notes_to_play.append(note)
                if is_open:
                    open_hat_keys.append(k)

            # Cymbals (49, 51, 57, 59)
            elif pitch in (49, 51, 57, 59):
                env = synthio.Envelope(attack_time=0.001, decay_time=1.0, release_time=0.3, attack_level=1.0, sustain_level=0.0)
                bp = synthio.Biquad(synthio.FilterMode.BAND_PASS, cymbal_pitch * 0.8, Q=0.5)
                hp = synthio.Biquad(synthio.FilterMode.HIGH_PASS, cymbal_pitch * 1.2, Q=0.7)
                note1 = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=env, filter=bp, amplitude=amp * 0.5)
                note2 = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=env, filter=hp, amplitude=amp * 0.5)
                notes_to_play.extend([note1, note2])

            # Fallback
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
            elif data0 == 1: bd_pitch = logmap(value0, 40.0, 90.0)
            elif data0 == 2: bd_decay = logmap(value0, 0.1, 0.8)
            elif data0 == 3: sd_pitch = logmap(value0, 120.0, 300.0)
            elif data0 == 4: sd_snappy = value0
            elif data0 == 5: rim_pitch = logmap(value0, 500.0, 1500.0)
            elif data0 == 6: clap_decay = logmap(value0, 0.1, 0.6)
            elif data0 == 7: lt_pitch = logmap(value0, 60.0, 130.0)
            elif data0 == 8: mt_pitch = logmap(value0, 100.0, 170.0)
            elif data0 == 9: ht_pitch = logmap(value0, 140.0, 240.0)
            elif data0 == 10: tamb_level = value0
            elif data0 == 11: shaker_level = value0
            elif data0 == 12: cowbell_pitch = logmap(value0, 500.0, 1200.0)
            elif data0 == 13: cymbal_pitch = logmap(value0, 4000.0, 10000.0)
            elif data0 == 14: ch_decay = logmap(value0, 0.02, 0.15)
            elif data0 == 15: oh_decay = logmap(value0, 0.1, 0.6)

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport, note_map=NOTE_MAP)
    instrument.program_change(0)
    return instrument
