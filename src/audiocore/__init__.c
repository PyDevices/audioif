// Ported from CircuitPython's shared-module/audiocore/__init__.c (upstream
// repo: https://github.com/adafruit/circuitpython, MIT). Unused includes
// dropped (RawSample.h/WaveFile.h/audiomixer/Mixer.h/audioio/__init__.h --
// none of their symbols are referenced in this file upstream either;
// checked with a grep across the whole file before dropping them, to avoid
// a premature tier-3 build dependency here in tier 1).
//
// The deinit-guard helpers and the three common property accessors
// (sample_rate/bits_per_sample/channel_count) below are ported from
// CircuitPython's shared-bindings/audiocore/__init__.c, minus its
// CIRCUITPY_AUDIOCORE_DEBUG-gated get_buffer/reset_buffer/get_structure
// functions (docs-hidden debug helpers, not part of the real audiosample
// surface, and gated off in CP's own default config) and minus the module
// table + MP_REGISTER_MODULE (moved to module.c once RawSample/WaveFile
// exist, so this file doesn't have to forward-declare their types).
//
// SPDX-License-Identifier: MIT

#include "audiocore/__init__.h"
#include "cp_compat/argcheck.h"
#include "cp_compat/objproperty.h"
#include "cp_compat/util.h"

#include "py/obj.h"
#include "py/runtime.h"

void audiosample_reset_buffer(mp_obj_t sample_obj, bool single_channel_output, uint8_t audio_channel) {
    const audiosample_p_t *proto = mp_proto_get_or_throw(MP_QSTR_protocol_audiosample, sample_obj);
    proto->reset_buffer(MP_OBJ_TO_PTR(sample_obj), single_channel_output, audio_channel);
}

audioio_get_buffer_result_t audiosample_get_buffer(mp_obj_t sample_obj,
    bool single_channel_output,
    uint8_t channel,
    uint8_t **buffer, uint32_t *buffer_length) {
    const audiosample_p_t *proto = mp_proto_get_or_throw(MP_QSTR_protocol_audiosample, sample_obj);
    return proto->get_buffer(MP_OBJ_TO_PTR(sample_obj), single_channel_output, channel, buffer, buffer_length);
}

void audiosample_convert_u8m_s16s(int16_t *buffer_out, const uint8_t *buffer_in, size_t nframes) {
    for (; nframes--;) {
        int16_t sample = (*buffer_in++ - 0x80) << 8;
        *buffer_out++ = sample;
        *buffer_out++ = sample;
    }
}

void audiosample_convert_u8s_s16s(int16_t *buffer_out, const uint8_t *buffer_in, size_t nframes) {
    size_t nsamples = 2 * nframes;
    for (; nsamples--;) {
        int16_t sample = (*buffer_in++ - 0x80) << 8;
        *buffer_out++ = sample;
    }
}

void audiosample_convert_s8m_s16s(int16_t *buffer_out, const int8_t *buffer_in, size_t nframes) {
    for (; nframes--;) {
        int16_t sample = (*buffer_in++) << 8;
        *buffer_out++ = sample;
        *buffer_out++ = sample;
    }
}

void audiosample_convert_s8s_s16s(int16_t *buffer_out, const int8_t *buffer_in, size_t nframes) {
    size_t nsamples = 2 * nframes;
    for (; nsamples--;) {
        int16_t sample = (*buffer_in++) << 8;
        *buffer_out++ = sample;
    }
}

void audiosample_convert_u16m_s16s(int16_t *buffer_out, const uint16_t *buffer_in, size_t nframes) {
    for (; nframes--;) {
        int16_t sample = *buffer_in++ - 0x8000;
        *buffer_out++ = sample;
        *buffer_out++ = sample;
    }
}

void audiosample_convert_u16s_s16s(int16_t *buffer_out, const uint16_t *buffer_in, size_t nframes) {
    size_t nsamples = 2 * nframes;
    for (; nsamples--;) {
        int16_t sample = *buffer_in++ - 0x8000;
        *buffer_out++ = sample;
    }
}

