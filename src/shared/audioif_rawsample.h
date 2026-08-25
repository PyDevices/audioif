// Runtime-neutral RawSample state and pull implementation.
// SPDX-License-Identifier: MIT

#pragma once

#include "shared/audioif_sample.h"

typedef struct {
    audioif_sample_info_t *info;
    uint8_t *buffer;
    uint32_t buffer_length;
    uint8_t buffer_index;
    bool deinited;
} audioif_rawsample_state_t;

void audioif_rawsample_construct(audioif_rawsample_state_t *state,
    audioif_sample_info_t *info, uint8_t *buffer, uint32_t len,
    uint8_t bytes_per_sample, bool samples_signed, uint8_t channel_count,
    uint32_t sample_rate, bool single_buffer);
void audioif_rawsample_deinit(audioif_rawsample_state_t *state);
audioif_sample_source_t audioif_rawsample_source(audioif_rawsample_state_t *state);

