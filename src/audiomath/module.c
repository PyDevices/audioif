// audiomath module table. New code (not a port) -- see audiomixer/module.c
// for why this port uses a single registration file per module.
//
// One class for now. The name is the room: anything that is arithmetic on
// streams rather than an effect built out of them belongs here.
//
// SPDX-License-Identifier: MIT

#include "audiomath/Multiply.h"

#include "py/obj.h"

static const mp_rom_map_elem_t audiomath_module_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_audiomath) },
    { MP_ROM_QSTR(MP_QSTR_Multiply), MP_ROM_PTR(&audiomath_multiply_type) },
};
static MP_DEFINE_CONST_DICT(audiomath_module_globals,
    audiomath_module_globals_table);

const mp_obj_module_t audiomath_module = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&audiomath_module_globals,
};

MP_REGISTER_MODULE(MP_QSTR_audiomath, audiomath_module);
