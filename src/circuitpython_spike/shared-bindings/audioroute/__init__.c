// audioroute module table for CircuitPython.
//
// SPDX-License-Identifier: MIT

#include <stdint.h>

#include "py/obj.h"
#include "py/runtime.h"

#include "shared-bindings/audioroute/__init__.h"
#include "shared-bindings/audioroute/Splitter.h"
#include "shared-bindings/audioroute/SplitterTap.h"

//| """Fan one audio stream out to parallel branches
//|
//| The `audioroute` module lets a single source feed several effect chains at
//| once - an exciter, a Haas widener, multiband splits - which a `audiomixer`
//| Mixer then sums back together. It is not part of CircuitPython upstream; it
//| comes from PyDevices' audioif, which in turn took it from micropython-vst3's
//| audio engine.
//|
//| """

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
