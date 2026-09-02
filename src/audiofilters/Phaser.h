// Ported from CircuitPython's shared-bindings+shared-module/audiofilters/
// Phaser.{h,c} (upstream repo: https://github.com/adafruit/circuitpython,
// MIT). Merged into one header/source pair -- see audiomixer/Mixer.h for
// why this port doesn't keep the shared-bindings/shared-module split.
//
// SPDX-FileCopyrightText: Copyright (c) 2025 Cooper Dalrymple
// SPDX-FileCopyrightText: Copyright (c) 2026 PyDevices
// SPDX-License-Identifier: MIT

#pragma once

#include "py/obj.h"

#include "audiocore/__init__.h"
#include "synthio/__init__.h"
#include "synthio/block.h"

extern const mp_obj_type_t audiofilters_phaser_type;

typedef struct {
    audiosample_base_t base;
    synthio_block_slot_t frequency;
    synthio_block_slot_t feedback;
    synthio_block_slot_t mix;
    uint8_t stages;

    mp_float_t nyquist;

    int8_t *buffer[2];
    uint8_t last_buf_idx;
    uint32_t buffer_len; // max buffer in bytes

    uint8_t *sample_remaining_buffer;
    uint32_t sample_buffer_length;

    bool loop;
    bool more_data;

    int16_t *allpass_buffer;
    int16_t *word_buffer;

    mp_obj_t sample;
} audiofilters_phaser_obj_t;

void common_hal_audiofilters_phaser_construct(audiofilters_phaser_obj_t *self,
    mp_obj_t frequency, mp_obj_t feedback, mp_obj_t mix, uint8_t stages,
    uint32_t buffer_size, uint8_t bits_per_sample, bool samples_signed,
    uint8_t channel_count, uint32_t sample_rate);

void common_hal_audiofilters_phaser_deinit(audiofilters_phaser_obj_t *self);

mp_obj_t common_hal_audiofilters_phaser_get_frequency(audiofilters_phaser_obj_t *self);
void common_hal_audiofilters_phaser_set_frequency(audiofilters_phaser_obj_t *self, mp_obj_t arg);

mp_obj_t common_hal_audiofilters_phaser_get_feedback(audiofilters_phaser_obj_t *self);
void common_hal_audiofilters_phaser_set_feedback(audiofilters_phaser_obj_t *self, mp_obj_t arg);

mp_obj_t common_hal_audiofilters_phaser_get_mix(audiofilters_phaser_obj_t *self);
void common_hal_audiofilters_phaser_set_mix(audiofilters_phaser_obj_t *self, mp_obj_t arg);

uint8_t common_hal_audiofilters_phaser_get_stages(audiofilters_phaser_obj_t *self);
void common_hal_audiofilters_phaser_set_stages(audiofilters_phaser_obj_t *self, uint8_t arg);

bool common_hal_audiofilters_phaser_get_playing(audiofilters_phaser_obj_t *self);
void common_hal_audiofilters_phaser_play(audiofilters_phaser_obj_t *self, mp_obj_t sample, bool loop);
void common_hal_audiofilters_phaser_stop(audiofilters_phaser_obj_t *self);

void audiofilters_phaser_reset_buffer(audiofilters_phaser_obj_t *self,
    bool single_channel_output, uint8_t channel);
audioio_get_buffer_result_t audiofilters_phaser_get_buffer(audiofilters_phaser_obj_t *self,
    bool single_channel_output, uint8_t channel,
    uint8_t **buffer, uint32_t *buffer_length);