void audiosample_convert_s16m_s16s(int16_t *buffer_out, const int16_t *buffer_in, size_t nframes) {
    for (; nframes--;) {
        int16_t sample = *buffer_in++;
        *buffer_out++ = sample;
        *buffer_out++ = sample;
    }
}


void audiosample_convert_u8s_u8m(uint8_t *buffer_out, const uint8_t *buffer_in, size_t nframes) {
    for (; nframes--;) {
        uint8_t sample = *buffer_in++ + 0x80;
        *buffer_out++ = sample;
        buffer_in++;
    }
}

void audiosample_convert_s8m_u8m(uint8_t *buffer_out, const int8_t *buffer_in, size_t nframes) {
    for (; nframes--;) {
        uint8_t sample = *buffer_in++ + 0x80;
        *buffer_out++ = sample;
    }
}

void audiosample_convert_s8s_u8m(uint8_t *buffer_out, const int8_t *buffer_in, size_t nframes) {
    for (; nframes--;) {
        uint8_t sample = *buffer_in++ + 0x80;
        *buffer_out++ = sample;
        buffer_in++;
    }
}

void audiosample_convert_u16m_u8m(uint8_t *buffer_out, const uint16_t *buffer_in, size_t nframes) {
    for (; nframes--;) {
        uint8_t sample = (*buffer_in++) >> 8;
        *buffer_out++ = sample;
    }
}

void audiosample_convert_u16s_u8m(uint8_t *buffer_out, const uint16_t *buffer_in, size_t nframes) {
    for (; nframes--;) {
        uint8_t sample = (*buffer_in++) >> 8;
        *buffer_out++ = sample;
        buffer_in++;
    }
}

void audiosample_convert_s16m_u8m(uint8_t *buffer_out, const int16_t *buffer_in, size_t nframes) {
    for (; nframes--;) {
        uint8_t sample = (*buffer_in++ + 0x8000) >> 8;
        *buffer_out++ = sample;
    }
}

void audiosample_convert_s16s_u8m(uint8_t *buffer_out, const int16_t *buffer_in, size_t nframes) {
    for (; nframes--;) {
        uint8_t sample = (*buffer_in++ + 0x8000) >> 8;
        *buffer_out++ = sample;
        buffer_in++;
    }
}


void audiosample_convert_u8m_u8s(uint8_t *buffer_out, const uint8_t *buffer_in, size_t nframes) {
    for (; nframes--;) {
        uint8_t sample = *buffer_in++;
        *buffer_out++ = sample;
        *buffer_out++ = sample;
    }
}

void audiosample_convert_s8m_u8s(uint8_t *buffer_out, const int8_t *buffer_in, size_t nframes) {
    for (; nframes--;) {
        uint8_t sample = *buffer_in++ + 0x80;
        *buffer_out++ = sample;
        *buffer_out++ = sample;
    }
}

void audiosample_convert_s8s_u8s(uint8_t *buffer_out, const int8_t *buffer_in, size_t nframes) {
    size_t nsamples = 2 * nframes;
    for (; nsamples--;) {
        uint8_t sample = *buffer_in++ + 0x80;
        *buffer_out++ = sample;
    }
}

void audiosample_convert_u16m_u8s(uint8_t *buffer_out, const uint16_t *buffer_in, size_t nframes) {
    for (; nframes--;) {
        uint8_t sample = (*buffer_in++) >> 8;
        *buffer_out++ = sample;
        *buffer_out++ = sample;
    }
}

void audiosample_convert_u16s_u8s(uint8_t *buffer_out, const uint16_t *buffer_in, size_t nframes) {
    size_t nsamples = 2 * nframes;
    for (; nsamples--;) {
        uint8_t sample = (*buffer_in++) >> 8;
        *buffer_out++ = sample;
    }
}

void audiosample_convert_s16m_u8s(uint8_t *buffer_out, const int16_t *buffer_in, size_t nframes) {
    for (; nframes--;) {
        uint8_t sample = (*buffer_in++ + 0x8000) >> 8;
        *buffer_out++ = sample;
        *buffer_out++ = sample;
    }
}

void audiosample_convert_s16s_u8s(uint8_t *buffer_out, const int16_t *buffer_in, size_t nframes) {
    size_t nsamples = 2 * nframes;
    for (; nsamples--;) {
        uint8_t sample = (*buffer_in++ + 0x8000) >> 8;
        *buffer_out++ = sample;
    }
}

