// The old side of the audiodynamics/audioroute gate.
//
// micropython-vst3's `vstaudio` usermod is where Dynamics and Splitter came
// from, but it cannot be imported here: modvstaudio.c is the plugin sidecar
// and wants a shared memory mapping a VST host created. Its DSP file has no
// such dependency, so this compiles `vstaudio_dsp.c` *verbatim* out of the
// sibling checkout and publishes the two types as `vstaudio_oracle`.
//
// Nothing in the shipping tree builds this. It exists so
// `capture_dynamics_oracle.sh` can record what the original nodes rendered,
// and it reads micropython-vst3 without writing to it.
//
// SPDX-License-Identifier: MIT

#include "py/obj.h"

extern const mp_obj_type_t vstaudio_dynamics_type;
extern const mp_obj_type_t vstaudio_splitter_type;

static const mp_rom_map_elem_t vstaudio_oracle_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_vstaudio_oracle) },
    { MP_ROM_QSTR(MP_QSTR_Dynamics), MP_ROM_PTR(&vstaudio_dynamics_type) },
    { MP_ROM_QSTR(MP_QSTR_Splitter), MP_ROM_PTR(&vstaudio_splitter_type) },
    { MP_ROM_QSTR(MP_QSTR_DYN_COMPRESS), MP_ROM_INT(0) },
    { MP_ROM_QSTR(MP_QSTR_DYN_LIMIT), MP_ROM_INT(1) },
    { MP_ROM_QSTR(MP_QSTR_DYN_EXPAND), MP_ROM_INT(2) },
    { MP_ROM_QSTR(MP_QSTR_DYN_GATE), MP_ROM_INT(3) },
    { MP_ROM_QSTR(MP_QSTR_DYN_TRANSIENT), MP_ROM_INT(4) },
};
static MP_DEFINE_CONST_DICT(vstaudio_oracle_globals,
    vstaudio_oracle_globals_table);

const mp_obj_module_t vstaudio_oracle_module = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&vstaudio_oracle_globals,
};

MP_REGISTER_MODULE(MP_QSTR_vstaudio_oracle, vstaudio_oracle_module);
