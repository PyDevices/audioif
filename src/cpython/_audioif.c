// SPDX-License-Identifier: MIT
// Small CPython runtime core used by the public compatibility modules.
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdint.h>
#include <string.h>

#include "shared/audioif_rawsample.h"
#include "shared/audioif_synth_dsp.h"
#include "shared/audioif_envelope.h"
#include "shared/audioif_distortion.h"
#include "shared/audioif_biquad.h"
#include "shared/audioif_echo.h"
#include "shared/audioif_phaser.h"
#include "shared/audioif_chorus.h"
#include "shared/audioif_multitap.h"
#include "shared/audioif_pitchshift.h"
#include "shared/audioif_freeverb.h"

typedef struct {
    PyObject *error;
    PyObject *buffer_owner_type;
    PyObject *rawsample_type;
    PyObject *envelope_state_type;
    PyObject *biquad_state_type;
} audioif_state_t;

typedef struct {
    PyObject_HEAD
    Py_buffer view;
    int acquired;
} audioif_buffer_owner_t;

static int buffer_owner_init(audioif_buffer_owner_t *self, PyObject *args, PyObject *kwargs) {
    PyObject *exporter;
    static char *keywords[] = {"exporter", NULL};
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "O:BufferOwner", keywords, &exporter)) return -1;
    if (self->acquired) {
        PyBuffer_Release(&self->view);
        self->acquired = 0;
    }
    if (PyObject_GetBuffer(exporter, &self->view, PyBUF_FORMAT | PyBUF_C_CONTIGUOUS) < 0) return -1;
    self->acquired = 1;
    return 0;
}

static int buffer_owner_traverse(audioif_buffer_owner_t *self, visitproc visit, void *arg) {
    if (self->acquired) Py_VISIT(self->view.obj);
    return 0;
}

static int buffer_owner_clear(audioif_buffer_owner_t *self) {
    if (self->acquired) {
        PyBuffer_Release(&self->view);
        self->acquired = 0;
    }
    return 0;
}

static void buffer_owner_dealloc(audioif_buffer_owner_t *self) {
    PyObject_GC_UnTrack(self);
    buffer_owner_clear(self);
    Py_TYPE(self)->tp_free((PyObject *)self);
}

static PyObject *buffer_owner_release(audioif_buffer_owner_t *self, PyObject *unused) {
    buffer_owner_clear(self);
    Py_RETURN_NONE;
}

static PyObject *buffer_owner_bytes(audioif_buffer_owner_t *self, PyObject *unused) {
    if (!self->acquired) {
        PyErr_SetString(PyExc_RuntimeError, "buffer has been released");
        return NULL;
    }
    return PyBytes_FromStringAndSize((const char *)self->view.buf, self->view.len);
}

static PyObject *buffer_owner_format(audioif_buffer_owner_t *self, void *closure) {
    if (!self->acquired) Py_RETURN_NONE;
    return PyUnicode_FromString(self->view.format == NULL ? "B" : self->view.format);
}

static PyObject *buffer_owner_nbytes(audioif_buffer_owner_t *self, void *closure) {
    return PyLong_FromSsize_t(self->acquired ? self->view.len : 0);
}

static PyObject *buffer_owner_itemsize(audioif_buffer_owner_t *self, void *closure) {
    return PyLong_FromSsize_t(self->acquired ? self->view.itemsize : 0);
}

static PyMethodDef buffer_owner_methods[] = {
    {"release", (PyCFunction)buffer_owner_release, METH_NOARGS, NULL},
    {"bytes", (PyCFunction)buffer_owner_bytes, METH_NOARGS, NULL},
    {NULL, NULL, 0, NULL},
};

static PyGetSetDef buffer_owner_getset[] = {
    {"format", (getter)buffer_owner_format, NULL, NULL, NULL},
    {"nbytes", (getter)buffer_owner_nbytes, NULL, NULL, NULL},
    {"itemsize", (getter)buffer_owner_itemsize, NULL, NULL, NULL},
    {NULL, NULL, NULL, NULL, NULL},
};

static PyType_Slot buffer_owner_slots[] = {
    {Py_tp_new, PyType_GenericNew},
    {Py_tp_init, buffer_owner_init},
    {Py_tp_dealloc, buffer_owner_dealloc},
    {Py_tp_traverse, buffer_owner_traverse},
    {Py_tp_clear, buffer_owner_clear},
    {Py_tp_methods, buffer_owner_methods},
    {Py_tp_getset, buffer_owner_getset},
    {0, NULL},
};

static PyType_Spec buffer_owner_spec = {
    .name = "_audioif.BufferOwner",
    .basicsize = sizeof(audioif_buffer_owner_t),
    .flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HEAPTYPE | Py_TPFLAGS_HAVE_GC,
    .slots = buffer_owner_slots,
};

typedef struct {
    PyObject_HEAD
    Py_buffer exporter;
    int acquired;
    audioif_sample_info_t info;
    audioif_rawsample_state_t state;
} audioif_rawsample_object_t;

static int rawsample_raise_status(audioif_status_t status) {
    if (status == AUDIOIF_STATUS_DEINITIALIZED) {
        PyErr_SetString(PyExc_RuntimeError,
            "Object has been deinitialized and can no longer be used");
    } else {
        PyErr_SetString(PyExc_RuntimeError, "audio sample operation failed");
    }
    return -1;
}

