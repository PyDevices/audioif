// audioroute.SplitterTap. See SplitterTap.h for provenance.
// SPDX-License-Identifier: MIT

#include "audioroute/SplitterTap.h"

#include <string.h>

#include "py/runtime.h"

static audioio_get_buffer_result_t audioroute_splitter_tap_get_buffer(
    mp_obj_t self_in, bool single_channel_output, uint8_t channel,
    uint8_t **buffer, uint32_t *buffer_length) {
    (void)single_channel_output;
    (void)channel;
    audioroute_splitter_tap_obj_t *tap = MP_OBJ_TO_PTR(self_in);
    audioroute_splitter_obj_t *self = MP_OBJ_TO_PTR(tap->owner);
    if (audioif_splitter_starved(&self->state, tap->index)) {
        audioroute_splitter_pull(self);
    }
    uint32_t start = 0;
    const uint32_t run = audioif_splitter_take(&self->state, tap->index,
        &start);
    if (run == 0) {
        // Still nothing: the source is dry, or another tap has already read
        // ahead of what one pull could supply. Hand out silence and let the
        // branch stay in step rather than stalling the graph.
        memset(self->silence, 0, sizeof(self->silence));
        *buffer = (uint8_t *)self->silence;
        *buffer_length = sizeof(self->silence);
        return GET_BUFFER_MORE_DATA;
    }
    *buffer = (uint8_t *)&self->state.ring[start * 2u];
    *buffer_length = run * 4u;
    return GET_BUFFER_MORE_DATA;
}

static void audioroute_splitter_tap_reset_buffer(mp_obj_t self_in,
    bool single_channel_output, uint8_t channel) {
    // Deliberately nothing. The cursors belong to the Splitter and the other
    // taps are still reading from them; rewinding one branch mid-stream would
    // desynchronise the rest.
    (void)self_in;
    (void)single_channel_output;
    (void)channel;
}

static const mp_rom_map_elem_t audioroute_splitter_tap_locals_table[] = {
    AUDIOSAMPLE_FIELDS,
};
static MP_DEFINE_CONST_DICT(audioroute_splitter_tap_locals,
    audioroute_splitter_tap_locals_table);

static const audiosample_p_t audioroute_splitter_tap_proto = {
    MP_PROTO_IMPLEMENT(MP_QSTR_protocol_audiosample)
    .reset_buffer = audioroute_splitter_tap_reset_buffer,
    .get_buffer = audioroute_splitter_tap_get_buffer,
};

MP_DEFINE_CONST_OBJ_TYPE(
    audioroute_splitter_tap_type,
    MP_QSTR_SplitterTap,
    MP_TYPE_FLAG_HAS_SPECIAL_ACCESSORS,
    attr, cp_compat_attr,
    locals_dict, &audioroute_splitter_tap_locals,
    protocol, &audioroute_splitter_tap_proto
    );
