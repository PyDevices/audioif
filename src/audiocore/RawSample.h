// Ported from CircuitPython's shared-bindings/audiocore/RawSample.h and
// shared-module/audiocore/RawSample.h (upstream repo:
// https://github.com/adafruit/circuitpython, MIT), merged into one file
// (this port doesn't keep CP's shared-bindings/shared-module split).
//
// SPDX-License-Identifier: MIT

#pragma once

#include "py/obj.h"

#include "audiocore/__init__.h"

typedef struct {
    audiosample_base_t base;
    uint8_t *buffer;
    uint8_t buffer_index;
} audioio_rawsample_obj_t;

extern const mp_obj_type_t audioio_rawsample_type;

void common_hal_audioio_rawsample_construct(audioio_rawsample_obj_t *self,
    uint8_t *buffer, uint32_t len, uint8_t bytes_per_sample, bool samples_signed,
    uint8_t channel_count, uint32_t sample_rate, bool single_buffer);

void common_hal_audioio_rawsample_deinit(audioio_rawsample_obj_t *self);

// These are not available from Python because it may be called in an interrupt.
void audioio_rawsample_reset_buffer(audioio_rawsample_obj_t *self,
    bool single_channel_output,
    uint8_t channel);
audioio_get_buffer_result_t audioio_rawsample_get_buffer(audioio_rawsample_obj_t *self,
    bool single_channel_output,
    uint8_t channel,
    uint8_t **buffer,
    uint32_t *buffer_length);                                                      // length in bytes
