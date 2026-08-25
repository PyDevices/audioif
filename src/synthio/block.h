// Ported from CircuitPython's shared-module/synthio/block.h (upstream
// repo: https://github.com/adafruit/circuitpython, MIT). Unchanged except
// the include paths (this port's flat layout, and cp_compat/proto.h).
//
// The "block input" value protocol: any synthio attribute typed as
// BlockInput (Math.__init__'s inputs, Note.amplitude/bend/panning, LFO
// rate/scale/offset/phase_offset, Biquad.frequency/Q/A, ...) accepts a
// plain float or an object implementing this protocol (Math, LFO), each
// tick-computed once per synthesis block and cached (see
// synthio_global_tick in synthio/__init__.c).
//
// SPDX-License-Identifier: MIT

#pragma once

#include "cp_compat/proto.h"
#include "py/obj.h"

#include "synthio/__init__.h"

typedef struct synthio_block_base {
    mp_obj_base_t base;
    uint8_t last_tick;
    mp_float_t value;
} synthio_block_base_t;

typedef struct synthio_block_slot {
    mp_obj_t obj;
} synthio_block_slot_t;

typedef struct {
    MP_PROTOCOL_HEAD;
    mp_float_t (*tick)(mp_obj_t obj);
} synthio_block_proto_t;

// Update the value inside the lfo slot if the value is an LFO, returning the new value
mp_float_t synthio_block_slot_get(synthio_block_slot_t *block_slot);
// the same, but the output is constrained to be between lo and hi
mp_float_t synthio_block_slot_get_limited(synthio_block_slot_t *block_slot, mp_float_t lo, mp_float_t hi);
// the same, but the output is constrained to be between lo and hi and converted to an integer with 15 fractional bits
int32_t synthio_block_slot_get_scaled(synthio_block_slot_t *block_slot, mp_float_t lo, mp_float_t hi);

// Assign an object (which may be a float or a synthio_block_obj_t) to an block slot
void synthio_block_assign_slot(mp_obj_t obj, synthio_block_slot_t *block_slot, qstr arg_name);
bool synthio_block_assign_slot_maybe(mp_obj_t obj, synthio_block_slot_t *block_slot);
bool synthio_obj_is_block(mp_obj_t obj);
