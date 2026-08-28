// audiodynamics.Dynamics bindings for CircuitPython.
//
// SPDX-License-Identifier: MIT

#include <stdint.h>

#include "shared-bindings/audiodynamics/Dynamics.h"
#include "shared-bindings/audiocore/__init__.h"

#include "py/objproperty.h"
#include "py/runtime.h"

//| class Dynamics:
//|     """An envelope-follower gain computer: compressor, limiter, downward
//|     expander, gate, and transient shaper.
//|
//|     Processes signed 16-bit stereo, and hands out 256 frames at a time. It
//|     sits in an audiosample chain like any other effect, and never reports
//|     itself finished - a starved chain gets silence."""
//|
//|     def __init__(
//|         self,
//|         mode: int = DYN_COMPRESS,
//|         *,
//|         sample_rate: int = 48000,
//|         threshold_db: float = -24.0,
//|         ratio: float = 4.0,
//|         knee_db: float = 6.0,
//|         makeup_db: float = 0.0,
//|         attack_ms: float = 10.0,
//|         release_ms: float = 120.0,
//|         attack_gain_db: float = 0.0,
//|         sustain_gain_db: float = 0.0,
//|         sidechain_hz: float = 0.0,
//|     ) -> None:
//|         """Create a dynamics processor in one of the ``DYN_*`` modes.
//|
//|         ``sidechain_hz`` high-passes the detector without touching the
//|         audio, which is how a de-esser is built. ``attack_gain_db`` and
//|         ``sustain_gain_db`` apply to ``DYN_TRANSIENT`` only; the threshold,
//|         ratio and knee apply to the others."""
//|         ...

// The options __init__ and set() accept, paired with the shared DSP's enum.
// `sample_rate` is deliberately absent: the millisecond conversions read it,
// so it is applied ahead of this table rather than from it, and keyword order
// stays irrelevant.
typedef struct {
    qstr name;
    audioif_dynamics_option_t option;
} dynamics_option_name_t;

static const dynamics_option_name_t dynamics_option_names[] = {
    { MP_QSTR_threshold_db, AUDIOIF_DYNAMICS_OPT_THRESHOLD_DB },
    { MP_QSTR_ratio, AUDIOIF_DYNAMICS_OPT_RATIO },
    { MP_QSTR_knee_db, AUDIOIF_DYNAMICS_OPT_KNEE_DB },
    { MP_QSTR_makeup_db, AUDIOIF_DYNAMICS_OPT_MAKEUP_DB },
    { MP_QSTR_attack_ms, AUDIOIF_DYNAMICS_OPT_ATTACK_MS },
    { MP_QSTR_release_ms, AUDIOIF_DYNAMICS_OPT_RELEASE_MS },
    { MP_QSTR_attack_gain_db, AUDIOIF_DYNAMICS_OPT_ATTACK_GAIN_DB },
    { MP_QSTR_sustain_gain_db, AUDIOIF_DYNAMICS_OPT_SUSTAIN_GAIN_DB },
    { MP_QSTR_sidechain_hz, AUDIOIF_DYNAMICS_OPT_SIDECHAIN_HZ },
    { MP_QSTR_lookahead_ms, AUDIOIF_DYNAMICS_OPT_LOOKAHEAD_MS },
    { MP_QSTR_true_peak, AUDIOIF_DYNAMICS_OPT_TRUE_PEAK },
};

// The lookahead buffer is allocated only once someone asks for one, and only
// ever grows: `set(lookahead_ms=...)` mid-stream is a live gesture, and
// shrinking would mean freeing memory the DSP is reading out of.
static void dynamics_ensure_lookahead(audiodynamics_dynamics_obj_t *self) {
    const uint32_t wanted = audioif_dynamics_lookahead_frames(&self->config);
    if (wanted == 0 || wanted <= self->state.lookahead_capacity) {
        return;
    }
    int16_t *buffer = m_malloc((size_t)wanted * self->base.channel_count *
        sizeof(int16_t));
    audioif_dynamics_set_lookahead(&self->state, buffer, wanted);
}

static void dynamics_apply_kwargs(audiodynamics_dynamics_obj_t *self,
    const mp_map_t *kw) {
    for (size_t i = 0; i < kw->alloc; ++i) {
        if (mp_map_slot_is_filled(kw, i) &&
            mp_obj_str_get_qstr(kw->table[i].key) == MP_QSTR_sample_rate) {
            self->base.sample_rate =
                (uint32_t)mp_obj_get_int(kw->table[i].value);
            self->config.sample_rate = self->base.sample_rate;
        }
    }
    for (size_t i = 0; i < kw->alloc; ++i) {
        if (mp_map_slot_is_filled(kw, i) &&
            mp_obj_str_get_qstr(kw->table[i].key) == MP_QSTR_channel_count) {
            mp_int_t channels = mp_obj_get_int(kw->table[i].value);
            if (channels < 1 || channels > 2) {
                mp_raise_ValueError(MP_ERROR_TEXT(
                    "channel_count must be 1 or 2"));
            }
            self->base.channel_count = (uint8_t)channels;
            audioif_dynamics_set_channel_count(&self->config, &self->state,
                (uint32_t)channels);
        }
    }
    for (size_t i = 0; i < kw->alloc; ++i) {
        if (!mp_map_slot_is_filled(kw, i)) {
            continue;
        }
        qstr name = mp_obj_str_get_qstr(kw->table[i].key);
        if (name == MP_QSTR_sample_rate || name == MP_QSTR_channel_count) {
            continue;
        }
        float value = (float)mp_obj_get_float(kw->table[i].value);
        bool known = false;
        for (size_t option = 0; option < MP_ARRAY_SIZE(dynamics_option_names);
             ++option) {
            if (dynamics_option_names[option].name == name) {
                audioif_dynamics_configure(&self->config,
                    dynamics_option_names[option].option, value);
                known = true;
                break;
            }
        }
        if (!known) {
            mp_raise_msg_varg(&mp_type_TypeError,
                MP_ERROR_TEXT("unknown Dynamics option '%q'"), name);
        }
    }
    dynamics_ensure_lookahead(self);
}

