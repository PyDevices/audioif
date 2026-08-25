// Runtime-neutral fixed-point synthesis primitives.
// SPDX-License-Identifier: MIT

#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

int16_t audioif_sat16(int32_t value, int right_shift);
int16_t audioif_mix_down_sample(int32_t sample, int32_t scale,
    int32_t range_low, int32_t range_high);
bool audioif_oscillator_fill(int32_t *output, const int16_t *waveform,
    uint32_t waveform_start, uint32_t waveform_end, uint32_t dds_rate,
    uint32_t *accumulator, uint16_t duration, uint8_t frequency_shift);
void audioif_sum_with_loudness(int32_t *output, const int32_t *voice,
    const int16_t loudness[2], size_t duration, uint8_t channel_count);
uint32_t audioif_pitch_bend(uint32_t frequency_scaled, int32_t bend_value);
