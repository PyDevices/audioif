// audioecho.FeedbackDelay bindings for CircuitPython.
//
// SPDX-License-Identifier: MIT

#include <stdint.h>
#include <string.h>

#include "shared-bindings/audioecho/FeedbackDelay.h"
#include "shared-bindings/audiocore/__init__.h"

#include "py/objproperty.h"
#include "py/runtime.h"

//| class FeedbackDelay:
//|     """A delay line whose feedback path carries a low-pass, a high-pass, a
//|     soft-clip, per-sample delay modulation and a cross-feed between the
//|     channels.
//|
//|     Processes signed 16-bit stereo, and hands out 256 frames at a time. It
//|     sits in an audiosample chain like any other effect, and never reports
//|     itself finished - a starved chain gets silence. The line only advances
//|     with frames that arrive, so the repeats stop with the source rather
//|     than ringing on, the same way `audiodelays.Echo` behaves."""
//|
//|     def __init__(
//|         self,
//|         *,
//|         sample_rate: int = 48000,
//|         max_delay_ms: float = 250.0,
//|         delay_ms: float = ...,
//|         feedback: float = 0.4,
//|         mix: float = 0.3,
//|         damping_hz: float = 0.0,
//|         cut_hz: float = 0.0,
//|         wow_hz: float = 0.0,
//|         wow_depth_ms: float = 0.0,
//|         cross_feed: float = 0.0,
//|         loop_drive: float = 0.0,
//|         input_pan: float = 0.0,
//|     ) -> None:
//|         """Create a feedback delay. ``max_delay_ms`` sizes the line and
//|         cannot change afterwards; ``delay_ms`` defaults to half of it.
//|
//|         ``damping_hz`` and ``cut_hz`` are one-pole filters *inside* the
//|         loop, so every repeat loses a little more top and bottom than the
//|         last. ``loop_drive`` softens each pass. ``wow_hz`` and
//|         ``wow_depth_ms`` modulate the delay per sample, which is where the
//|         doppler in a tape machine's wow comes from. ``cross_feed`` sends
//|         each channel's repeats into the other channel's line, and
//|         ``input_pan`` steers the input into one line only: hard over with
//|         full cross-feed is a real ping-pong."""
//|         ...

// The options __init__ and set() accept, paired with the shared DSP's enum.
// `sample_rate` and `max_delay_ms` are deliberately absent: they size the
// line, so they are applied ahead of this table rather than from it, and
// keyword order stays irrelevant.
typedef struct {
    qstr name;
    audioif_feedback_delay_option_t option;
} feedback_delay_option_name_t;

static const feedback_delay_option_name_t feedback_delay_option_names[] = {
    { MP_QSTR_delay_ms, AUDIOIF_FEEDBACK_DELAY_OPT_DELAY_MS },
    { MP_QSTR_feedback, AUDIOIF_FEEDBACK_DELAY_OPT_FEEDBACK },
    { MP_QSTR_mix, AUDIOIF_FEEDBACK_DELAY_OPT_MIX },
    { MP_QSTR_damping_hz, AUDIOIF_FEEDBACK_DELAY_OPT_DAMPING_HZ },
    { MP_QSTR_cut_hz, AUDIOIF_FEEDBACK_DELAY_OPT_CUT_HZ },
    { MP_QSTR_wow_hz, AUDIOIF_FEEDBACK_DELAY_OPT_WOW_HZ },
    { MP_QSTR_wow_depth_ms, AUDIOIF_FEEDBACK_DELAY_OPT_WOW_DEPTH_MS },
    { MP_QSTR_cross_feed, AUDIOIF_FEEDBACK_DELAY_OPT_CROSS_FEED },
    { MP_QSTR_loop_drive, AUDIOIF_FEEDBACK_DELAY_OPT_LOOP_DRIVE },
    { MP_QSTR_input_pan, AUDIOIF_FEEDBACK_DELAY_OPT_INPUT_PAN },
};

static void feedback_delay_apply_kwargs(audioecho_feedback_delay_obj_t *self,
    const mp_map_t *kw) {
    for (size_t i = 0; i < kw->alloc; ++i) {
        if (!mp_map_slot_is_filled(kw, i)) {
            continue;
        }
        qstr name = mp_obj_str_get_qstr(kw->table[i].key);
        if (name == MP_QSTR_sample_rate || name == MP_QSTR_max_delay_ms) {
            continue;
        }
        float value = (float)mp_obj_get_float(kw->table[i].value);
        bool known = false;
        for (size_t option = 0;
             option < MP_ARRAY_SIZE(feedback_delay_option_names); ++option) {
            if (feedback_delay_option_names[option].name == name) {
                audioif_feedback_delay_configure(&self->config,
                    feedback_delay_option_names[option].option, value);
                known = true;
                break;
            }
        }
        if (!known) {
            mp_raise_msg_varg(&mp_type_TypeError,
                MP_ERROR_TEXT("unknown FeedbackDelay option '%q'"), name);
        }
    }
}