static int rawsample_init(audioif_rawsample_object_t *self,
    PyObject *args, PyObject *kwargs) {
    PyObject *exporter;
    int channel_count = 1;
    unsigned int sample_rate = 8000;
    int single_buffer = 1;
    static char *keywords[] = {
        "buffer", "channel_count", "sample_rate", "single_buffer", NULL
    };
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "O|$iIp:RawSample",
        keywords, &exporter, &channel_count, &sample_rate, &single_buffer)) {
        return -1;
    }
    if (channel_count != 1 && channel_count != 2) {
        PyErr_SetString(PyExc_ValueError, "channel_count must be 1 or 2");
        return -1;
    }
    if (sample_rate < 1) {
        PyErr_SetString(PyExc_ValueError, "sample_rate must be at least 1");
        return -1;
    }

    Py_buffer view = {0};
    if (PyObject_GetBuffer(exporter, &view,
        PyBUF_FORMAT | PyBUF_C_CONTIGUOUS) < 0) {
        return -1;
    }
    const char *format = view.format == NULL ? "B" : view.format;
    bool samples_signed = format[0] == 'b' || format[0] == 'h';
    if (!((format[0] == 'b' || format[0] == 'B') && format[1] == '\0') &&
        !((format[0] == 'h' || format[0] == 'H') && format[1] == '\0')) {
        PyBuffer_Release(&view);
        PyErr_SetString(PyExc_ValueError,
            "buffer must be a bytearray or array of type 'h', 'H', 'b', or 'B'");
        return -1;
    }
    uint8_t bytes_per_sample = (format[0] == 'h' || format[0] == 'H') ? 2 : 1;
    if (!single_buffer &&
        view.len % (bytes_per_sample * channel_count * 2) != 0) {
        PyBuffer_Release(&view);
        PyErr_SetString(PyExc_ValueError,
            "Length of buffer must be an even multiple of channel_count * type_size");
        return -1;
    }
    if (view.len > UINT32_MAX) {
        PyBuffer_Release(&view);
        PyErr_SetString(PyExc_OverflowError, "buffer is too large");
        return -1;
    }

    if (self->acquired) {
        audioif_rawsample_deinit(&self->state);
        PyBuffer_Release(&self->exporter);
    }
    self->exporter = view;
    self->acquired = 1;
    audioif_rawsample_construct(&self->state, &self->info,
        (uint8_t *)view.buf, (uint32_t)view.len, bytes_per_sample,
        samples_signed, (uint8_t)channel_count, sample_rate, single_buffer);
    return 0;
}

static int rawsample_traverse(audioif_rawsample_object_t *self,
    visitproc visit, void *arg) {
    if (self->acquired) Py_VISIT(self->exporter.obj);
    return 0;
}

static int rawsample_clear(audioif_rawsample_object_t *self) {
    audioif_rawsample_deinit(&self->state);
    if (self->acquired) {
        PyBuffer_Release(&self->exporter);
        self->acquired = 0;
    }
    return 0;
}

static void rawsample_dealloc(audioif_rawsample_object_t *self) {
    PyObject_GC_UnTrack(self);
    rawsample_clear(self);
    Py_TYPE(self)->tp_free((PyObject *)self);
}

static PyObject *rawsample_deinit(audioif_rawsample_object_t *self,
    PyObject *unused) {
    rawsample_clear(self);
    Py_RETURN_NONE;
}

static PyObject *rawsample_reset_buffer(audioif_rawsample_object_t *self,
    PyObject *args, PyObject *kwargs) {
    int single_channel_output = 0;
    unsigned int audio_channel = 0;
    static char *keywords[] = {
        "single_channel_output", "audio_channel", NULL
    };
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|pI:_reset_buffer",
        keywords, &single_channel_output, &audio_channel)) return NULL;
    audioif_sample_source_t source = audioif_rawsample_source(&self->state);
    audioif_status_t status = audioif_sample_reset(&source,
        single_channel_output, (uint8_t)audio_channel);
    if (status != AUDIOIF_STATUS_OK) {
        rawsample_raise_status(status);
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject *rawsample_get_buffer(audioif_rawsample_object_t *self,
    PyObject *args, PyObject *kwargs) {
    int single_channel_output = 0;
    unsigned int audio_channel = 0;
    static char *keywords[] = {
        "single_channel_output", "audio_channel", NULL
    };
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|pI:_get_buffer",
        keywords, &single_channel_output, &audio_channel)) return NULL;

    audioif_sample_source_t source = audioif_rawsample_source(&self->state);
    const uint8_t *buffer = NULL;
    uint32_t buffer_length = 0;
    audioif_buffer_result_t result = AUDIOIF_BUFFER_ERROR;
    audioif_status_t status = audioif_sample_get(&source,
        single_channel_output, (uint8_t)audio_channel,
        &buffer, &buffer_length, &result);
    if (status != AUDIOIF_STATUS_OK) {
        rawsample_raise_status(status);
        return NULL;
    }

    PyObject *data;
    if (single_channel_output && self->info.channel_count > 1) {
        const uint32_t width = self->info.bits_per_sample / 8;
        const uint32_t frame_width = width * self->info.channel_count;
        const uint32_t frames = buffer_length / frame_width;
        data = PyBytes_FromStringAndSize(NULL, (Py_ssize_t)frames * width);
        if (data != NULL) {
            uint8_t *destination = (uint8_t *)PyBytes_AS_STRING(data);
            for (uint32_t frame = 0; frame < frames; frame++) {
                memcpy(destination + frame * width,
                    buffer + frame * frame_width, width);
            }
        }
    } else {
        data = PyBytes_FromStringAndSize((const char *)buffer, buffer_length);
    }
    if (data == NULL) return NULL;
    PyObject *tuple = Py_BuildValue("(iN)", (int)result, data);
    return tuple;
}

static PyObject *rawsample_enter(audioif_rawsample_object_t *self,
    PyObject *unused) {
    if (self->state.deinited) {
        rawsample_raise_status(AUDIOIF_STATUS_DEINITIALIZED);
        return NULL;
    }
    return Py_NewRef((PyObject *)self);
}

static PyObject *rawsample_exit(audioif_rawsample_object_t *self,
    PyObject *args) {
    rawsample_clear(self);
    Py_RETURN_NONE;
}

static PyObject *rawsample_get_sample_rate(audioif_rawsample_object_t *self,
    void *closure) {
    if (self->state.deinited) {
        rawsample_raise_status(AUDIOIF_STATUS_DEINITIALIZED);
        return NULL;
    }
    return PyLong_FromUnsignedLong(self->info.sample_rate);
}