void audiosample_must_match(audiosample_base_t *self, mp_obj_t other_in, bool allow_mono_to_stereo) {
    const audiosample_base_t *other = audiosample_check(other_in);
    if (other->sample_rate != self->sample_rate) {
        mp_raise_ValueError_varg(MP_ERROR_TEXT("The sample's %q does not match"), MP_QSTR_sample_rate);
    }
    if ((!allow_mono_to_stereo || (allow_mono_to_stereo && self->channel_count != 2)) && other->channel_count != self->channel_count) {
        mp_raise_ValueError_varg(MP_ERROR_TEXT("The sample's %q does not match"), MP_QSTR_channel_count);
    }
    if (other->bits_per_sample != self->bits_per_sample) {
        mp_raise_ValueError_varg(MP_ERROR_TEXT("The sample's %q does not match"), MP_QSTR_bits_per_sample);
    }
    if (other->samples_signed != self->samples_signed) {
        mp_raise_ValueError_varg(MP_ERROR_TEXT("The sample's %q does not match"), MP_QSTR_signedness);
    }
}

bool audiosample_deinited(const audiosample_base_t *self) {
    return self->channel_count == 0;
}

void audiosample_check_for_deinit(const audiosample_base_t *self) {
    if (audiosample_deinited(self)) {
        raise_deinited_error();
    }
}

void audiosample_mark_deinit(audiosample_base_t *self) {
    self->channel_count = 0;
}

// common implementation of channel_count property for audio samples
static mp_obj_t audiosample_obj_get_channel_count(mp_obj_t self_in) {
    audiosample_base_t *self = MP_OBJ_TO_PTR(self_in);
    audiosample_check_for_deinit(self);
    return MP_OBJ_NEW_SMALL_INT(audiosample_get_channel_count(self));
}
MP_DEFINE_CONST_FUN_OBJ_1(audiosample_get_channel_count_obj, audiosample_obj_get_channel_count);

MP_PROPERTY_GETTER(audiosample_channel_count_obj,
    (mp_obj_t)&audiosample_get_channel_count_obj);


// common implementation of bits_per_sample property for audio samples
static mp_obj_t audiosample_obj_get_bits_per_sample(mp_obj_t self_in) {
    audiosample_base_t *self = MP_OBJ_TO_PTR(self_in);
    audiosample_check_for_deinit(self);
    return MP_OBJ_NEW_SMALL_INT(audiosample_get_bits_per_sample(self));
}
MP_DEFINE_CONST_FUN_OBJ_1(audiosample_get_bits_per_sample_obj, audiosample_obj_get_bits_per_sample);

MP_PROPERTY_GETTER(audiosample_bits_per_sample_obj,
    (mp_obj_t)&audiosample_get_bits_per_sample_obj);

// common implementation of sample_rate property for audio samples
static mp_obj_t audiosample_obj_get_sample_rate(mp_obj_t self_in) {
    audiosample_base_t *self = MP_OBJ_TO_PTR(self_in);
    audiosample_check_for_deinit(self);
    return MP_OBJ_NEW_SMALL_INT(audiosample_get_sample_rate(audiosample_check(self_in)));
}
MP_DEFINE_CONST_FUN_OBJ_1(audiosample_get_sample_rate_obj, audiosample_obj_get_sample_rate);

static mp_obj_t audiosample_obj_set_sample_rate(mp_obj_t self_in, mp_obj_t sample_rate) {
    audiosample_base_t *self = MP_OBJ_TO_PTR(self_in);
    audiosample_check_for_deinit(self);
    audiosample_set_sample_rate(audiosample_check(self_in), mp_obj_get_int(sample_rate));
    return mp_const_none;
}
MP_DEFINE_CONST_FUN_OBJ_2(audiosample_set_sample_rate_obj, audiosample_obj_set_sample_rate);

MP_PROPERTY_GETSET(audiosample_sample_rate_obj,
    (mp_obj_t)&audiosample_get_sample_rate_obj,
    (mp_obj_t)&audiosample_set_sample_rate_obj);
