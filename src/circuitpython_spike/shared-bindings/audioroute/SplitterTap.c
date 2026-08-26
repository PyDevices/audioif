// audioroute.SplitterTap bindings for CircuitPython.
//
// SPDX-License-Identifier: MIT

#include <stdint.h>

#include "shared-bindings/audioroute/SplitterTap.h"
#include "shared-bindings/audiocore/__init__.h"

#include "py/runtime.h"

//| class SplitterTap:
//|     """One branch's view of a `Splitter`'s stream.
//|
//|     Taps are built by the Splitter and handed out by `Splitter.tap`; there
//|     is no constructor."""
//|
//|
static const mp_rom_map_elem_t audioroute_splitter_tap_locals_dict_table[] = {
    AUDIOSAMPLE_FIELDS,
};
static MP_DEFINE_CONST_DICT(audioroute_splitter_tap_locals_dict,
    audioroute_splitter_tap_locals_dict_table);

static const audiosample_p_t audioroute_splitter_tap_proto = {
    MP_PROTO_IMPLEMENT(MP_QSTR_protocol_audiosample)
    .reset_buffer = (audiosample_reset_buffer_fun)
        audioroute_splitter_tap_reset_buffer,
    .get_buffer = (audiosample_get_buffer_fun)
        audioroute_splitter_tap_get_buffer,
};

MP_DEFINE_CONST_OBJ_TYPE(
    audioroute_splitter_tap_type,
    MP_QSTR_SplitterTap,
    MP_TYPE_FLAG_HAS_SPECIAL_ACCESSORS,
    locals_dict, &audioroute_splitter_tap_locals_dict,
    protocol, &audioroute_splitter_tap_proto
    );
