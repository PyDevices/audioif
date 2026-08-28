// audioroute.Splitter. See Splitter.h for provenance.
// SPDX-License-Identifier: MIT

#include "audioroute/Splitter.h"

#include "audioroute/SplitterTap.h"

#include "py/runtime.h"

void audioroute_splitter_pull(audioroute_splitter_obj_t *self) {
    if (self->source == MP_OBJ_NULL) {
        return;
    }
    uint8_t *raw = NULL;
    uint32_t raw_bytes = 0;
    audioio_get_buffer_result_t result = audiosample_get_buffer(
        self->source, false, 0, &raw, &raw_bytes);
    if (result == GET_BUFFER_ERROR || raw == NULL) {
        return;
    }
    const uint32_t width = 2u * self->state.channel_count;
    if (raw_bytes % width != 0) {
        return;
    }
    audioif_splitter_write(&self->state, (const int16_t *)raw,
        raw_bytes / width);
}

static mp_obj_t audioroute_splitter_make_new(const mp_obj_type_t *type,
    size_t n_args, size_t n_kw, const mp_obj_t *all_args) {
    enum { ARG_source, ARG_taps };
    static const mp_arg_t allowed_args[] = {
        { MP_QSTR_source, MP_ARG_REQUIRED | MP_ARG_OBJ, {} },
        { MP_QSTR_taps, MP_ARG_INT, {.u_int = 2} },
    };
    mp_arg_val_t args[MP_ARRAY_SIZE(allowed_args)];
    mp_arg_parse_all_kw_array(n_args, n_kw, all_args,
        MP_ARRAY_SIZE(allowed_args), allowed_args, args);

    mp_obj_t source = args[ARG_source].u_obj;
    audiosample_base_t *sample = audiosample_check(source);
    const mp_int_t taps = args[ARG_taps].u_int;
    if (taps < 1 || taps > (mp_int_t)AUDIOIF_SPLITTER_MAX_TAPS) {
        mp_raise_ValueError(MP_ERROR_TEXT("taps must be 1..4"));
    }

    audioroute_splitter_obj_t *self =
        mp_obj_malloc(audioroute_splitter_obj_t, type);
    self->source = source;
    audioif_splitter_init(&self->state, (uint32_t)taps);
    if (sample->channel_count < 1 || sample->channel_count > 2) {
        mp_raise_ValueError(MP_ERROR_TEXT(
            "source channel_count must be 1 or 2"));
    }
    audioif_splitter_set_channel_count(&self->state, sample->channel_count);
    for (uint32_t index = 0; index < AUDIOIF_SPLITTER_MAX_TAPS; ++index) {
        self->taps[index] = MP_OBJ_NULL;
    }
    // Every tap exists from the start, whether or not anything asks for it:
    // the ring drops what an unread tap never collects, so a branch built
    // late would begin mid-stream rather than at the beginning.
    for (uint32_t index = 0; index < (uint32_t)taps; ++index) {
        audioroute_splitter_tap_obj_t *tap =
            mp_obj_malloc(audioroute_splitter_tap_obj_t,
                &audioroute_splitter_tap_type);
        tap->base.sample_rate = sample->sample_rate;
        tap->base.max_buffer_length = AUDIOIF_SPLITTER_CHUNK_FRAMES * 2u *
            sample->channel_count;
        tap->base.bits_per_sample = 16;
        tap->base.channel_count = sample->channel_count;
        tap->base.samples_signed = 1;
        tap->base.single_buffer = false;
        tap->owner = MP_OBJ_FROM_PTR(self);
        tap->index = index;
        self->taps[index] = MP_OBJ_FROM_PTR(tap);
    }
    return MP_OBJ_FROM_PTR(self);
}

static mp_obj_t audioroute_splitter_tap(mp_obj_t self_in, mp_obj_t index_in) {
    audioroute_splitter_obj_t *self = MP_OBJ_TO_PTR(self_in);
    const mp_int_t index = mp_obj_get_int(index_in);
    if (index < 0 || (uint32_t)index >= self->state.tap_count) {
        mp_raise_ValueError(MP_ERROR_TEXT("tap index out of range"));
    }
    return self->taps[index];
}
static MP_DEFINE_CONST_FUN_OBJ_2(audioroute_splitter_tap_obj,
    audioroute_splitter_tap);

static const mp_rom_map_elem_t audioroute_splitter_locals_table[] = {
    { MP_ROM_QSTR(MP_QSTR_tap), MP_ROM_PTR(&audioroute_splitter_tap_obj) },
};
static MP_DEFINE_CONST_DICT(audioroute_splitter_locals,
    audioroute_splitter_locals_table);

MP_DEFINE_CONST_OBJ_TYPE(
    audioroute_splitter_type,
    MP_QSTR_Splitter,
    MP_TYPE_FLAG_NONE,
    make_new, audioroute_splitter_make_new,
    locals_dict, &audioroute_splitter_locals
    );