static mp_obj_t audioecho_feedback_delay_make_new(const mp_obj_type_t *type,
    size_t n_args, size_t n_kw, const mp_obj_t *all_args) {
    mp_arg_check_num(n_args, n_kw, 0, 0, true);
    mp_map_t kw_map;
    mp_map_init_fixed_table(&kw_map, n_kw, all_args + n_args);

    uint32_t sample_rate = 48000;
    mp_float_t max_delay_ms = 250;
    for (size_t i = 0; i < kw_map.alloc; ++i) {
        if (!mp_map_slot_is_filled(&kw_map, i)) {
            continue;
        }
        qstr name = mp_obj_str_get_qstr(kw_map.table[i].key);
        if (name == MP_QSTR_sample_rate) {
            sample_rate = (uint32_t)mp_obj_get_int(kw_map.table[i].value);
        } else if (name == MP_QSTR_max_delay_ms) {
            max_delay_ms = mp_obj_get_float(kw_map.table[i].value);
        }
    }
    if (max_delay_ms <= 0) {
        mp_raise_ValueError(MP_ERROR_TEXT("max_delay_ms must be positive"));
    }

    audioecho_feedback_delay_obj_t *self =
        mp_obj_malloc(audioecho_feedback_delay_obj_t, type);
    self->base.sample_rate = sample_rate;
    self->base.max_buffer_length = sizeof(self->buffer);
    self->base.bits_per_sample = 16;
    self->base.channel_count = 2;
    self->base.samples_signed = 1;
    self->base.single_buffer = false;
    self->source = MP_OBJ_NULL;
    self->pending = NULL;
    self->pending_frames = 0;

    uint32_t line_frames =
        (uint32_t)((mp_float_t)sample_rate * max_delay_ms / 1000);
    if (line_frames < 2) {
        line_frames = 2;
    }
    audioif_feedback_delay_config_init(&self->config, sample_rate,
        line_frames);
    int16_t *line = m_malloc((size_t)line_frames * 2u * sizeof(int16_t));
    memset(line, 0, (size_t)line_frames * 2u * sizeof(int16_t));
    audioif_feedback_delay_state_init(&self->state, line);
    // The default delay is half the line rather than all of it, so a caller
    // who sizes the line and says nothing else still hears repeats.
    audioif_feedback_delay_configure(&self->config,
        AUDIOIF_FEEDBACK_DELAY_OPT_DELAY_MS, (float)max_delay_ms * 0.5f);

    feedback_delay_apply_kwargs(self, &kw_map);
    audioif_feedback_delay_config_finish(&self->config);
    return MP_OBJ_FROM_PTR(self);
}

//|     def play(self, sample: circuitpython_typing.AudioSample) -> None:
//|         """Set the source the delay reads from."""
//|         ...
static mp_obj_t audioecho_feedback_delay_play(mp_obj_t self_in,
    mp_obj_t sample) {
    audioecho_feedback_delay_obj_t *self = MP_OBJ_TO_PTR(self_in);
    (void)audiosample_check(sample);
    self->source = sample;
    self->pending = NULL;
    self->pending_frames = 0;
    return mp_const_none;
}
MP_DEFINE_CONST_FUN_OBJ_2(audioecho_feedback_delay_play_obj,
    audioecho_feedback_delay_play);

//|     def set(self, **options: float) -> None:
//|         """Change settings mid-stream. The line and the filters keep their
//|         contents; only what the loop does to them changes."""
//|         ...
static mp_obj_t audioecho_feedback_delay_set(size_t n_args,
    const mp_obj_t *args, mp_map_t *kw_args) {
    audioecho_feedback_delay_obj_t *self = MP_OBJ_TO_PTR(args[0]);
    (void)n_args;
    feedback_delay_apply_kwargs(self, kw_args);
    return mp_const_none;
}
MP_DEFINE_CONST_FUN_OBJ_KW(audioecho_feedback_delay_set_obj, 1,
    audioecho_feedback_delay_set);

//|     def clear(self) -> None:
//|         """Empty the line and the loop filters."""
//|         ...
//|
//|
static mp_obj_t audioecho_feedback_delay_clear(mp_obj_t self_in) {
    audioecho_feedback_delay_obj_t *self = MP_OBJ_TO_PTR(self_in);
    audioif_feedback_delay_reset(&self->state, &self->config);
    return mp_const_none;
}
MP_DEFINE_CONST_FUN_OBJ_1(audioecho_feedback_delay_clear_obj,
    audioecho_feedback_delay_clear);

static const mp_rom_map_elem_t
audioecho_feedback_delay_locals_dict_table[] = {
    { MP_ROM_QSTR(MP_QSTR_play),
      MP_ROM_PTR(&audioecho_feedback_delay_play_obj) },
    { MP_ROM_QSTR(MP_QSTR_set),
      MP_ROM_PTR(&audioecho_feedback_delay_set_obj) },
    { MP_ROM_QSTR(MP_QSTR_clear),
      MP_ROM_PTR(&audioecho_feedback_delay_clear_obj) },
    AUDIOSAMPLE_FIELDS,
};
static MP_DEFINE_CONST_DICT(audioecho_feedback_delay_locals_dict,
    audioecho_feedback_delay_locals_dict_table);

static const audiosample_p_t audioecho_feedback_delay_proto = {
    MP_PROTO_IMPLEMENT(MP_QSTR_protocol_audiosample)
    .reset_buffer = (audiosample_reset_buffer_fun)
        audioecho_feedback_delay_reset_buffer,
    .get_buffer = (audiosample_get_buffer_fun)
        audioecho_feedback_delay_get_buffer,
};

MP_DEFINE_CONST_OBJ_TYPE(
    audioecho_feedback_delay_type,
    MP_QSTR_FeedbackDelay,
    MP_TYPE_FLAG_HAS_SPECIAL_ACCESSORS,
    make_new, audioecho_feedback_delay_make_new,
    locals_dict, &audioecho_feedback_delay_locals_dict,
    protocol, &audioecho_feedback_delay_proto
    );