static int rawsample_set_sample_rate(audioif_rawsample_object_t *self,
    PyObject *value, void *closure) {
    if (self->state.deinited) return rawsample_raise_status(AUDIOIF_STATUS_DEINITIALIZED);
    unsigned long rate = PyLong_AsUnsignedLong(value);
    if (PyErr_Occurred()) return -1;
    if (rate < 1 || rate > UINT32_MAX) {
        PyErr_SetString(PyExc_ValueError, "sample_rate must be at least 1");
        return -1;
    }
    self->info.sample_rate = (uint32_t)rate;
    return 0;
}

#define RAWSAMPLE_UINT8_GETTER(name, field) \
    static PyObject *rawsample_get_##name(audioif_rawsample_object_t *self, void *closure) { \
        if (self->state.deinited) { \
            rawsample_raise_status(AUDIOIF_STATUS_DEINITIALIZED); \
            return NULL; \
        } \
        return PyLong_FromUnsignedLong(self->info.field); \
    }

RAWSAMPLE_UINT8_GETTER(bits_per_sample, bits_per_sample)
RAWSAMPLE_UINT8_GETTER(channel_count, channel_count)

static PyObject *rawsample_get_samples_signed(audioif_rawsample_object_t *self,
    void *closure) {
    return PyBool_FromLong(self->info.samples_signed);
}

static PyObject *rawsample_get_single_buffer(audioif_rawsample_object_t *self,
    void *closure) {
    return PyBool_FromLong(self->info.single_buffer);
}

static PyMethodDef rawsample_methods[] = {
    {"deinit", (PyCFunction)rawsample_deinit, METH_NOARGS, NULL},
    {"_reset_buffer", (PyCFunction)rawsample_reset_buffer, METH_VARARGS | METH_KEYWORDS, NULL},
    {"_get_buffer", (PyCFunction)rawsample_get_buffer, METH_VARARGS | METH_KEYWORDS, NULL},
    {"__enter__", (PyCFunction)rawsample_enter, METH_NOARGS, NULL},
    {"__exit__", (PyCFunction)rawsample_exit, METH_VARARGS, NULL},
    {NULL, NULL, 0, NULL},
};

static PyGetSetDef rawsample_getset[] = {
    {"sample_rate", (getter)rawsample_get_sample_rate, (setter)rawsample_set_sample_rate, NULL, NULL},
    {"bits_per_sample", (getter)rawsample_get_bits_per_sample, NULL, NULL, NULL},
    {"channel_count", (getter)rawsample_get_channel_count, NULL, NULL, NULL},
    {"samples_signed", (getter)rawsample_get_samples_signed, NULL, NULL, NULL},
    {"single_buffer", (getter)rawsample_get_single_buffer, NULL, NULL, NULL},
    {NULL, NULL, NULL, NULL, NULL},
};

static PyType_Slot rawsample_slots[] = {
    {Py_tp_new, PyType_GenericNew},
    {Py_tp_init, rawsample_init},
    {Py_tp_dealloc, rawsample_dealloc},
    {Py_tp_traverse, rawsample_traverse},
    {Py_tp_clear, rawsample_clear},
    {Py_tp_methods, rawsample_methods},
    {Py_tp_getset, rawsample_getset},
    {0, NULL},
};

static PyType_Spec rawsample_spec = {
    .name = "audiocore.RawSample",
    .basicsize = sizeof(audioif_rawsample_object_t),
    .flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HEAPTYPE | Py_TPFLAGS_HAVE_GC,
    .slots = rawsample_slots,
};

typedef struct {
    PyObject_HEAD
    audioif_envelope_definition_t definition;
    audioif_envelope_state_t state;
} audioif_envelope_state_object_t;

static int envelope_state_init(audioif_envelope_state_object_t *self,
    PyObject *args, PyObject *kwargs) {
    unsigned int sample_rate;
    int enabled;
    double attack_time = 0, decay_time = 0, release_time = 0;
    double attack_level = 1, sustain_level = 1;
    static char *keywords[] = {
        "sample_rate", "enabled", "attack_time", "decay_time",
        "release_time", "attack_level", "sustain_level", NULL
    };
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "Ip|ddddd:EnvelopeState",
        keywords, &sample_rate, &enabled, &attack_time, &decay_time,
        &release_time, &attack_level, &sustain_level)) return -1;
    audioif_envelope_definition_init(&self->definition, sample_rate, enabled,
        attack_time, decay_time, release_time, attack_level, sustain_level);
    audioif_envelope_state_init(&self->state, &self->definition);
    return 0;
}

static PyObject *envelope_state_step(audioif_envelope_state_object_t *self,
    PyObject *argument) {
    size_t count = PyLong_AsSize_t(argument);
    if (PyErr_Occurred()) return NULL;
    audioif_envelope_state_step(&self->state, &self->definition, count);
    Py_RETURN_NONE;
}

static PyObject *envelope_state_release(audioif_envelope_state_object_t *self,
    PyObject *unused) {
    audioif_envelope_state_release(&self->state);
    Py_RETURN_NONE;
}

static PyObject *envelope_state_level(audioif_envelope_state_object_t *self,
    void *closure) {
    return PyLong_FromLong(self->state.level);
}

static PyObject *envelope_state_kind(audioif_envelope_state_object_t *self,
    void *closure) {
    return PyLong_FromLong(self->state.state);
}

static PyMethodDef envelope_state_methods[] = {
    {"step", (PyCFunction)envelope_state_step, METH_O, NULL},
    {"release", (PyCFunction)envelope_state_release, METH_NOARGS, NULL},
    {NULL, NULL, 0, NULL},
};

static PyGetSetDef envelope_state_getset[] = {
    {"level", (getter)envelope_state_level, NULL, NULL, NULL},
    {"state", (getter)envelope_state_kind, NULL, NULL, NULL},
    {NULL, NULL, NULL, NULL, NULL},
};

static PyType_Slot envelope_state_slots[] = {
    {Py_tp_new, PyType_GenericNew},
    {Py_tp_init, envelope_state_init},
    {Py_tp_methods, envelope_state_methods},
    {Py_tp_getset, envelope_state_getset},
    {0, NULL},
};

