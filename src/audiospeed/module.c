// audiospeed module table. New code (not a port) -- see audiomixer/module.c
// for why this port uses a single registration file per module.
//
// SPDX-License-Identifier: MIT

#include "audiospeed/SpeedChanger.h"

#include "py/obj.h"

static const mp_rom_map_elem_t audiospeed_module_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_audiospeed) },
    { MP_ROM_QSTR(MP_QSTR_SpeedChanger), MP_ROM_PTR(&audiospeed_speedchanger_type) },
};
static MP_DEFINE_CONST_DICT(audiospeed_module_globals, audiospeed_module_globals_table);

const mp_obj_module_t audiospeed_module = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&audiospeed_module_globals,
};

MP_REGISTER_MODULE(MP_QSTR_audiospeed, audiospeed_module);
