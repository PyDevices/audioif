// Ported from CircuitPython's shared-bindings/synthio/Biquad.h and
// shared-module/synthio/Biquad.h (upstream repo:
// https://github.com/adafruit/circuitpython, MIT), merged into one file.
//
// SPDX-FileCopyrightText: Copyright (c) 2023 Jeff Epler for Adafruit Industries
// SPDX-FileCopyrightText: Copyright (c) 2026 PyDevices
// SPDX-License-Identifier: MIT

#pragma once

#include "py/obj.h"

#include "synthio/block.h"
#include "shared/audioif_biquad.h"

extern const mp_obj_type_t synthio_biquad_type_obj;
extern const mp_obj_type_t synthio_filter_mode_type;
typedef struct synthio_biquad synthio_biquad_t;

typedef enum {
    SYNTHIO_LOW_PASS, SYNTHIO_HIGH_PASS, SYNTHIO_BAND_PASS, SYNTHIO_NOTCH,
    // filters beyond this line use the "A" parameter (in addition to f0 and Q)
    SYNTHIO_PEAKING_EQ, SYNTHIO_LOW_SHELF, SYNTHIO_HIGH_SHELF
} synthio_filter_mode;

struct synthio_biquad {
    mp_obj_base_t base;
    synthio_filter_mode mode;
    synthio_block_slot_t f0, Q, A;
    mp_float_t cached_W0, cached_Q, cached_A;
    // `shift` is the coefficients' fixed-point format, which audioif picks per
    // filter rather than fixing at Q15 the way upstream does. Cache it with
    // them: they are meaningless apart.
    int32_t a1, a2, b0, b1, b2, shift;
    // CircuitPython 10.3.0's audiofilters_process_filter_chain uses these:
    // Q15, same scale as shared-module/synthio/Biquad.c. audioif's wider
    // shift above is a different arithmetic and is not that helper.
    //
    // audioif#77: choosing per-function like this makes ONE NODE'S ARITHMETIC
    // DEPEND ON WHICH TARGET IS RUNNING IT. synthio_biquad_filter_sample()
    // uses these, its plural sibling uses the wider shift, and the CPython
    // twin uses the wider shift for both -- so audiofilters.Filter renders
    // different bytes on MicroPython and on the CPython extension, 11 LSB
    // apart by the eighth sample of an 800 Hz low-pass and still opening.
    // Awaiting Brad's call on which kernel wins; do not "fix" one side alone.
    int32_t cp_a1, cp_a2, cp_b0, cp_b1, cp_b2;
};

typedef audioif_biquad_state_t biquad_filter_state;

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
int32_t synthio_biquad_filter_sample(mp_obj_t self_in, biquad_filter_state *st, int32_t input);