static PyType_Spec envelope_state_spec = {
    .name = "_audioif.EnvelopeState",
    .basicsize = sizeof(audioif_envelope_state_object_t),
    .flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HEAPTYPE,
    .slots = envelope_state_slots,
};

typedef struct {
    PyObject_HEAD
    audioif_biquad_state_t state;
} audioif_biquad_state_object_t;

static int biquad_state_init(audioif_biquad_state_object_t *self,
    PyObject *args, PyObject *kwargs) {
    if (!PyArg_ParseTuple(args, ":BiquadState")) return -1;
    memset(&self->state, 0, sizeof(self->state));
    return 0;
}

static PyObject *biquad_state_reset(audioif_biquad_state_object_t *self,
    PyObject *unused) {
    audioif_biquad_reset(&self->state);
    Py_RETURN_NONE;
}

static PyObject *biquad_state_process(audioif_biquad_state_object_t *self,
    PyObject *args) {
    Py_buffer input = {0};
    int mode;
    double frequency, Q, A;
    unsigned int sample_rate;
    if (!PyArg_ParseTuple(args, "y*idddI:process_i32", &input, &mode,
        &frequency, &Q, &A, &sample_rate)) return NULL;
    if (input.len % sizeof(int32_t) || mode < 0 || mode > 6 ||
        sample_rate < 1) {
        PyBuffer_Release(&input);
        PyErr_SetString(PyExc_ValueError, "invalid biquad parameters");
        return NULL;
    }
    PyObject *result = PyBytes_FromStringAndSize((const char *)input.buf,
        input.len);
    PyBuffer_Release(&input);
    if (result == NULL) return NULL;
    audioif_biquad_coefficients_t coefficients;
    audioif_biquad_configure(&coefficients, mode, frequency, Q, A,
        sample_rate);
    audioif_biquad_process(&coefficients, &self->state,
        (int32_t *)PyBytes_AS_STRING(result),
        PyBytes_GET_SIZE(result) / sizeof(int32_t));
    return result;
}

static PyObject *biquad_state_process_s16(audioif_biquad_state_object_t *self,
    PyObject *args) {
    Py_buffer input = {0};
    int mode;
    double frequency, Q, A, mix;
    unsigned int sample_rate;
    if (!PyArg_ParseTuple(args, "y*idddId:process_s16", &input, &mode,
        &frequency, &Q, &A, &sample_rate, &mix)) return NULL;
    if (input.len % sizeof(int16_t) || mode < 0 || mode > 6 ||
        sample_rate < 1) {
        PyBuffer_Release(&input);
        PyErr_SetString(PyExc_ValueError, "invalid biquad parameters");
        return NULL;
    }
    Py_ssize_t count = input.len / sizeof(int16_t);
    int32_t *working = PyMem_Malloc((size_t)count * sizeof(int32_t));
    if (working == NULL) {
        PyBuffer_Release(&input);
        return PyErr_NoMemory();
    }
    const int16_t *source = input.buf;
    for (Py_ssize_t i = 0; i < count; i++) working[i] = source[i];
    audioif_biquad_coefficients_t coefficients;
    audioif_biquad_configure(&coefficients, mode, frequency, Q, A,
        sample_rate);
    audioif_biquad_process(&coefficients, &self->state, working, count);
    PyObject *result = PyBytes_FromStringAndSize(NULL, input.len);
    if (result != NULL) {
        int16_t *destination = (int16_t *)PyBytes_AS_STRING(result);
        int32_t scale = 0x0fffffff / (32768 * 2 - 28000);
        for (Py_ssize_t i = 0; i < count; i++) {
            int32_t combined = (int32_t)(source[i] * (1.0 - mix) +
                working[i] * mix);
            destination[i] = audioif_mix_down_sample(combined, scale,
                -28000, 28000);
        }
    }
    PyMem_Free(working);
    PyBuffer_Release(&input);
    return result;
}

static PyMethodDef biquad_state_methods[] = {
    {"reset", (PyCFunction)biquad_state_reset, METH_NOARGS, NULL},
    {"process_i32", (PyCFunction)biquad_state_process, METH_VARARGS, NULL},
    {"process_s16", (PyCFunction)biquad_state_process_s16, METH_VARARGS, NULL},
    {NULL, NULL, 0, NULL},
};

static PyType_Slot biquad_state_slots[] = {
    {Py_tp_new, PyType_GenericNew},
    {Py_tp_init, biquad_state_init},
    {Py_tp_methods, biquad_state_methods},
    {0, NULL},
};

static PyType_Spec biquad_state_spec = {
    .name = "_audioif.BiquadState",
    .basicsize = sizeof(audioif_biquad_state_object_t),
    .flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HEAPTYPE,
    .slots = biquad_state_slots,
};

static PyObject *audioif_mix_s16(PyObject *module, PyObject *args) {
    Py_buffer left = {0};
    Py_buffer right = {0};
    if (!PyArg_ParseTuple(args, "y*y*:mix_s16", &left, &right)) {
        return NULL;
    }
    if (left.len != right.len || left.len % 2) {
        PyBuffer_Release(&left);
        PyBuffer_Release(&right);
        PyErr_SetString(PyExc_ValueError, "buffers must have the same even byte length");
        return NULL;
    }
    PyObject *result = PyBytes_FromStringAndSize(NULL, left.len);
    if (result == NULL) {
        PyBuffer_Release(&left);
        PyBuffer_Release(&right);
        return NULL;
    }
    const int16_t *a = (const int16_t *)left.buf;
    const int16_t *b = (const int16_t *)right.buf;
    int16_t *out = (int16_t *)PyBytes_AS_STRING(result);
    for (Py_ssize_t i = 0; i < left.len / 2; i++) {
        int32_t value = (int32_t)a[i] + (int32_t)b[i];
        if (value > INT16_MAX) value = INT16_MAX;
        if (value < INT16_MIN) value = INT16_MIN;
        out[i] = (int16_t)value;
    }
    PyBuffer_Release(&left);
    PyBuffer_Release(&right);
    return result;
}

