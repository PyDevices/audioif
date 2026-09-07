// audioshaper module table. New code (not a port) -- see audiomixer/module.c
// for why this port uses a single registration file per module.
//
// Named apart from CircuitPython's `audiofilters` on purpose: this is not an
// extension of `audiofilters.Distortion` but a different node -- one whose
// curve arrives as data and whose shaping happens above the sample rate.
// Adding either to `Distortion` would have made audioif's copy of a
// CircuitPython module diverge from the one on a stock board, which is the
// one thing apply_cp_patches.sh is built to avoid.
//
// SPDX-License-Identifier: MIT

#include "audioshaper/Waveshaper.h"

#include "py/obj.h"

static const mp_rom_map_elem_t audioshaper_module_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_audioshaper) },
    { MP_ROM_QSTR(MP_QSTR_Waveshaper),
      MP_ROM_PTR(&audioshaper_waveshaper_type) },
};
static MP_DEFINE_CONST_DICT(audioshaper_module_globals,
    audioshaper_module_globals_table);

const mp_obj_module_t audioshaper_module = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&audioshaper_module_globals,
};

MP_REGISTER_MODULE(MP_QSTR_audioshaper, audioshaper_module);
