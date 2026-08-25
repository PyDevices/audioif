// audiofreeverb module table. New code (not a port) -- see
// audiomixer/module.c for why this port uses a single registration file
// per module.
//
// SPDX-License-Identifier: MIT

#include "audiofreeverb/Freeverb.h"

#include "py/obj.h"

static const mp_rom_map_elem_t audiofreeverb_module_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_audiofreeverb) },
    { MP_ROM_QSTR(MP_QSTR_Freeverb), MP_ROM_PTR(&audiofreeverb_freeverb_type) },
};
static MP_DEFINE_CONST_DICT(audiofreeverb_module_globals, audiofreeverb_module_globals_table);

const mp_obj_module_t audiofreeverb_module = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&audiofreeverb_module_globals,
};

MP_REGISTER_MODULE(MP_QSTR_audiofreeverb, audiofreeverb_module);