static PyObject *audioif_oscillator_i32(PyObject *module, PyObject *args) {
    PyObject *waveform_object;
    unsigned int accumulator, dds_rate, waveform_start, waveform_end;
    int loudness_left, loudness_right;
    unsigned int channel_count, duration;
    if (!PyArg_ParseTuple(args, "OIIIIiiII:oscillator_i32",
        &waveform_object, &accumulator, &dds_rate, &waveform_start,
        &waveform_end, &loudness_left, &loudness_right, &channel_count,
        &duration)) return NULL;
    if ((channel_count != 1 && channel_count != 2) || duration > UINT16_MAX ||
        loudness_left < INT16_MIN || loudness_left > INT16_MAX ||
        loudness_right < INT16_MIN || loudness_right > INT16_MAX) {
        PyErr_SetString(PyExc_ValueError, "invalid oscillator parameters");
        return NULL;
    }

    Py_buffer waveform = {0};
    if (PyObject_GetBuffer(waveform_object, &waveform,
        PyBUF_FORMAT | PyBUF_C_CONTIGUOUS) < 0) return NULL;
    const char *format = waveform.format == NULL ? "" : waveform.format;
    uint32_t waveform_length = (uint32_t)(waveform.len / sizeof(int16_t));
    if (strcmp(format, "h") != 0 || waveform.len % sizeof(int16_t) ||
        waveform_start >= waveform_end || waveform_end > waveform_length) {
        PyBuffer_Release(&waveform);
        PyErr_SetString(PyExc_ValueError,
            "waveform must be a native signed 16-bit buffer with a valid loop");
        return NULL;
    }

    int32_t *voice = PyMem_Calloc(duration, sizeof(int32_t));
    int32_t *output = PyMem_Calloc((size_t)duration * channel_count,
        sizeof(int32_t));
    if (voice == NULL || output == NULL) {
        PyMem_Free(voice);
        PyMem_Free(output);
        PyBuffer_Release(&waveform);
        return PyErr_NoMemory();
    }
    uint32_t next_accumulator = accumulator;
    bool rendered = audioif_oscillator_fill(voice,
        (const int16_t *)waveform.buf, waveform_start, waveform_end, dds_rate,
        &next_accumulator, (uint16_t)duration, 16);
    if (rendered) {
        int16_t loudness[2] = {(int16_t)loudness_left, (int16_t)loudness_right};
        audioif_sum_with_loudness(output, voice, loudness, duration,
            (uint8_t)channel_count);
    }
    PyObject *data = PyBytes_FromStringAndSize((const char *)output,
        (Py_ssize_t)duration * channel_count * sizeof(int32_t));
    PyMem_Free(voice);
    PyMem_Free(output);
    PyBuffer_Release(&waveform);
    if (data == NULL) return NULL;
    return Py_BuildValue("(NI)", data, next_accumulator);
}

static PyObject *audioif_oscillator_raw_i32(PyObject *module, PyObject *args) {
    PyObject *waveform_object;
    unsigned int accumulator, dds_rate, waveform_start, waveform_end, duration;
    if (!PyArg_ParseTuple(args, "OIIIII:oscillator_raw_i32",
        &waveform_object, &accumulator, &dds_rate, &waveform_start,
        &waveform_end, &duration)) return NULL;
    if (duration > UINT16_MAX) {
        PyErr_SetString(PyExc_ValueError, "invalid oscillator duration");
        return NULL;
    }
    Py_buffer waveform = {0};
    if (PyObject_GetBuffer(waveform_object, &waveform,
        PyBUF_FORMAT | PyBUF_C_CONTIGUOUS) < 0) return NULL;
    const char *format = waveform.format == NULL ? "" : waveform.format;
    uint32_t waveform_length = (uint32_t)(waveform.len / sizeof(int16_t));
    if (strcmp(format, "h") != 0 || waveform.len % sizeof(int16_t) ||
        waveform_start >= waveform_end || waveform_end > waveform_length) {
        PyBuffer_Release(&waveform);
        PyErr_SetString(PyExc_ValueError, "invalid oscillator waveform");
        return NULL;
    }
    PyObject *data = PyBytes_FromStringAndSize(NULL,
        (Py_ssize_t)duration * sizeof(int32_t));
    if (data == NULL) {
        PyBuffer_Release(&waveform);
        return NULL;
    }
    memset(PyBytes_AS_STRING(data), 0, PyBytes_GET_SIZE(data));
    uint32_t next_accumulator = accumulator;
    (void)audioif_oscillator_fill((int32_t *)PyBytes_AS_STRING(data),
        (const int16_t *)waveform.buf, waveform_start, waveform_end, dds_rate,
        &next_accumulator, (uint16_t)duration, 16);
    PyBuffer_Release(&waveform);
    return Py_BuildValue("(NI)", data, next_accumulator);
}

static PyObject *audioif_apply_loudness_i32(PyObject *module, PyObject *args) {
    Py_buffer voice = {0};
    int left, right;
    unsigned int channels;
    if (!PyArg_ParseTuple(args, "y*iiI:apply_loudness_i32", &voice,
        &left, &right, &channels)) return NULL;
    if (voice.len % sizeof(int32_t) || (channels != 1 && channels != 2) ||
        left < INT16_MIN || left > INT16_MAX ||
        right < INT16_MIN || right > INT16_MAX) {
        PyBuffer_Release(&voice);
        PyErr_SetString(PyExc_ValueError, "invalid loudness parameters");
        return NULL;
    }
    Py_ssize_t duration = voice.len / sizeof(int32_t);
    PyObject *result = PyBytes_FromStringAndSize(NULL,
        duration * channels * sizeof(int32_t));
    if (result == NULL) {
        PyBuffer_Release(&voice);
        return NULL;
    }
    memset(PyBytes_AS_STRING(result), 0, PyBytes_GET_SIZE(result));
    int16_t loudness[2] = {(int16_t)left, (int16_t)right};
    audioif_sum_with_loudness((int32_t *)PyBytes_AS_STRING(result),
        (const int32_t *)voice.buf, loudness, duration, (uint8_t)channels);
    PyBuffer_Release(&voice);
    return result;
}

