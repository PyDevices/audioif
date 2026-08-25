// Ported from CircuitPython's shared-bindings+shared-module/audiodelays/
// Echo.{h,c} (upstream repo: https://github.com/adafruit/circuitpython,
// MIT). Merged into one header/source pair -- see audiomixer/Mixer.h for
// why this port doesn't keep the shared-bindings/shared-module split.
//
// SPDX-License-Identifier: MIT

#pragma once

#include "py/obj.h"

#include "audiocore/__init__.h"
#include "synthio/__init__.h"
#include "synthio/block.h"

extern const mp_obj_type_t audiodelays_echo_type;

typedef struct {
    audiosample_base_t base;
    uint32_t max_delay_ms;
    synthio_block_slot_t delay_ms;
    mp_float_t current_delay_ms;
    mp_float_t sample_ms;
    synthio_block_slot_t decay;
    synthio_block_slot_t mix;

    int8_t *buffer[2];
    uint8_t last_buf_idx;
    uint32_t buffer_len; // max buffer in bytes

    uint8_t *sample_remaining_buffer;
    uint32_t sample_buffer_length;

    bool loop;
    bool more_data;
    bool freq_shift; // does the echo shift frequencies if delay changes

    int8_t *echo_buffer;
    uint32_t echo_buffer_len; // bytes
    uint32_t max_echo_buffer_len; // bytes

    uint32_t echo_buffer_left_pos; // words (<< 8 when freq_shift=True)
    uint32_t echo_buffer_right_pos; // words (<< 8 when freq_shift=True)
    uint32_t echo_buffer_rate; // words << 8

    mp_obj_t sample;
} audiodelays_echo_obj_t;

void common_hal_audiodelays_echo_construct(audiodelays_echo_obj_t *self, uint32_t max_delay_ms,
    mp_obj_t delay_ms, mp_obj_t decay, mp_obj_t mix,
    uint32_t buffer_size, uint8_t bits_per_sample, bool samples_signed,
    uint8_t channel_count, uint32_t sample_rate, bool freq_shift);

void common_hal_audiodelays_echo_deinit(audiodelays_echo_obj_t *self);

mp_obj_t common_hal_audiodelays_echo_get_delay_ms(audiodelays_echo_obj_t *self);
void common_hal_audiodelays_echo_set_delay_ms(audiodelays_echo_obj_t *self, mp_obj_t delay_ms);

bool common_hal_audiodelays_echo_get_freq_shift(audiodelays_echo_obj_t *self);
void common_hal_audiodelays_echo_set_freq_shift(audiodelays_echo_obj_t *self, bool freq_shift);

mp_obj_t common_hal_audiodelays_echo_get_decay(audiodelays_echo_obj_t *self);
void common_hal_audiodelays_echo_set_decay(audiodelays_echo_obj_t *self, mp_obj_t decay);

mp_obj_t common_hal_audiodelays_echo_get_mix(audiodelays_echo_obj_t *self);
void common_hal_audiodelays_echo_set_mix(audiodelays_echo_obj_t *self, mp_obj_t arg);

bool common_hal_audiodelays_echo_get_playing(audiodelays_echo_obj_t *self);
void common_hal_audiodelays_echo_play(audiodelays_echo_obj_t *self, mp_obj_t sample, bool loop);
void common_hal_audiodelays_echo_stop(audiodelays_echo_obj_t *self);

void recalculate_delay(audiodelays_echo_obj_t *self, mp_float_t f_delay_ms);

void audiodelays_echo_reset_buffer(audiodelays_echo_obj_t *self,
    bool single_channel_output, uint8_t channel);
audioio_get_buffer_result_t audiodelays_echo_get_buffer(audiodelays_echo_obj_t *self,
    bool single_channel_output, uint8_t channel,
    uint8_t **buffer, uint32_t *buffer_length);
