// Ported from CircuitPython's shared-bindings/synthio/Biquad.h and
// shared-module/synthio/Biquad.h (upstream repo:
// https://github.com/adafruit/circuitpython, MIT), merged into one file.
//
// SPDX-License-Identifier: MIT

#pragma once

#include "py/obj.h"

#include "synthio/block.h"

extern const mp_obj_type_t synthio_biquad_type_obj;
extern const mp_obj_type_t synthio_filter_mode_type;
typedef struct synthio_biquad synthio_biquad_t;

typedef enum {
    SYNTHIO_LOW_PASS, SYNTHIO_HIGH_PASS, SYNTHIO_BAND_PASS, SYNTHIO_NOTCH,
    // filters beyond this line use the "A" parameter (in addition to f0 and Q)
    SYNTHIO_PEAKING_EQ, SYNTHIO_LOW_SHELF, SYNTHIO_HIGH_SHELF
} synthio_filter_mode;

#define BIQUAD_SHIFT (15)

struct synthio_biquad {
    mp_obj_base_t base;
    synthio_filter_mode mode;
    synthio_block_slot_t f0, Q, A;
    mp_float_t cached_W0, cached_Q, cached_A;
    int32_t a1, a2, b0, b1, b2;
};

typedef struct {
    int32_t x[2], y[2];
} biquad_filter_state;

mp_obj_t common_hal_synthio_biquad_get_A(synthio_biquad_t *self);
void common_hal_synthio_biquad_set_A(synthio_biquad_t *self, mp_obj_t A);

mp_obj_t common_hal_synthio_biquad_get_Q(synthio_biquad_t *self);
void common_hal_synthio_biquad_set_Q(synthio_biquad_t *self, mp_obj_t Q);

mp_obj_t common_hal_synthio_biquad_get_frequency(synthio_biquad_t *self);
void common_hal_synthio_biquad_set_frequency(synthio_biquad_t *self, mp_obj_t frequency);

synthio_filter_mode common_hal_synthio_biquad_get_mode(synthio_biquad_t *self);

mp_obj_t common_hal_synthio_biquad_new(synthio_filter_mode mode);

void common_hal_synthio_biquad_tick(mp_obj_t self_in);
void synthio_biquad_filter_reset(biquad_filter_state *st);
void synthio_biquad_filter_samples(mp_obj_t self_in, biquad_filter_state *st, int32_t *buffer, size_t n_samples);
