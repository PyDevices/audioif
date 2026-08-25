// Ported from CircuitPython's shared-bindings/synthio/Biquad.c and
// shared-module/synthio/Biquad.c (upstream repo:
// https://github.com/adafruit/circuitpython, MIT), merged into one file.
// Docstrings dropped. See docs/upstream-diff.md: every type using
// MP_PROPERTY_GETTER/GETSET needs `attr, cp_compat_attr` wired in.
//
// SPDX-License-Identifier: MIT

#include <math.h>
#include <stdint.h>
#include <string.h>

#include "cp_compat/enum.h"
#include "cp_compat/objproperty.h"
#include "cp_compat/util.h"
#include "synthio/Biquad.h"
#include "synthio/__init__.h"

#include "py/runtime.h"

// --- from shared-module/synthio/Biquad.c ----------------------------------

typedef struct {
    mp_float_t s, c;
} sincos_result_t;

// The famous Quake approximate square root function
static mp_float_t Q_rsqrt(mp_float_t number_in) {
    float number = (float)number_in;
    union {
        float f;
        uint32_t i;
    } conv = { .f = (float)number };
    conv.i = 0x5f3759df - (conv.i >> 1);
    conv.f *= 1.5F - (number * 0.5F * conv.f * conv.f);
    return (mp_float_t)conv.f;
}

static mp_float_t fast_sqrt(mp_float_t number) {
    return number * Q_rsqrt(number);
}

// Deviation from upstream: M_PI is a glibc/mingw <math.h> extension, not
// ISO C99 -- present transitively on unix/windows, but undeclared under
// emscripten's strict `-std=c99` (phase 8d). Defined here only if missing.
#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
#define FOUR_OVER_PI (4 / M_PI)
static void fast_sincos(mp_float_t theta, sincos_result_t *result) {
    mp_float_t x = (theta * FOUR_OVER_PI) - 1;
    mp_float_t x2 = x * x, x3 = x2 * x, x4 = x2 * x2, x5 = x2 * x3;
    mp_float_t c0 = 0.70708592,
               c1x = -0.55535724 * x,
               c2x2 = -0.21798592 * x2,
               c3x3 = 0.05707685 * x3,
               c4x4 = 0.0109 * x4,
               c5x5 = -0.00171961 * x5;

    mp_float_t evens = c4x4 + c2x2 + c0, odds = c5x5 + c3x3 + c1x;
    result->c = evens + odds;
    result->s = evens - odds;
}

mp_obj_t common_hal_synthio_biquad_new(synthio_filter_mode mode) {
    synthio_biquad_t *self = mp_obj_malloc(synthio_biquad_t, &synthio_biquad_type_obj);
    self->mode = mode;
    return MP_OBJ_FROM_PTR(self);
}

synthio_filter_mode common_hal_synthio_biquad_get_mode(synthio_biquad_t *self) {
    return self->mode;
}

mp_obj_t common_hal_synthio_biquad_get_Q(synthio_biquad_t *self) {
    return self->Q.obj;
}

void common_hal_synthio_biquad_set_Q(synthio_biquad_t *self, mp_obj_t Q) {
    synthio_block_assign_slot(Q, &self->Q, MP_QSTR_Q);
}

mp_obj_t common_hal_synthio_biquad_get_A(synthio_biquad_t *self) {
    return self->A.obj;
}

void common_hal_synthio_biquad_set_A(synthio_biquad_t *self, mp_obj_t A) {
    synthio_block_assign_slot(A, &self->A, MP_QSTR_A);
}

mp_obj_t common_hal_synthio_biquad_get_frequency(synthio_biquad_t *self) {
    return self->f0.obj;
}

void common_hal_synthio_biquad_set_frequency(synthio_biquad_t *self, mp_obj_t frequency) {
    synthio_block_assign_slot(frequency, &self->f0, MP_QSTR_frequency);
}

static int32_t biquad_scale_arg_float(mp_float_t arg) {
    return (int32_t)MICROPY_FLOAT_C_FUN(round)(MICROPY_FLOAT_C_FUN(ldexp)(arg, BIQUAD_SHIFT));
}

static int float_equal_or_update(
    mp_float_t *cached,
    mp_float_t new) {
    // uses memcmp to avoid error about equality float comparison
    if (memcmp(cached, &new, sizeof(mp_float_t))) {
        *cached = new;
        return false;
    }
    return true;
}

