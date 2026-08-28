"""Plucked string, Karplus-Strong style."""

NAME = 'karplus'
DISPLAY_NAME = 'Karplus-Strong'
CATEGORIES = ('Synth',)
VERSION = '0.0.1'
VENDOR = "PyDevices"

MACRO_LABELS = (
    "Volume", "Pluck Position", "String Damping", "Body Resonance",
    "Pick Hardness", "Decay", "Master Tune",
)
MACRO_MODES = {
    0: "UNIPOLAR",
    1: "UNIPOLAR",
    2: "UNIPOLAR",
    3: "UNIPOLAR",
    4: "UNIPOLAR",
    5: "UNIPOLAR",
    6: "BIPOLAR",
}

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ("Default", (102, 64, 64, 64, 64, 48, 64)),
}

import array
import math
import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, key_of, noise_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

NOISE = noise_table(seed=1234)

KS_TABLE_LEN = 8192 # bounds the per-note-on cost of the algorithm below


def create(sample_rate, channel_count=2, transport=None):
    SR = sample_rate
    NOISE_HZ = SR / 8192.0
    def karplus_strong_table(hz, damping, pluck_pos, seed=1234):
        # The real Karplus-Strong algorithm: fill a delay line (length = one
        # period at this pitch) with noise, then repeatedly read it back and
        # feed each sample into a leaky lowpass (average with the previous
        # sample) before writing it back into the same slot. High harmonics
        # get averaged away faster than the fundamental every time around the
        # loop, which is what produces the natural pitched pluck-and-decay -
        # a filtered noise burst alone can't reproduce that decay curve because
        # it never actually loops back through itself.
        delay_len = max(4, min(KS_TABLE_LEN, int(SR / hz)))
        state = seed
        buf = [0.0] * delay_len
        for i in range(delay_len):
            state = (state * 1103515245 + 12345) & 0x7FFFFFFF
            buf[i] = (((state >> 15) & 0xFFFF) - 32768) / 32768.0
        # Pluck position: subtracting a delayed copy of the burst from itself
        # is the classic extended-KS "pick position" filter - it carves a comb
        # notch wherever the string was plucked, same as a real string being
        # picked nearer the bridge vs. the middle. Read from a separate copy:
        # reading buf itself while writing it means buf[i - p] is already the
        # once-subtracted value for every i >= p (i - p < i), so the filter
        # compounds into an unintended recursive comb instead of the single
        # clean +/-1 notch described above.
        src = list(buf)
        p = 1 + int(pluck_pos * (delay_len - 2))
        for i in range(delay_len):
            buf[i] -= 0.5 * src[i - p]
        fb = 0.90 + damping * 0.09 # feedback loss per lap; closer to 1 rings longer
        # The pluck-position comb above subtracts each sample from one already
        # updated earlier in the same pass (i - p < i whenever i >= p), so it
        # compounds rather than staying a clean +/-1 FIR notch - real output
        # can run well past unit amplitude (peaks of 1.3-1.4x measured). A
        # fixed *32000 scale with a hard clamp baked genuine digital clipping
        # into the wavetable at every pitch, damping and pluck-position
        # combination, which is why no macro setting ever sounded clean: none
        # of them touch this. Render to floats first and normalize to the
        # loop's own peak, the same way every other instrument's make_table
        # does, instead of assuming the algorithm stays within +/-1.
        vals = [0.0] * KS_TABLE_LEN
        idx = 0
        prev = buf[0]
        peak = 0.0
        for i in range(KS_TABLE_LEN):
            cur = buf[idx]
            avg = (cur + prev) * 0.5 * fb
            buf[idx] = avg
            vals[i] = avg
            a = avg if avg >= 0.0 else -avg
            if a > peak:
                peak = a
            prev = cur
            idx += 1
            if idx >= delay_len:
                idx = 0
        if peak <= 0.0:
            peak = 1.0
        scale = 32000.0 / peak
        out = array.array("h", bytearray(KS_TABLE_LEN * 2))
        for i in range(KS_TABLE_LEN):
            out[i] = int(vals[i] * scale)

        # Which lap to loop, for the caller to mark as the sustain via
        # waveform_loop_start/end (see the note in handle_event on why the
        # whole table can't just be looped as-is). Pick the LATEST lap that
        # still stays safely above int16's noise floor, rather than always
        # the table's final lap: fb decays every lap, and a short delay_len
        # fits far more laps into the fixed KS_TABLE_LEN budget than a long
        # one (182 laps at a high pitch vs 11 at a low one), so the same fb
        # that leaves plenty of headroom for a low note can decay a high
        # note's last lap to exact silence before the loop ever reaches it.
        laps_available = KS_TABLE_LEN // delay_len
        settle_laps = laps_available - 1
        if 0.0 < fb < 1.0:
            headroom_laps = int(math.log(1.0 / 2000.0) / math.log(fb))
            if headroom_laps < settle_laps:
                settle_laps = headroom_laps
        if settle_laps < 0:
            settle_laps = 0
        loop_start = settle_laps * delay_len
        return out, loop_start, loop_start + delay_len
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=channel_count)

    # Macros
    volume = 0.8
    pluck_pos = 0.5 # where along the string it's plucked (comb-filters the burst)
    damping = 0.5 # how fast the delay loop's feedback dies out
    body_res = 0.5
    pick_hard = 0.5
    decay_time = 2.0
    master_tune = 1.0

    voices = {}
    serial = 0
    MAX_VOICES = 6


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, pluck_pos, damping, body_res, pick_hard, decay_time, master_tune
        nonlocal serial

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            release_voice(k)
            if len(voices) >= MAX_VOICES:
                steal_oldest()

            hz = synthio.midi_to_hz(data0 + value1) * master_tune
            amp = volume * value0

            # 1. The string itself: a genuine Karplus-Strong delay/feedback
            # loop rendered into a table, so the ring is real comb-filtered
            # decay, not a static harmonic wavetable
            ks_wave, ks_loop_start, ks_loop_end = karplus_strong_table(hz, damping, pluck_pos)
            env_body = synthio.Envelope(attack_time=0.001, decay_time=decay_time, release_time=0.3, attack_level=1.0, sustain_level=0.0)
            lp_body = synthio.Biquad(synthio.FilterMode.LOW_PASS, 400.0 + body_res * 3000.0, Q=1.0 + body_res * 2.0)

            # 2. The pick/strike transient (short noise burst, harder pick = brighter)
            env_pick = synthio.Envelope(attack_time=0.001, decay_time=0.02 + pluck_pos * 0.05, release_time=0.01, attack_level=1.0, sustain_level=0.0)
            hp_pick = synthio.Biquad(synthio.FilterMode.HIGH_PASS, 1000.0 + pick_hard * 4000.0, Q=0.5)

            notes = []
            # synthio always plays a Note's waveform as if the ENTIRE buffer
            # were one cycle at hz (dds_rate is proportional to hz * (loop_end
            # - loop_start), full length by default). KS_TABLE_LEN packs many
            # decaying laps of a delay_len-sample period into one 8192-sample
            # buffer, so left at the default loop bounds the whole buffer got
            # squeezed into one period: measured 5.8x the requested pitch and
            # 97% of the energy off the requested note's own harmonic series -
            # a real, inharmonic "ringing" no macro could ever reach, since
            # none of them touch table length. loop_start/loop_end instead
            # mark one settled lap - by construction one true period of the
            # string - as the loop; everything before it plays once, as the
            # decaying attack transient, at the correct real-time rate.
            notes.append(synthio.Note(hz, waveform=ks_wave, envelope=env_body, filter=lp_body, amplitude=amp * 0.8,
                                      waveform_loop_start=ks_loop_start,
                                      waveform_loop_end=ks_loop_end))
            if pick_hard > 0.01:
                notes.append(synthio.Note(NOISE_HZ, waveform=NOISE, envelope=env_pick, filter=hp_pick, amplitude=amp * pick_hard * 0.3))

            serial += 1
            voices[k] = (tuple(notes), serial)
            for n in notes:
                synth.press(n)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: pluck_pos = value0
            elif data0 == 2: damping = value0
            elif data0 == 3: body_res = value0
            elif data0 == 4: pick_hard = value0
            elif data0 == 5: decay_time = 0.5 + value0 * 4.0
            elif data0 == 6: master_tune = 0.95 + value0 * 0.1

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    return instrument
