// Ported from CircuitPython's shared-bindings+shared-module/audiofilters/
// Distortion.{h,c} (upstream repo: https://github.com/adafruit/circuitpython,
// MIT). Merged into one header/source pair -- see audiomixer/Mixer.h for
// why this port doesn't keep the shared-bindings/shared-module split.
//
// SPDX-License-Identifier: MIT

#pragma once

#include "py/obj.h"

#include "audiocore/__init__.h"
#include "synthio/block.h"

typedef enum {
    DISTORTION_MODE_CLIP,
    DISTORTION_MODE_LOFI,
    DISTORTION_MODE_OVERDRIVE,
    DISTORTION_MODE_WAVESHAPE,
} audiofilters_distortion_mode;

extern const mp_obj_type_t audiofilters_distortion_type;
extern const mp_obj_type_t audiofilters_distortion_mode_type;

typedef struct {
    audiosample_base_t base;
    synthio_block_slot_t drive;
    synthio_block_slot_t pre_gain;
    synthio_block_slot_t post_gain;
    audiofilters_distortion_mode mode;
    bool soft_clip;
    synthio_block_slot_t mix;

    int8_t *buffer[2];
    uint8_t last_buf_idx;
    uint32_t buffer_len; // max buffer in bytes

    uint8_t *sample_remaining_buffer;
    uint32_t sample_buffer_length;

    bool loop;
    bool more_data;

    mp_obj_t sample;
} audiofilters_distortion_obj_t;

void common_hal_audiofilters_distortion_construct(audiofilters_distortion_obj_t *self,
    mp_obj_t drive, mp_obj_t pre_gain, mp_obj_t post_gain,
    audiofilters_distortion_mode mode, bool soft_clip, mp_obj_t mix,
    uint32_t buffer_size, uint8_t bits_per_sample, bool samples_signed,
    uint8_t channel_count, uint32_t sample_rate);

void common_hal_audiofilters_distortion_deinit(audiofilters_distortion_obj_t *self);

mp_obj_t common_hal_audiofilters_distortion_get_drive(audiofilters_distortion_obj_t *self);
void common_hal_audiofilters_distortion_set_drive(audiofilters_distortion_obj_t *self, mp_obj_t arg);

mp_obj_t common_hal_audiofilters_distortion_get_pre_gain(audiofilters_distortion_obj_t *self);
void common_hal_audiofilters_distortion_set_pre_gain(audiofilters_distortion_obj_t *self, mp_obj_t arg);

mp_obj_t common_hal_audiofilters_distortion_get_post_gain(audiofilters_distortion_obj_t *self);
void common_hal_audiofilters_distortion_set_post_gain(audiofilters_distortion_obj_t *self, mp_obj_t arg);

audiofilters_distortion_mode common_hal_audiofilters_distortion_get_mode(audiofilters_distortion_obj_t *self);
void common_hal_audiofilters_distortion_set_mode(audiofilters_distortion_obj_t *self, audiofilters_distortion_mode mode);

bool common_hal_audiofilters_distortion_get_soft_clip(audiofilters_distortion_obj_t *self);
void common_hal_audiofilters_distortion_set_soft_clip(audiofilters_distortion_obj_t *self, bool soft_clip);

mp_obj_t common_hal_audiofilters_distortion_get_mix(audiofilters_distortion_obj_t *self);
void common_hal_audiofilters_distortion_set_mix(audiofilters_distortion_obj_t *self, mp_obj_t arg);

bool common_hal_audiofilters_distortion_get_playing(audiofilters_distortion_obj_t *self);
void common_hal_audiofilters_distortion_play(audiofilters_distortion_obj_t *self, mp_obj_t sample, bool loop);
void common_hal_audiofilters_distortion_stop(audiofilters_distortion_obj_t *self);

void audiofilters_distortion_reset_buffer(audiofilters_distortion_obj_t *self,
    bool single_channel_output, uint8_t channel);
audioio_get_buffer_result_t audiofilters_distortion_get_buffer(audiofilters_distortion_obj_t *self,
    bool single_channel_output, uint8_t channel,
    uint8_t **buffer, uint32_t *buffer_length);