static PyObject *audioif_mixdown_i32(PyObject *module, PyObject *args) {
    Py_buffer input = {0};
    unsigned int max_polyphony = 14;
    if (!PyArg_ParseTuple(args, "y*|I:mixdown_i32", &input,
        &max_polyphony)) return NULL;
    if (input.len % sizeof(int32_t) || max_polyphony < 1) {
        PyBuffer_Release(&input);
        PyErr_SetString(PyExc_ValueError,
            "input must contain native signed 32-bit samples");
        return NULL;
    }
    Py_ssize_t count = input.len / sizeof(int32_t);
    PyObject *result = PyBytes_FromStringAndSize(NULL,
        count * sizeof(int16_t));
    if (result == NULL) {
        PyBuffer_Release(&input);
        return NULL;
    }
    int32_t scale = 0x0fffffff / (32768 * (int32_t)max_polyphony - 28000);
    const int32_t *source = input.buf;
    int16_t *destination = (int16_t *)PyBytes_AS_STRING(result);
    for (Py_ssize_t i = 0; i < count; i++) {
        destination[i] = audioif_mix_down_sample(source[i], scale,
            -28000, 28000);
    }
    PyBuffer_Release(&input);
    return result;
}

static PyObject *audioif_pitch_bend_value(PyObject *module, PyObject *args) {
    unsigned int frequency_scaled;
    int bend_value;
    if (!PyArg_ParseTuple(args, "Ii:pitch_bend", &frequency_scaled,
        &bend_value)) return NULL;
    return PyLong_FromUnsignedLong(audioif_pitch_bend(frequency_scaled,
        bend_value));
}

static PyObject *audioif_distortion_s16(PyObject *module, PyObject *args) {
    Py_buffer input = {0};
    double drive, pre_gain, post_gain, mix;
    int mode, soft_clip;
    if (!PyArg_ParseTuple(args, "y*dddipd:distortion_s16", &input,
        &drive, &pre_gain, &post_gain, &mode, &soft_clip, &mix)) return NULL;
    if (input.len % sizeof(int16_t) || mode < AUDIOIF_DISTORTION_CLIP ||
        mode > AUDIOIF_DISTORTION_WAVESHAPE) {
        PyBuffer_Release(&input);
        PyErr_SetString(PyExc_ValueError, "invalid distortion parameters");
        return NULL;
    }
    PyObject *result = PyBytes_FromStringAndSize(NULL, input.len);
    if (result == NULL) {
        PyBuffer_Release(&input);
        return NULL;
    }
    audioif_distortion_process_s16(
        (int16_t *)PyBytes_AS_STRING(result), (const int16_t *)input.buf,
        input.len / sizeof(int16_t), drive, pre_gain, post_gain,
        (audioif_distortion_mode_t)mode, soft_clip, mix);
    PyBuffer_Release(&input);
    return result;
}

static PyObject *audioif_echo_s16(PyObject *module, PyObject *args) {
    Py_buffer input = {0}, delay = {0};
    unsigned int left, right, delay_samples, maximum_samples, rate, channels;
    double decay, mix;
    int frequency_shift;
    if (!PyArg_ParseTuple(args, "y*w*IIIIIddpI:echo_s16", &input, &delay,
        &left, &right, &delay_samples, &maximum_samples, &rate, &decay,
        &mix, &frequency_shift, &channels)) return NULL;
    if (input.len % sizeof(int16_t) || channels < 1 || channels > 2 ||
        delay_samples < 1 || delay_samples > maximum_samples ||
        delay.len < (Py_ssize_t)((size_t)maximum_samples * channels * sizeof(int16_t))) {
        PyBuffer_Release(&input);
        PyBuffer_Release(&delay);
        PyErr_SetString(PyExc_ValueError, "invalid echo parameters");
        return NULL;
    }
    PyObject *result = PyBytes_FromStringAndSize(NULL, input.len);
    if (result == NULL) {
        PyBuffer_Release(&input);
        PyBuffer_Release(&delay);
        return NULL;
    }
    audioif_echo_positions_t positions = {left, right};
    audioif_echo_process_s16((int16_t *)PyBytes_AS_STRING(result),
        (const int16_t *)input.buf, input.len / sizeof(int16_t), delay.buf,
        delay_samples, maximum_samples, rate, decay, mix, frequency_shift,
        (uint8_t)channels, &positions);
    PyBuffer_Release(&input);
    PyBuffer_Release(&delay);
    return Py_BuildValue("(NII)", result, positions.left_position,
        positions.right_position);
}

static PyObject *audioif_phaser_s16(PyObject *module, PyObject *args) {
    Py_buffer input = {0}, feedback_words = {0}, allpass_words = {0};
    unsigned int channels, stages;
    double frequency, nyquist, feedback, mix;
    if (!PyArg_ParseTuple(args, "y*w*w*IIdddd:phaser_s16", &input,
        &feedback_words, &allpass_words, &channels, &stages, &frequency,
        &nyquist, &feedback, &mix)) return NULL;
    if (input.len % sizeof(int16_t) || channels < 1 || channels > 2 ||
        stages < 1 || stages > 255 || nyquist <= 0 ||
        feedback_words.len < (Py_ssize_t)(channels * sizeof(int16_t)) ||
        allpass_words.len <
            (Py_ssize_t)((size_t)channels * stages * sizeof(int16_t))) {
        PyBuffer_Release(&input);
        PyBuffer_Release(&feedback_words);
        PyBuffer_Release(&allpass_words);
        PyErr_SetString(PyExc_ValueError, "invalid phaser parameters");
        return NULL;
    }
    PyObject *result = PyBytes_FromStringAndSize((const char *)input.buf,
        input.len);
    PyBuffer_Release(&input);
    if (result == NULL) {
        PyBuffer_Release(&feedback_words);
        PyBuffer_Release(&allpass_words);
        return NULL;
    }
    audioif_phaser_process_s16((int16_t *)PyBytes_AS_STRING(result),
        PyBytes_GET_SIZE(result) / sizeof(int16_t), feedback_words.buf,
        allpass_words.buf, (uint8_t)channels, (uint8_t)stages, frequency,
        nyquist, feedback, mix);
    PyBuffer_Release(&feedback_words);
    PyBuffer_Release(&allpass_words);
    return result;
}

