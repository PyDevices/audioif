// audiomath.Multiply. See Multiply.h for provenance.
// SPDX-License-Identifier: MIT

#include "audiomath/Multiply.h"

#include <string.h>

#include "py/runtime.h"

static mp_obj_t audiomath_multiply_make_new(const mp_obj_type_t *type,
    size_t n_args, size_t n_kw, const mp_obj_t *all_args) {
    enum { ARG_source, ARG_modulator, ARG_mix, ARG_sample_rate };
    static const mp_arg_t allowed_args[] = {
        { MP_QSTR_source, MP_ARG_OBJ, {.u_obj = MP_ROM_NONE} },
        { MP_QSTR_modulator, MP_ARG_OBJ, {.u_obj = MP_ROM_NONE} },
        { MP_QSTR_mix, MP_ARG_OBJ, {.u_obj = MP_ROM_NONE} },
        { MP_QSTR_sample_rate, MP_ARG_INT, {.u_int = 48000} },
    };
    mp_arg_val_t args[MP_ARRAY_SIZE(allowed_args)];
    mp_arg_parse_all_kw_array(n_args, n_kw, all_args,
        MP_ARRAY_SIZE(allowed_args), allowed_args, args);

    audiomath_multiply_obj_t *self =
        mp_obj_malloc(audiomath_multiply_obj_t, type);
    self->base.sample_rate = (uint32_t)args[ARG_sample_rate].u_int;
    self->base.max_buffer_length = sizeof(self->buffer);
    self->base.bits_per_sample = 16;
    self->base.channel_count = 2;
    self->base.samples_signed = 1;
    self->base.single_buffer = false;
    self->source = MP_OBJ_NULL;
    self->modulator = MP_OBJ_NULL;
    self->pending_source = NULL;
    self->pending_source_frames = 0;
    self->pending_modulator = NULL;
    self->pending_modulator_frames = 0;
    audioif_multiply_config_init(&self->config);

    if (args[ARG_source].u_obj != mp_const_none) {
        (void)audiosample_check(args[ARG_source].u_obj);
        self->source = args[ARG_source].u_obj;
    }
    if (args[ARG_modulator].u_obj != mp_const_none) {
        (void)audiosample_check(args[ARG_modulator].u_obj);
        self->modulator = args[ARG_modulator].u_obj;
    }
    if (args[ARG_mix].u_obj != mp_const_none) {
        audioif_multiply_set_mix(&self->config,
            (float)mp_obj_get_float(args[ARG_mix].u_obj));
    }
    return MP_OBJ_FROM_PTR(self);
}

