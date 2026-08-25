// audiomixer module table. New code (not a port) -- see audiocore/module.c
// for why this port uses a single registration file per module instead of
// CircuitPython's build-time manifest system. MixerVoice isn't registered
// at module scope, matching upstream: voices are only ever reached via
// `Mixer().voice`, never constructed directly by user code.
//
// SPDX-License-Identifier: MIT

#include "audiomixer/Mixer.h"
#include "audiomixer/MixerVoice.h"

#include "py/obj.h"

static const mp_rom_map_elem_t audiomixer_module_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_audiomixer) },
    { MP_ROM_QSTR(MP_QSTR_Mixer), MP_ROM_PTR(&audiomixer_mixer_type) },
};
static MP_DEFINE_CONST_DICT(audiomixer_module_globals, audiomixer_module_globals_table);

const mp_obj_module_t audiomixer_module = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&audiomixer_module_globals,
};

MP_REGISTER_MODULE(MP_QSTR_audiomixer, audiomixer_module);