static PyObject *audioif_chorus_s16(PyObject *module, PyObject *args) {
    Py_buffer input = {0}, delay = {0};
    unsigned int position, delay_samples, maximum_samples;
    int voices;
    double mix;
    if (!PyArg_ParseTuple(args, "y*w*IIIid:chorus_s16", &input, &delay,
        &position, &delay_samples, &maximum_samples, &voices, &mix)) return NULL;
    if (input.len % sizeof(int16_t) || voices < 1 || delay_samples < 1 ||
        delay_samples > maximum_samples || delay.len <
            (Py_ssize_t)((size_t)maximum_samples * sizeof(int16_t))) {
        PyBuffer_Release(&input); PyBuffer_Release(&delay);
        PyErr_SetString(PyExc_ValueError, "invalid chorus parameters");
        return NULL;
    }
    PyObject *result = PyBytes_FromStringAndSize(NULL, input.len);
    if (result == NULL) {
        PyBuffer_Release(&input); PyBuffer_Release(&delay); return NULL;
    }
    position = audioif_chorus_process_s16(
        (int16_t *)PyBytes_AS_STRING(result), input.buf,
        input.len / sizeof(int16_t), delay.buf, position, delay_samples,
        maximum_samples, voices, mix);
    PyBuffer_Release(&input); PyBuffer_Release(&delay);
    return Py_BuildValue("(NI)", result, position);
}

static PyObject *audioif_multitap_s16(PyObject *module, PyObject *args) {
    Py_buffer input = {0}, delay = {0}, offsets = {0}, levels = {0};
    unsigned int position, delay_samples, channels;
    double decay, mix;
    if (!PyArg_ParseTuple(args, "y*w*IIIw*w*dd:multitap_s16", &input,
        &delay, &position, &delay_samples, &channels, &offsets, &levels,
        &decay, &mix)) return NULL;
    size_t tap_count = (size_t)offsets.len / sizeof(uint32_t);
    if (input.len % sizeof(int16_t) || channels < 1 || channels > 2 ||
        delay_samples < 1 || offsets.len % sizeof(uint32_t) ||
        levels.len != (Py_ssize_t)(tap_count * sizeof(double)) ||
        delay.len < (Py_ssize_t)((size_t)delay_samples * channels *
            sizeof(int16_t))) {
        PyBuffer_Release(&input); PyBuffer_Release(&delay);
        PyBuffer_Release(&offsets); PyBuffer_Release(&levels);
        PyErr_SetString(PyExc_ValueError, "invalid multi-tap parameters");
        return NULL;
    }
    PyObject *result = PyBytes_FromStringAndSize(NULL, input.len);
    if (result == NULL) {
        PyBuffer_Release(&input); PyBuffer_Release(&delay);
        PyBuffer_Release(&offsets); PyBuffer_Release(&levels); return NULL;
    }
    position = audioif_multitap_process_s16(
        (int16_t *)PyBytes_AS_STRING(result), input.buf,
        input.len / sizeof(int16_t), delay.buf, position, delay_samples,
        (uint8_t)channels, offsets.buf, levels.buf, tap_count, decay, mix);
    PyBuffer_Release(&input); PyBuffer_Release(&delay);
    PyBuffer_Release(&offsets); PyBuffer_Release(&levels);
    return Py_BuildValue("(NI)", result, position);
}

static PyObject *audioif_pitchshift_s16(PyObject *module, PyObject *args) {
    Py_buffer input = {0}, window = {0}, overlap = {0};
    unsigned int window_samples, overlap_samples, channels, read_rate;
    unsigned int window_index, overlap_index, read_index;
    double mix;
    if (!PyArg_ParseTuple(args, "y*w*w*IIIIIIId:pitchshift_s16", &input,
        &window, &overlap, &window_samples, &overlap_samples, &channels,
        &read_rate, &window_index, &overlap_index, &read_index, &mix)) return NULL;
    if (input.len % sizeof(int16_t) || channels < 1 || channels > 2 ||
        window_samples < 1 || window.len <
            (Py_ssize_t)((size_t)window_samples * channels * sizeof(int16_t)) ||
        overlap.len < (Py_ssize_t)((size_t)overlap_samples * channels *
            sizeof(int16_t))) {
        PyBuffer_Release(&input); PyBuffer_Release(&window);
        PyBuffer_Release(&overlap);
        PyErr_SetString(PyExc_ValueError, "invalid pitch-shift parameters");
        return NULL;
    }
    PyObject *result = PyBytes_FromStringAndSize(NULL, input.len);
    if (result == NULL) {
        PyBuffer_Release(&input); PyBuffer_Release(&window);
        PyBuffer_Release(&overlap); return NULL;
    }
    audioif_pitchshift_positions_t positions = {
        window_index, overlap_index, read_index};
    audioif_pitchshift_process_s16((int16_t *)PyBytes_AS_STRING(result),
        input.buf, input.len / sizeof(int16_t), window.buf, window_samples,
        overlap.buf, overlap_samples, (uint8_t)channels, read_rate, mix,
        &positions);
    PyBuffer_Release(&input); PyBuffer_Release(&window);
    PyBuffer_Release(&overlap);
    return Py_BuildValue("(NIII)", result, positions.window_index,
        positions.overlap_index, positions.read_index);
}