static mp_obj_t audiomath_multiply_play(mp_obj_t self_in, mp_obj_t sample) {
    audiomath_multiply_obj_t *self = MP_OBJ_TO_PTR(self_in);
    (void)audiosample_check(sample);
    self->source = sample;
    self->pending_source = NULL;
    self->pending_source_frames = 0;
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(audiomath_multiply_play_obj,
    audiomath_multiply_play);

static mp_obj_t audiomath_multiply_modulate(mp_obj_t self_in,
    mp_obj_t sample) {
    audiomath_multiply_obj_t *self = MP_OBJ_TO_PTR(self_in);
    (void)audiosample_check(sample);
    self->modulator = sample;
    self->pending_modulator = NULL;
    self->pending_modulator_frames = 0;
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(audiomath_multiply_modulate_obj,
    audiomath_multiply_modulate);

// `set(mix=...)` rather than a property, to match audiodynamics.Dynamics --
// the two are siblings, both new here, and one settable option does not earn
// three copies of the getter/setter boilerplate.
static mp_obj_t audiomath_multiply_set(size_t n_args, const mp_obj_t *args,
    mp_map_t *kw_args) {
    audiomath_multiply_obj_t *self = MP_OBJ_TO_PTR(args[0]);
    (void)n_args;
    for (size_t i = 0; i < kw_args->alloc; ++i) {
        if (!mp_map_slot_is_filled(kw_args, i)) {
            continue;
        }
        qstr name = mp_obj_str_get_qstr(kw_args->table[i].key);
        if (name != MP_QSTR_mix) {
            mp_raise_msg_varg(&mp_type_TypeError,
                MP_ERROR_TEXT("unknown Multiply option '%q'"), name);
        }
        audioif_multiply_set_mix(&self->config,
            (float)mp_obj_get_float(kw_args->table[i].value));
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_KW(audiomath_multiply_set_obj, 1,
    audiomath_multiply_set);

static audioio_get_buffer_result_t audiomath_multiply_get_buffer(
    mp_obj_t self_in, bool single_channel_output, uint8_t channel,
    uint8_t **buffer, uint32_t *buffer_length) {
    (void)single_channel_output;
    (void)channel;
    audiomath_multiply_obj_t *self = MP_OBJ_TO_PTR(self_in);
    uint32_t produced = 0;
    while (produced < AUDIOIF_MULTIPLY_FRAMES) {
        if (self->pending_source_frames == 0) {
            if (self->source == MP_OBJ_NULL) {
                break;
            }
            uint8_t *raw = NULL;
            uint32_t raw_bytes = 0;
            audioio_get_buffer_result_t result = audiosample_get_buffer(
                self->source, false, 0, &raw, &raw_bytes);
            if (result == GET_BUFFER_ERROR || raw == NULL || raw_bytes < 4) {
                break;
            }
            self->pending_source = (const int16_t *)raw;
            self->pending_source_frames = raw_bytes / 4u;
        }
        if (self->pending_modulator_frames == 0 &&
            self->modulator != MP_OBJ_NULL) {
            uint8_t *raw = NULL;
            uint32_t raw_bytes = 0;
            audioio_get_buffer_result_t result = audiosample_get_buffer(
                self->modulator, false, 0, &raw, &raw_bytes);
            // A modulator is normally a short looping table, which hands back
            // its whole length every time it is asked; one that has genuinely
            // stopped leaves the signal alone rather than muting it.
            if (result != GET_BUFFER_ERROR && raw != NULL && raw_bytes >= 4) {
                self->pending_modulator = (const int16_t *)raw;
                self->pending_modulator_frames = raw_bytes / 4u;
            }
        }
        uint32_t run = AUDIOIF_MULTIPLY_FRAMES - produced;
        if (run > self->pending_source_frames) {
            run = self->pending_source_frames;
        }
        if (self->pending_modulator_frames > 0) {
            if (run > self->pending_modulator_frames) {
                run = self->pending_modulator_frames;
            }
            audioif_multiply_process_s16(&self->config,
                &self->buffer[produced * 2], self->pending_source,
                self->pending_modulator, run);
            self->pending_modulator += run * 2;
            self->pending_modulator_frames -= run;
        } else {
            audioif_multiply_passthrough_s16(&self->buffer[produced * 2],
                self->pending_source, run);
        }
        self->pending_source += run * 2;
        self->pending_source_frames -= run;
        produced += run;
    }
    // A starved chain gets silence rather than a short block: this node sits
    // in the middle of a live graph and never reports itself finished.
    if (produced == 0) {
        memset(self->buffer, 0, sizeof(self->buffer));
        produced = AUDIOIF_MULTIPLY_FRAMES;
    }
    *buffer = (uint8_t *)self->buffer;
    *buffer_length = produced * 4u;
    return GET_BUFFER_MORE_DATA;
}

static void audiomath_multiply_reset_buffer(mp_obj_t self_in,
    bool single_channel_output, uint8_t channel) {
    (void)single_channel_output;
    (void)channel;
    audiomath_multiply_obj_t *self = MP_OBJ_TO_PTR(self_in);
    self->pending_source = NULL;
    self->pending_source_frames = 0;
    // The modulator's cursor goes too, so a chain restarted mid-cycle begins
    // at the top of the table rather than wherever it happened to stop.
    self->pending_modulator = NULL;
    self->pending_modulator_frames = 0;
}

static const mp_rom_map_elem_t audiomath_multiply_locals_table[] = {
    { MP_ROM_QSTR(MP_QSTR_play), MP_ROM_PTR(&audiomath_multiply_play_obj) },
    { MP_ROM_QSTR(MP_QSTR_modulate),
      MP_ROM_PTR(&audiomath_multiply_modulate_obj) },
    { MP_ROM_QSTR(MP_QSTR_set), MP_ROM_PTR(&audiomath_multiply_set_obj) },
    AUDIOSAMPLE_FIELDS,
};
static MP_DEFINE_CONST_DICT(audiomath_multiply_locals,
    audiomath_multiply_locals_table);

static const audiosample_p_t audiomath_multiply_proto = {
    MP_PROTO_IMPLEMENT(MP_QSTR_protocol_audiosample)
    .reset_buffer = audiomath_multiply_reset_buffer,
    .get_buffer = audiomath_multiply_get_buffer,
};

MP_DEFINE_CONST_OBJ_TYPE(
    audiomath_multiply_type,
    MP_QSTR_Multiply,
    MP_TYPE_FLAG_HAS_SPECIAL_ACCESSORS,
    make_new, audiomath_multiply_make_new,
    attr, cp_compat_attr,
    locals_dict, &audiomath_multiply_locals,
    protocol, &audiomath_multiply_proto
    );
