// audiodelays module table. New code (not a port) -- see
// audiomixer/module.c for why this port uses a single registration file
// per module.
//
// SPDX-License-Identifier: MIT

#include "audiodelays/Chorus.h"
#include "audiodelays/Echo.h"
#include "audiodelays/MultiTapDelay.h"
#include "audiodelays/PitchShift.h"

#include "py/obj.h"

static const mp_rom_map_elem_t audiodelays_module_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_audiodelays) },
    { MP_ROM_QSTR(MP_QSTR_Echo), MP_ROM_PTR(&audiodelays_echo_type) },
    { MP_ROM_QSTR(MP_QSTR_Chorus), MP_ROM_PTR(&audiodelays_chorus_type) },
    { MP_ROM_QSTR(MP_QSTR_PitchShift), MP_ROM_PTR(&audiodelays_pitch_shift_type) },
    { MP_ROM_QSTR(MP_QSTR_MultiTapDelay), MP_ROM_PTR(&audiodelays_multi_tap_delay_type) },
};
static MP_DEFINE_CONST_DICT(audiodelays_module_globals, audiodelays_module_globals_table);

const mp_obj_module_t audiodelays_module = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&audiodelays_module_globals,
};

MP_REGISTER_MODULE(MP_QSTR_audiodelays, audiodelays_module);
