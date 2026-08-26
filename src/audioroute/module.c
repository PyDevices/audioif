// audioroute module table. New code (not a port) -- see audiomixer/module.c
// for why this port uses a single registration file per module.
//
// SplitterTap is exported for `isinstance` checks and repr readability only;
// it has no constructor, and taps come from `Splitter.tap(index)`.
//
// SPDX-License-Identifier: MIT

#include "audioroute/Splitter.h"
#include "audioroute/SplitterTap.h"

#include "py/obj.h"

static const mp_rom_map_elem_t audioroute_module_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_audioroute) },
    { MP_ROM_QSTR(MP_QSTR_Splitter), MP_ROM_PTR(&audioroute_splitter_type) },
    { MP_ROM_QSTR(MP_QSTR_SplitterTap),
      MP_ROM_PTR(&audioroute_splitter_tap_type) },
};
static MP_DEFINE_CONST_DICT(audioroute_module_globals,
    audioroute_module_globals_table);

const mp_obj_module_t audioroute_module = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&audioroute_module_globals,
};

MP_REGISTER_MODULE(MP_QSTR_audioroute, audioroute_module);
