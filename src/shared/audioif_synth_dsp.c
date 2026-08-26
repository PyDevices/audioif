// SPDX-License-Identifier: MIT

#include "shared/audioif_synth_dsp.h"

static const uint16_t pitch_bend_table[] = {
    0, 1948, 4013, 6200, 8517, 10972, 13573,
    16329, 19248, 22341, 25618, 29090, 32768
};

int16_t audioif_sat16(int32_t value, int right_shift) {
    if (value < 0) {
        value += ~(0xFFFFFFFFUL << right_shift);
    }
    value >>= right_shift;
    if (value > 32767) return 32767;
    if (value < -32768) return -32768;
    return (int16_t)value;
}

int16_t audioif_mix_down_sample(int32_t sample, int32_t scale,
    int32_t range_low, int32_t range_high) {
    if (sample < range_low) {
        sample = (((sample - range_low) * scale) >> 16) + range_low;
    } else if (sample > range_high) {
        sample = (((sample - range_high) * scale) >> 16) + range_high;
    }
    return (int16_t)sample;
}

bool audioif_oscillator_fill(int32_t *output, const int16_t *waveform,
    uint32_t waveform_start, uint32_t waveform_end, uint32_t dds_rate,
    uint32_t *accumulator, uint16_t duration, uint8_t frequency_shift) {
    uint32_t offset = waveform_start << frequency_shift;
    uint32_t limit = waveform_end << frequency_shift;
    uint32_t span = limit - offset;
    uint32_t accum = *accumulator;
    if (dds_rate > limit / 2) return false;
    // Deviation from CircuitPython: it wraps on `accum > limit`, which lets an
    // accumulator landing exactly on the loop end index waveform[waveform_end]
    // - one past the samples it may read, and off the end of the buffer
    // entirely for a note looping the whole waveform. Any table advancing an
    // exact number of samples per frame hits it, so a render's output depended
    // on whatever the allocator had left after the array. The playable index
    // range is [waveform_start, waveform_end), so wrap on `>=`.
    // See docs/upstream-diff.md.
    if (accum >= limit) accum = offset + (accum - offset) % span;

    for (uint16_t i = 0; i < duration; i++) {
        accum += dds_rate;
        if (accum >= limit) accum -= span;
        output[i] = waveform[accum >> frequency_shift];
    }
    *accumulator = accum;
    return true;
}

void audioif_sum_with_loudness(int32_t *output, const int32_t *voice,
    const int16_t loudness[2], size_t duration, uint8_t channel_count) {
    if (channel_count == 1) {
        for (size_t i = 0; i < duration; i++) {
            *output++ += audioif_sat16(*voice++ * loudness[0], 16);
        }
    } else {
        for (size_t i = 0; i < duration; i++) {
            *output++ += audioif_sat16(*voice * loudness[0], 16);
            *output++ += audioif_sat16(*voice++ * loudness[1], 16);
        }
    }
}

uint32_t audioif_pitch_bend(uint32_t frequency_scaled, int32_t bend_value) {
    int octave = bend_value >> 15;
    bend_value &= 0x7fff;
    uint32_t bend_value_semitone = (uint32_t)bend_value * 24;
    uint32_t semitone = bend_value_semitone >> 16;
    uint32_t fractone = bend_value_semitone & 0xffff;
    uint32_t low = pitch_bend_table[semitone];
    uint32_t high = pitch_bend_table[semitone + 1];
    uint32_t factor = ((low * (65535 - fractone) + high * fractone) >> 16) + 32768;
    return (uint32_t)((frequency_scaled * (uint64_t)factor) >> (15 - octave));
}