static mp_obj_t audiodynamics_dynamics_make_new(const mp_obj_type_t *type,
    size_t n_args, size_t n_kw, const mp_obj_t *all_args) {
    mp_arg_check_num(n_args, n_kw, 0, 1, true);
    audiodynamics_dynamics_obj_t *self =
        mp_obj_malloc(audiodynamics_dynamics_obj_t, type);
    self->base.sample_rate = 48000;
    self->base.max_buffer_length = sizeof(self->buffer);
    self->base.bits_per_sample = 16;
    self->base.channel_count = 2;
    self->base.samples_signed = 1;
    self->base.single_buffer = false;
    self->source = MP_OBJ_NULL;
    self->pending = NULL;
    self->pending_frames = 0;

    const int mode = n_args >= 1 ? (int)mp_obj_get_int(all_args[0])
                                 : AUDIOIF_DYNAMICS_COMPRESS;
    audioif_dynamics_config_init(&self->config, mode, self->base.sample_rate);
    audioif_dynamics_state_init(&self->state);

    mp_map_t kw_map;
    mp_map_init_fixed_table(&kw_map, n_kw, all_args + n_args);
    dynamics_apply_kwargs(self, &kw_map);
    audioif_dynamics_config_finish(&self->config);
    return MP_OBJ_FROM_PTR(self);
}

//|     def play(self, sample: circuitpython_typing.AudioSample) -> None:
//|         """Take audio from ``sample``. Signed 16-bit stereo only."""
//|         ...
static mp_obj_t audiodynamics_dynamics_play(mp_obj_t self_in,
    mp_obj_t sample) {
    audiodynamics_dynamics_obj_t *self = MP_OBJ_TO_PTR(self_in);
    (void)audiosample_check(sample);
    self->source = sample;
    self->pending = NULL;
    self->pending_frames = 0;
    return mp_const_none;
}
MP_DEFINE_CONST_FUN_OBJ_2(audiodynamics_dynamics_play_obj,
    audiodynamics_dynamics_play);

//|     def set(self, **options: float) -> None:
//|         """Change any of the constructor's options mid-stream. The detector
//|         keeps its memory."""
//|         ...
static mp_obj_t audiodynamics_dynamics_set(size_t n_args,
    const mp_obj_t *args, mp_map_t *kw_args) {
    audiodynamics_dynamics_obj_t *self = MP_OBJ_TO_PTR(args[0]);
    (void)n_args;
    dynamics_apply_kwargs(self, kw_args);
    return mp_const_none;
}
MP_DEFINE_CONST_FUN_OBJ_KW(audiodynamics_dynamics_set_obj, 1,
    audiodynamics_dynamics_set);

//|     def gain_reduction_db(self) -> float:
//|         """Gain applied to the most recent frame, in dB (negative = cut)."""
//|         ...
//|
//|
static mp_obj_t audiodynamics_dynamics_gain_reduction_db(mp_obj_t self_in) {
    audiodynamics_dynamics_obj_t *self = MP_OBJ_TO_PTR(self_in);
    return mp_obj_new_float((mp_float_t)self->state.gain_reduction_db);
}
MP_DEFINE_CONST_FUN_OBJ_1(audiodynamics_dynamics_gain_reduction_db_obj,
    audiodynamics_dynamics_gain_reduction_db);

static const mp_rom_map_elem_t audiodynamics_dynamics_locals_dict_table[] = {
    { MP_ROM_QSTR(MP_QSTR_play), MP_ROM_PTR(&audiodynamics_dynamics_play_obj) },
    { MP_ROM_QSTR(MP_QSTR_set), MP_ROM_PTR(&audiodynamics_dynamics_set_obj) },
    { MP_ROM_QSTR(MP_QSTR_gain_reduction_db),
      MP_ROM_PTR(&audiodynamics_dynamics_gain_reduction_db_obj) },
    AUDIOSAMPLE_FIELDS,
};
static MP_DEFINE_CONST_DICT(audiodynamics_dynamics_locals_dict,
    audiodynamics_dynamics_locals_dict_table);

static const audiosample_p_t audiodynamics_dynamics_proto = {
    MP_PROTO_IMPLEMENT(MP_QSTR_protocol_audiosample)
    .reset_buffer = (audiosample_reset_buffer_fun)
        audiodynamics_dynamics_reset_buffer,
    .get_buffer = (audiosample_get_buffer_fun)
        audiodynamics_dynamics_get_buffer,
};

MP_DEFINE_CONST_OBJ_TYPE(
    audiodynamics_dynamics_type,
    MP_QSTR_Dynamics,
    MP_TYPE_FLAG_HAS_SPECIAL_ACCESSORS,
    make_new, audiodynamics_dynamics_make_new,
    locals_dict, &audiodynamics_dynamics_locals_dict,
    protocol, &audiodynamics_dynamics_proto
    );
