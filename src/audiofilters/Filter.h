// Ported from CircuitPython's shared-bindings+shared-module/audiofilters/
// Filter.{h,c} (upstream repo: https://github.com/adafruit/circuitpython,
// MIT). Merged into one header/source pair -- see audiomixer/Mixer.h for
// why this port doesn't keep the shared-bindings/shared-module split.
//
// SPDX-FileCopyrightText: Copyright (c) 2024 Cooper Dalrymple
// SPDX-FileCopyrightText: Copyright (c) 2026 PyDevices
// SPDX-License-Identifier: MIT

#pragma once

#include "py/obj.h"

#include "audiocore/__init__.h"
#include "synthio/Biquad.h"
#include "synthio/__init__.h"
#include "synthio/block.h"

extern const mp_obj_type_t audiofilters_filter_type;

typedef struct {
    audiosample_base_t base;
    mp_obj_t filter;
    synthio_block_slot_t mix;

    mp_obj_t *filter_objs;
    size_t filter_states_len;
    biquad_filter_state *filter_states;

    int8_t *buffer[2];
    uint8_t last_buf_idx;
    uint32_t buffer_len; // max buffer in bytes

    uint8_t *sample_remaining_buffer;
    uint32_t sample_buffer_length;

    int32_t *filter_buffer;

    bool loop;
    bool more_data;

    mp_obj_t sample;
} audiofilters_filter_obj_t;

void common_hal_audiofilters_filter_construct(audiofilters_filter_obj_t *self,
    mp_obj_t filter, mp_obj_t mix,
    uint32_t buffer_size, uint8_t bits_per_sample, bool samples_signed,
    uint8_t channel_count, uint32_t sample_rate);

void common_hal_audiofilters_filter_deinit(audiofilters_filter_obj_t *self);

mp_obj_t common_hal_audiofilters_filter_get_filter(audiofilters_filter_obj_t *self);
void common_hal_audiofilters_filter_set_filter(audiofilters_filter_obj_t *self, mp_obj_t arg);

mp_obj_t common_hal_audiofilters_filter_get_mix(audiofilters_filter_obj_t *self);
void common_hal_audiofilters_filter_set_mix(audiofilters_filter_obj_t *self, mp_obj_t arg);

bool common_hal_audiofilters_filter_get_playing(audiofilters_filter_obj_t *self);
void common_hal_audiofilters_filter_play(audiofilters_filter_obj_t *self, mp_obj_t sample, bool loop);
void common_hal_audiofilters_filter_stop(audiofilters_filter_obj_t *self);

void audiofilters_filter_reset_buffer(audiofilters_filter_obj_t *self,
    bool single_channel_output, uint8_t channel);
audioio_get_buffer_result_t audiofilters_filter_get_buffer(audiofilters_filter_obj_t *self,
    bool single_channel_output, uint8_t channel,
    uint8_t **buffer, uint32_t *buffer_length);
