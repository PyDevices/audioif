// Ported from CircuitPython's shared-bindings/synthio/LFO.h and
// shared-module/synthio/LFO.h (upstream repo:
// https://github.com/adafruit/circuitpython, MIT), merged into one file.
//
// SPDX-License-Identifier: MIT

#pragma once

#include "py/obj.h"

#include "synthio/block.h"

typedef struct synthio_lfo_obj {
    synthio_block_base_t base;
    bool once, interpolate;

    synthio_block_slot_t rate, scale, offset, phase_offset;
    mp_float_t accum;

    mp_obj_t waveform_obj;
    mp_buffer_info_t waveform_bufinfo;
} synthio_lfo_obj_t;

extern const mp_obj_type_t synthio_lfo_type;

mp_obj_t common_hal_synthio_lfo_get_waveform_obj(synthio_lfo_obj_t *self);
void common_hal_synthio_lfo_set_waveform_obj(synthio_lfo_obj_t *self, mp_obj_t arg);

mp_obj_t common_hal_synthio_lfo_get_rate_obj(synthio_lfo_obj_t *self);
void common_hal_synthio_lfo_set_rate_obj(synthio_lfo_obj_t *self, mp_obj_t arg);

mp_obj_t common_hal_synthio_lfo_get_scale_obj(synthio_lfo_obj_t *self);
void common_hal_synthio_lfo_set_scale_obj(synthio_lfo_obj_t *self, mp_obj_t arg);

mp_obj_t common_hal_synthio_lfo_get_phase_offset_obj(synthio_lfo_obj_t *self);
void common_hal_synthio_lfo_set_phase_offset_obj(synthio_lfo_obj_t *self, mp_obj_t arg);

mp_obj_t common_hal_synthio_lfo_get_offset_obj(synthio_lfo_obj_t *self);
void common_hal_synthio_lfo_set_offset_obj(synthio_lfo_obj_t *self, mp_obj_t arg);

bool common_hal_synthio_lfo_get_once(synthio_lfo_obj_t *self);
void common_hal_synthio_lfo_set_once(synthio_lfo_obj_t *self, bool arg);

bool common_hal_synthio_lfo_get_interpolate(synthio_lfo_obj_t *self);
void common_hal_synthio_lfo_set_interpolate(synthio_lfo_obj_t *self, bool arg);

mp_float_t common_hal_synthio_lfo_get_value(synthio_lfo_obj_t *self);

mp_float_t common_hal_synthio_lfo_get_phase(synthio_lfo_obj_t *self);

void common_hal_synthio_lfo_retrigger(synthio_lfo_obj_t *self);
mp_float_t common_hal_synthio_lfo_tick(mp_obj_t self_in);
