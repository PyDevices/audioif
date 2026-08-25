// Ported from CircuitPython's shared-bindings+shared-module/audiodelays/
// Chorus.{h,c} (upstream repo: https://github.com/adafruit/circuitpython,
// MIT). Merged into one header/source pair -- see audiomixer/Mixer.h for
// why this port doesn't keep the shared-bindings/shared-module split.
//
// SPDX-License-Identifier: MIT

#pragma once

#include "py/obj.h"

#include "audiocore/__init__.h"
#include "synthio/block.h"

extern const mp_obj_type_t audiodelays_chorus_type;

typedef struct {
    audiosample_base_t base;
    uint32_t max_delay_ms;
    synthio_block_slot_t delay_ms;
    mp_float_t current_delay_ms;
    mp_float_t sample_ms;
    synthio_block_slot_t voices;
    synthio_block_slot_t mix;

    int8_t *buffer[2];
    uint8_t last_buf_idx;
    uint32_t buffer_len; // max buffer in bytes

    uint8_t *sample_remaining_buffer;
    uint32_t sample_buffer_length;

    bool loop;
    bool more_data;

    int8_t *chorus_buffer;
    uint32_t chorus_buffer_len; // bytes
    uint32_t max_chorus_buffer_len; // bytes

    uint32_t chorus_buffer_pos; // words

    mp_obj_t sample;
} audiodelays_chorus_obj_t;

void common_hal_audiodelays_chorus_construct(audiodelays_chorus_obj_t *self, uint32_t max_delay_ms,
    mp_obj_t delay_ms, mp_obj_t voices, mp_obj_t mix,
    uint32_t buffer_size, uint8_t bits_per_sample,
    bool samples_signed, uint8_t channel_count, uint32_t sample_rate);

void common_hal_audiodelays_chorus_deinit(audiodelays_chorus_obj_t *self);
bool common_hal_audiodelays_chorus_deinited(audiodelays_chorus_obj_t *self);

mp_obj_t common_hal_audiodelays_chorus_get_delay_ms(audiodelays_chorus_obj_t *self);
void common_hal_audiodelays_chorus_set_delay_ms(audiodelays_chorus_obj_t *self, mp_obj_t delay_ms);

mp_obj_t common_hal_audiodelays_chorus_get_voices(audiodelays_chorus_obj_t *self);
void common_hal_audiodelays_chorus_set_voices(audiodelays_chorus_obj_t *self, mp_obj_t voices);

mp_obj_t common_hal_audiodelays_chorus_get_mix(audiodelays_chorus_obj_t *self);
void common_hal_audiodelays_chorus_set_mix(audiodelays_chorus_obj_t *self, mp_obj_t arg);

bool common_hal_audiodelays_chorus_get_playing(audiodelays_chorus_obj_t *self);
void common_hal_audiodelays_chorus_play(audiodelays_chorus_obj_t *self, mp_obj_t sample, bool loop);
void common_hal_audiodelays_chorus_stop(audiodelays_chorus_obj_t *self);

void chorus_recalculate_delay(audiodelays_chorus_obj_t *self, mp_float_t f_delay_ms);

void audiodelays_chorus_reset_buffer(audiodelays_chorus_obj_t *self,
    bool single_channel_output, uint8_t channel);
audioio_get_buffer_result_t audiodelays_chorus_get_buffer(audiodelays_chorus_obj_t *self,
    bool single_channel_output, uint8_t channel,
    uint8_t **buffer, uint32_t *buffer_length);