void common_hal_synthio_biquad_tick(mp_obj_t self_in) {
    synthio_biquad_t *self = MP_OBJ_TO_PTR(self_in);

    mp_float_t W0 = synthio_block_slot_get(&self->f0) * synthio_global_W_scale;
    mp_float_t Q = synthio_block_slot_get(&self->Q);
    mp_float_t A =
        (self->mode >= SYNTHIO_PEAKING_EQ) ? synthio_block_slot_get(&self->A) : 0;

    // n.b., assumes that the `mode` field is read-only
    // n.b., use of `&` is deliberate, avoids short-circuiting behavior
    if (float_equal_or_update(&self->cached_W0, W0)
        & float_equal_or_update(&self->cached_Q, Q)
        & float_equal_or_update(&self->cached_A, A)) {
        return;
    }

    sincos_result_t sc;
    fast_sincos(W0, &sc);

    mp_float_t alpha = sc.s / (2 * Q);

    mp_float_t a0, a1, a2, b0, b1, b2;

    switch (self->mode) {
        default:
            a0 = 1 + alpha;
            a1 = -2 * sc.c;
            a2 = 1 - alpha;

            switch (self->mode) {
                default:
                case SYNTHIO_LOW_PASS:
                    b2 = b0 = (1 - sc.c) * .5;
                    b1 = 1 - sc.c;
                    break;

                case SYNTHIO_HIGH_PASS:
                    b2 = b0 = (1 + sc.c) * .5;
                    b1 = -(1 + sc.c);
                    break;

                case SYNTHIO_BAND_PASS:
                    b0 = alpha;
                    b1 = 0;
                    b2 = -b0;
                    break;

                case SYNTHIO_NOTCH:
                    b0 = 1;
                    b1 = -2 * sc.c;
                    b2 = 1;
            }

            break;

        case SYNTHIO_PEAKING_EQ:
            b0 = 1 + alpha * A;
            b1 = -2 * sc.c;
            b2 = 1 + alpha * A;
            a0 = 1 + alpha / A;
            a1 = -2 * sc.c;
            a2 = 1 - alpha / A;
            break;

        case SYNTHIO_LOW_SHELF: {
            mp_float_t sqrt_A = fast_sqrt(A);
            b0 = A * ((A + 1) - (A - 1) * sc.c + 2 * sqrt_A * alpha);
            b1 = 2 * A * ((A - 1) - (A + 1) * sc.c);
            b2 = A * ((A + 1) - (A - 1) * sc.c - 2 * sqrt_A * alpha);
            a0 = (A + 1) + (A - 1) * sc.c + 2 * sqrt_A * alpha;
            a1 = -2 * ((A - 1) + (A + 1) * sc.c);
            a2 = (A + 1) + (A - 1) * sc.c - 2 * sqrt_A * alpha;
        }
        break;

        case SYNTHIO_HIGH_SHELF: {
            mp_float_t sqrt_A = fast_sqrt(A);
            b0 = A * ((A + 1) + (A - 1) * sc.c + 2 * sqrt_A * alpha);
            b1 = -2 * A * ((A - 1) + (A + 1) * sc.c);
            b2 = A * ((A + 1) + (A - 1) * sc.c - 2 * sqrt_A * alpha);
            a0 = (A + 1) - (A - 1) * sc.c + 2 * sqrt_A * alpha;
            a1 = 2 * ((A - 1) - (A + 1) * sc.c);
            a2 = (A + 1) - (A - 1) * sc.c - 2 * sqrt_A * alpha;
        }
        break;
    }
    mp_float_t recip_a0 = 1 / a0;

    self->a1 = biquad_scale_arg_float(a1 * recip_a0);
    self->a2 = biquad_scale_arg_float(a2 * recip_a0);
    self->b0 = biquad_scale_arg_float(b0 * recip_a0);
    self->b1 = biquad_scale_arg_float(b1 * recip_a0);
    self->b2 = biquad_scale_arg_float(b2 * recip_a0);
}

void synthio_biquad_filter_reset(biquad_filter_state *st) {
    memset(&st->x, 0, 4 * sizeof(int16_t));
}

void synthio_biquad_filter_samples(mp_obj_t self_in, biquad_filter_state *st, int32_t *buffer, size_t n_samples) {
    synthio_biquad_t *self = MP_OBJ_TO_PTR(self_in);

    int32_t a1 = self->a1;
    int32_t a2 = self->a2;
    int32_t b0 = self->b0;
    int32_t b1 = self->b1;
    int32_t b2 = self->b2;

    int32_t x0 = st->x[0];
    int32_t x1 = st->x[1];
    int32_t y0 = st->y[0];
    int32_t y1 = st->y[1];

    for (size_t n = n_samples; n; --n, ++buffer) {
        int32_t input = *buffer;
        int32_t output = synthio_sat16((b0 * input + b1 * x0 + b2 * x1 - a1 * y0 - a2 * y1 + (1 << (BIQUAD_SHIFT - 1))), BIQUAD_SHIFT);

        x1 = x0;
        x0 = input;
        y1 = y0;
        y0 = output;
        *buffer = output;
    }
    st->x[0] = x0;
    st->x[1] = x1;
    st->y[0] = y0;
    st->y[1] = y1;
}