static PyObject *audioif_freeverb_s16(PyObject *module, PyObject *args) {
    Py_buffer input = {0}, comb = {0}, comb_indices = {0}, filters = {0};
    Py_buffer allpass = {0}, allpass_indices = {0};
    double roomsize, damp, mix;
    if (!PyArg_ParseTuple(args, "y*w*w*w*w*w*ddd:freeverb_s16", &input,
        &comb, &comb_indices, &filters, &allpass, &allpass_indices,
        &roomsize, &damp, &mix)) return NULL;
    if (input.len % sizeof(int16_t) ||
        comb.len < AUDIOIF_FREEVERB_COMB_SAMPLES * (Py_ssize_t)sizeof(int16_t) ||
        comb_indices.len < 8 * (Py_ssize_t)sizeof(uint32_t) ||
        filters.len < 8 * (Py_ssize_t)sizeof(int16_t) ||
        allpass.len < AUDIOIF_FREEVERB_ALLPASS_SAMPLES *
            (Py_ssize_t)sizeof(int16_t) ||
        allpass_indices.len < 4 * (Py_ssize_t)sizeof(uint32_t)) {
        PyBuffer_Release(&input); PyBuffer_Release(&comb);
        PyBuffer_Release(&comb_indices); PyBuffer_Release(&filters);
        PyBuffer_Release(&allpass); PyBuffer_Release(&allpass_indices);
        PyErr_SetString(PyExc_ValueError, "invalid freeverb state");
        return NULL;
    }
    PyObject *result = PyBytes_FromStringAndSize(NULL, input.len);
    if (result != NULL) {
        audioif_freeverb_process_s16((int16_t *)PyBytes_AS_STRING(result),
            input.buf, input.len / sizeof(int16_t), comb.buf,
            comb_indices.buf, filters.buf, allpass.buf, allpass_indices.buf,
            roomsize, damp, mix);
    }
    PyBuffer_Release(&input); PyBuffer_Release(&comb);
    PyBuffer_Release(&comb_indices); PyBuffer_Release(&filters);
    PyBuffer_Release(&allpass); PyBuffer_Release(&allpass_indices);
    return result;
}

static PyMethodDef audioif_methods[] = {
    {"mix_s16", audioif_mix_s16, METH_VARARGS, PyDoc_STR("Saturating mix of two native-endian signed 16-bit PCM buffers.")},
    {"oscillator_i32", audioif_oscillator_i32, METH_VARARGS, NULL},
    {"oscillator_raw_i32", audioif_oscillator_raw_i32, METH_VARARGS, NULL},
    {"apply_loudness_i32", audioif_apply_loudness_i32, METH_VARARGS, NULL},
    {"mixdown_i32", audioif_mixdown_i32, METH_VARARGS, NULL},
    {"pitch_bend", audioif_pitch_bend_value, METH_VARARGS, NULL},
    {"distortion_s16", audioif_distortion_s16, METH_VARARGS, NULL},
    {"echo_s16", audioif_echo_s16, METH_VARARGS, NULL},
    {"phaser_s16", audioif_phaser_s16, METH_VARARGS, NULL},
    {"chorus_s16", audioif_chorus_s16, METH_VARARGS, NULL},
    {"multitap_s16", audioif_multitap_s16, METH_VARARGS, NULL},
    {"pitchshift_s16", audioif_pitchshift_s16, METH_VARARGS, NULL},
    {"freeverb_s16", audioif_freeverb_s16, METH_VARARGS, NULL},
    {NULL, NULL, 0, NULL},
};

static int audioif_exec(PyObject *module) {
    audioif_state_t *state = PyModule_GetState(module);
    state->buffer_owner_type = PyType_FromModuleAndSpec(module, &buffer_owner_spec, NULL);
    if (state->buffer_owner_type == NULL) return -1;
    if (PyModule_AddObjectRef(module, "BufferOwner", state->buffer_owner_type) < 0) return -1;
    state->rawsample_type = PyType_FromModuleAndSpec(module, &rawsample_spec, NULL);
    if (state->rawsample_type == NULL) return -1;
    if (PyModule_AddObjectRef(module, "RawSample", state->rawsample_type) < 0) return -1;
    state->envelope_state_type = PyType_FromModuleAndSpec(module,
        &envelope_state_spec, NULL);
    if (state->envelope_state_type == NULL) return -1;
    if (PyModule_AddObjectRef(module, "EnvelopeState",
        state->envelope_state_type) < 0) return -1;
    state->biquad_state_type = PyType_FromModuleAndSpec(module,
        &biquad_state_spec, NULL);
    if (state->biquad_state_type == NULL) return -1;
    if (PyModule_AddObjectRef(module, "BiquadState",
        state->biquad_state_type) < 0) return -1;
    if (PyModule_AddStringConstant(module, "__version__", "0.0.1") < 0) return -1;
    if (PyModule_AddIntConstant(module, "ABI_VERSION", 1) < 0) return -1;
    return 0;
}

static int audioif_traverse(PyObject *module, visitproc visit, void *arg) {
    audioif_state_t *state = PyModule_GetState(module);
    Py_VISIT(state->error);
    Py_VISIT(state->buffer_owner_type);
    Py_VISIT(state->rawsample_type);
    Py_VISIT(state->envelope_state_type);
    Py_VISIT(state->biquad_state_type);
    return 0;
}

static int audioif_clear(PyObject *module) {
    audioif_state_t *state = PyModule_GetState(module);
    Py_CLEAR(state->error);
    Py_CLEAR(state->buffer_owner_type);
    Py_CLEAR(state->rawsample_type);
    Py_CLEAR(state->envelope_state_type);
    Py_CLEAR(state->biquad_state_type);
    return 0;
}

static PyModuleDef_Slot audioif_slots[] = {
    {Py_mod_exec, audioif_exec},
    {0, NULL},
};

static struct PyModuleDef audioif_module = {
    PyModuleDef_HEAD_INIT,
    .m_name = "_audioif",
    .m_doc = "Private native core for pydevices-audioif.",
    .m_size = sizeof(audioif_state_t),
    .m_methods = audioif_methods,
    .m_slots = audioif_slots,
    .m_traverse = audioif_traverse,
    .m_clear = audioif_clear,
};

PyMODINIT_FUNC PyInit__audioif(void) {
    return PyModuleDef_Init(&audioif_module);
}