// --- from shared-bindings/synthio/Biquad.c --------------------------------

MAKE_ENUM_VALUE(synthio_filter_mode_type, mode, LOW_PASS, SYNTHIO_LOW_PASS);
MAKE_ENUM_VALUE(synthio_filter_mode_type, mode, HIGH_PASS, SYNTHIO_HIGH_PASS);
MAKE_ENUM_VALUE(synthio_filter_mode_type, mode, BAND_PASS, SYNTHIO_BAND_PASS);
MAKE_ENUM_VALUE(synthio_filter_mode_type, mode, NOTCH, SYNTHIO_NOTCH);
MAKE_ENUM_VALUE(synthio_filter_mode_type, mode, LOW_SHELF, SYNTHIO_LOW_SHELF);
MAKE_ENUM_VALUE(synthio_filter_mode_type, mode, HIGH_SHELF, SYNTHIO_HIGH_SHELF);
MAKE_ENUM_VALUE(synthio_filter_mode_type, mode, PEAKING_EQ, SYNTHIO_PEAKING_EQ);

MAKE_ENUM_MAP(synthio_filter_mode) {
    MAKE_ENUM_MAP_ENTRY(mode, LOW_PASS),
    MAKE_ENUM_MAP_ENTRY(mode, HIGH_PASS),
    MAKE_ENUM_MAP_ENTRY(mode, BAND_PASS),
    MAKE_ENUM_MAP_ENTRY(mode, NOTCH),
    MAKE_ENUM_MAP_ENTRY(mode, LOW_SHELF),
    MAKE_ENUM_MAP_ENTRY(mode, HIGH_SHELF),
    MAKE_ENUM_MAP_ENTRY(mode, PEAKING_EQ),
};

static MP_DEFINE_CONST_DICT(synthio_filter_mode_locals_dict, synthio_filter_mode_locals_table);

MAKE_PRINTER(synthio, synthio_filter_mode);

MAKE_ENUM_TYPE(synthio, FilterMode, synthio_filter_mode);

static synthio_filter_mode validate_synthio_filter_mode(mp_obj_t obj, qstr arg_name) {
    return cp_enum_value(&synthio_filter_mode_type, obj, arg_name);
}

static const mp_arg_t biquad_properties[] = {
    { MP_QSTR_mode, MP_ARG_OBJ | MP_ARG_REQUIRED, {.u_obj = MP_OBJ_NULL } },
    { MP_QSTR_frequency, MP_ARG_OBJ | MP_ARG_REQUIRED, {.u_obj = MP_OBJ_NULL } },
    { MP_QSTR_Q, MP_ARG_OBJ, {.u_obj = MP_OBJ_NULL } },
    { MP_QSTR_A, MP_ARG_OBJ, {.u_obj = MP_ROM_NONE } },
};

static mp_obj_t synthio_biquad_make_new(const mp_obj_type_t *type_in, size_t n_args, size_t n_kw, const mp_obj_t *all_args) {
    enum { ARG_mode, ARG_frequency, ARG_Q };

    mp_arg_val_t args[MP_ARRAY_SIZE(biquad_properties)];
    mp_arg_parse_all_kw_array(n_args, n_kw, all_args, MP_ARRAY_SIZE(biquad_properties), biquad_properties, args);

    if (args[ARG_Q].u_obj == MP_OBJ_NULL) {
        args[ARG_Q].u_obj = mp_obj_new_float(MICROPY_FLOAT_CONST(0.7071067811865475));
    }

    synthio_filter_mode mode = validate_synthio_filter_mode(args[ARG_mode].u_obj, MP_QSTR_mode);
    mp_obj_t result = common_hal_synthio_biquad_new(mode);
    properties_construct_helper(result, biquad_properties + 1, args + 1, MP_ARRAY_SIZE(biquad_properties) - 1);
    return result;
}

static mp_obj_t synthio_biquad_get_mode(mp_obj_t self_in) {
    synthio_biquad_t *self = MP_OBJ_TO_PTR(self_in);
    return cp_enum_find(&synthio_filter_mode_type, common_hal_synthio_biquad_get_mode(self));
}
MP_DEFINE_CONST_FUN_OBJ_1(synthio_biquad_get_mode_obj, synthio_biquad_get_mode);

MP_PROPERTY_GETTER(synthio_biquad_mode_obj,
    (mp_obj_t)&synthio_biquad_get_mode_obj);

static mp_obj_t synthio_biquad_get_frequency(mp_obj_t self_in) {
    synthio_biquad_t *self = MP_OBJ_TO_PTR(self_in);
    return common_hal_synthio_biquad_get_frequency(self);
}
MP_DEFINE_CONST_FUN_OBJ_1(synthio_biquad_get_frequency_obj, synthio_biquad_get_frequency);

static mp_obj_t synthio_biquad_set_frequency(mp_obj_t self_in, mp_obj_t arg) {
    synthio_biquad_t *self = MP_OBJ_TO_PTR(self_in);
    common_hal_synthio_biquad_set_frequency(self, arg);
    return mp_const_none;
}
MP_DEFINE_CONST_FUN_OBJ_2(synthio_biquad_set_frequency_obj, synthio_biquad_set_frequency);
MP_PROPERTY_GETSET(synthio_biquad_frequency_obj,
    (mp_obj_t)&synthio_biquad_get_frequency_obj,
    (mp_obj_t)&synthio_biquad_set_frequency_obj);

static mp_obj_t synthio_biquad_get_Q(mp_obj_t self_in) {
    synthio_biquad_t *self = MP_OBJ_TO_PTR(self_in);
    return common_hal_synthio_biquad_get_Q(self);
}
MP_DEFINE_CONST_FUN_OBJ_1(synthio_biquad_get_Q_obj, synthio_biquad_get_Q);

static mp_obj_t synthio_biquad_set_Q(mp_obj_t self_in, mp_obj_t arg) {
    synthio_biquad_t *self = MP_OBJ_TO_PTR(self_in);
    common_hal_synthio_biquad_set_Q(self, arg);
    return mp_const_none;
}
MP_DEFINE_CONST_FUN_OBJ_2(synthio_biquad_set_Q_obj, synthio_biquad_set_Q);
MP_PROPERTY_GETSET(synthio_biquad_Q_obj,
    (mp_obj_t)&synthio_biquad_get_Q_obj,
    (mp_obj_t)&synthio_biquad_set_Q_obj);

static mp_obj_t synthio_biquad_get_A(mp_obj_t self_in) {
    synthio_biquad_t *self = MP_OBJ_TO_PTR(self_in);
    return common_hal_synthio_biquad_get_A(self);
}
MP_DEFINE_CONST_FUN_OBJ_1(synthio_biquad_get_A_obj, synthio_biquad_get_A);

static mp_obj_t synthio_biquad_set_A(mp_obj_t self_in, mp_obj_t arg) {
    synthio_biquad_t *self = MP_OBJ_TO_PTR(self_in);
    common_hal_synthio_biquad_set_A(self, arg);
    return mp_const_none;
}
MP_DEFINE_CONST_FUN_OBJ_2(synthio_biquad_set_A_obj, synthio_biquad_set_A);
MP_PROPERTY_GETSET(synthio_biquad_A_obj,
    (mp_obj_t)&synthio_biquad_get_A_obj,
    (mp_obj_t)&synthio_biquad_set_A_obj);

static const mp_rom_map_elem_t synthio_biquad_locals_dict_table[] = {
    { MP_ROM_QSTR(MP_QSTR_mode), MP_ROM_PTR(&synthio_biquad_mode_obj) },
    { MP_ROM_QSTR(MP_QSTR_frequency), MP_ROM_PTR(&synthio_biquad_frequency_obj) },
    { MP_ROM_QSTR(MP_QSTR_Q), MP_ROM_PTR(&synthio_biquad_Q_obj) },
    { MP_ROM_QSTR(MP_QSTR_A), MP_ROM_PTR(&synthio_biquad_A_obj) },
};
static MP_DEFINE_CONST_DICT(synthio_biquad_locals_dict, synthio_biquad_locals_dict_table);

static void biquad_print(const mp_print_t *print, mp_obj_t self_in, mp_print_kind_t kind) {
    (void)kind;
    properties_print_helper(print, self_in, biquad_properties, MP_ARRAY_SIZE(biquad_properties));
}

MP_DEFINE_CONST_OBJ_TYPE(
    synthio_biquad_type_obj,
    MP_QSTR_Biquad,
    MP_TYPE_FLAG_HAS_SPECIAL_ACCESSORS,
    make_new, synthio_biquad_make_new,
    attr, cp_compat_attr,
    locals_dict, &synthio_biquad_locals_dict,
    print, biquad_print
    );
