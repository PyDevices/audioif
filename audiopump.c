// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: Copyright (c) 2026 PyDevices
//
// audiopump - the spike's C pull loop, written against audioif's runtime
// neutral sample protocol.
//
// Two jobs, one loop:
//
//   1. `pull()` runs the loop on the calling thread and allocates NOTHING,
//      so `micropython.heap_lock()` around it turns "the audio pull does not
//      allocate" from a claim into a gate. `audiocore.get_buffer()` cannot
//      do this: it m_mallocs a copy of every block (audiocore/module.c), so
//      the harness fails the gate before any node gets a chance to.
//
//   2. `spawn()` runs the same loop on a plain pthread with no interpreter
//      state of any kind, which is the unix stand-in for a FreeRTOS task.
//      Byte identity between the two is the whole proof.
//
// The one thing the loop may not do is call into the MicroPython runtime.
// That rules out `audiosample_get_buffer()`, the funnel every node uses to
// pull the node behind it, because it calls `mp_proto_get_or_throw()` and
// `audiosample_check_for_deinit()` and both of those raise. So the protocol
// is resolved once, on the interpreter thread, into an
// `audioif_sample_source_t`, and the loop calls through that. Node-internal
// pulls still go through the funnel; see the spike notes for what that costs.

#include <fcntl.h>
#include <pthread.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>

#include "py/mperrno.h"
#include "py/obj.h"
#include "py/runtime.h"

#include "audiocore/__init__.h"
#include "shared/audioif_sample.h"

// --- the runtime-neutral part ---------------------------------------------

// Layout of the caller's status bytearray: 8 x uint64_t, little endian,
// written by the loop and read by Python with struct.unpack. A bytearray
// rather than an array() so the width is not a typecode argument.
#define AUDIOPUMP_STATUS_WORDS (8)
#define AUDIOPUMP_STATUS_BYTES (AUDIOPUMP_STATUS_WORDS * 8)

enum {
    STATUS_BLOCKS = 0,      // blocks pulled
    STATUS_BYTES = 1,       // bytes seen
    STATUS_DIGEST = 2,      // FNV-1a 64 over every byte, in order
    STATUS_LAST_RESULT = 3, // last audioif_buffer_result_t
    STATUS_RUNNING = 4,     // 1 while the pump thread is inside the loop
    STATUS_ERROR = 5,       // 0 none, 1 buffer error, 2 null buffer, 3 done
    STATUS_TID = 6,         // pthread_self() of whoever ran the loop
    STATUS_SPARE = 7,
};

typedef struct {
    audioif_sample_source_t source;
    // The adapter the source's context points at. Lives here, not on a
    // stack, because the pump thread outlives the call that built it.
    const audiosample_p_t *protocol;
    mp_obj_t sample;
    uint64_t *status;
    uint64_t blocks;
    int sink_fd;
    bool stop;
} audiopump_ctx_t;

static audiopump_ctx_t audiopump_ctx;
static pthread_t audiopump_thread;
static bool audiopump_thread_live;

// The protocol adapter, as a pair of functions with no MicroPython in them
// beyond the already-resolved function pointers.
static audioif_status_t audiopump_reset(void *context,
    bool single_channel_output, uint8_t audio_channel) {
    audiopump_ctx_t *ctx = context;
    ctx->protocol->reset_buffer(ctx->sample, single_channel_output,
        audio_channel);
    return AUDIOIF_STATUS_OK;
}

static audioif_status_t audiopump_get(void *context,
    bool single_channel_output, uint8_t audio_channel,
    const uint8_t **buffer, uint32_t *buffer_length,
    audioif_buffer_result_t *result) {
    audiopump_ctx_t *ctx = context;
    uint8_t *raw = NULL;
    audioio_get_buffer_result_t got = ctx->protocol->get_buffer(ctx->sample,
        single_channel_output, audio_channel, &raw, buffer_length);
    *buffer = raw;
    *result = (audioif_buffer_result_t)got;
    return AUDIOIF_STATUS_OK;
}

static const audioif_sample_ops_t audiopump_ops = {
    .reset_buffer = audiopump_reset,
    .get_buffer = audiopump_get,
};

// The loop. No mp_* call, no allocation, no libc that could take a lock the
// interpreter also takes. write(2) on the sink is the one syscall.
static void audiopump_run(audiopump_ctx_t *ctx) {
    uint64_t digest = 0xcbf29ce484222325ULL;
    uint64_t blocks = 0;
    uint64_t bytes = 0;
    uint64_t error = 0;
    audioif_buffer_result_t result = AUDIOIF_BUFFER_MORE_DATA;

    ctx->status[STATUS_RUNNING] = 1;
    ctx->status[STATUS_TID] = (uint64_t)(uintptr_t)pthread_self();

    while (blocks < ctx->blocks && !ctx->stop) {
        const uint8_t *buffer = NULL;
        uint32_t length = 0;
        audioif_status_t status = audioif_sample_get(&ctx->source, false, 0,
            &buffer, &length, &result);
        if (status != AUDIOIF_STATUS_OK || result == AUDIOIF_BUFFER_ERROR) {
            error = 1;
            break;
        }
        if (buffer == NULL) {
            error = 2;
            break;
        }
        for (uint32_t i = 0; i < length; i++) {
            digest ^= buffer[i];
            digest *= 0x100000001b3ULL;
        }
        if (ctx->sink_fd >= 0 && length) {
            ssize_t written = write(ctx->sink_fd, buffer, length);
            (void)written;
        }
        bytes += length;
        blocks++;
        // Publish as we go so a watching interpreter sees progress.
        ctx->status[STATUS_BLOCKS] = blocks;
        ctx->status[STATUS_BYTES] = bytes;
        if (result == AUDIOIF_BUFFER_DONE) {
            error = 3;
            break;
        }
    }

    ctx->status[STATUS_DIGEST] = digest;
    ctx->status[STATUS_LAST_RESULT] = (uint64_t)result;
    ctx->status[STATUS_ERROR] = error;
    ctx->status[STATUS_RUNNING] = 0;
}

static void *audiopump_entry(void *arg) {
    audiopump_run((audiopump_ctx_t *)arg);
    return NULL;
}

// --- the MicroPython side, all of it on the interpreter thread ------------

// The pump's pointers are invisible to the collector, so the graph it is
// pulling is rooted here. See the spike notes, "what the pump holds".
MP_REGISTER_ROOT_POINTER(mp_obj_t audiopump_held);

static void audiopump_prepare(mp_obj_t sample, mp_obj_t blocks_in,
    mp_obj_t status_in, audiopump_ctx_t *ctx) {
    mp_buffer_info_t info;
    mp_get_buffer_raise(status_in, &info, MP_BUFFER_WRITE);
    if (info.len < AUDIOPUMP_STATUS_BYTES) {
        mp_raise_ValueError(MP_ERROR_TEXT("status must be 64 bytes"));
    }
    memset(info.buf, 0, AUDIOPUMP_STATUS_BYTES);

    // This is the call that would longjmp on a thread with no interpreter,
    // so it happens here and its result is what the loop carries.
    const audiosample_p_t *protocol = mp_proto_get_or_throw(
        MP_QSTR_protocol_audiosample, sample);
    audiosample_check_for_deinit(MP_OBJ_TO_PTR(sample));

    ctx->protocol = protocol;
    ctx->sample = sample;
    ctx->status = info.buf;
    ctx->blocks = (uint64_t)mp_obj_get_int(blocks_in);
    ctx->sink_fd = -1;
    ctx->stop = false;
    ctx->source.ops = &audiopump_ops;
    ctx->source.context = ctx;
    ctx->source.info = NULL;

    MP_STATE_VM(audiopump_held) = sample;
}

static mp_obj_t audiopump_pull(size_t n_args, const mp_obj_t *args) {
    audiopump_ctx_t ctx;
    audiopump_prepare(args[0], args[1], args[2], &ctx);
    if (n_args > 3 && args[3] != mp_const_none) {
        // Opened here so the loop only ever does write(2).
        const char *path = mp_obj_str_get_str(args[3]);
        ctx.sink_fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
        if (ctx.sink_fd < 0) {
            mp_raise_OSError(MP_ENOENT);
        }
    }
    audiopump_run(&ctx);
    if (ctx.sink_fd >= 0) {
        close(ctx.sink_fd);
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(audiopump_pull_obj, 3, 4,
    audiopump_pull);

static mp_obj_t audiopump_reset_graph(mp_obj_t sample) {
    const audiosample_p_t *protocol = mp_proto_get_or_throw(
        MP_QSTR_protocol_audiosample, sample);
    protocol->reset_buffer(sample, false, 0);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(audiopump_reset_graph_obj,
    audiopump_reset_graph);

static mp_obj_t audiopump_spawn(size_t n_args, const mp_obj_t *args) {
    if (audiopump_thread_live) {
        mp_raise_ValueError(MP_ERROR_TEXT("pump already running"));
    }
    audiopump_prepare(args[0], args[1], args[2], &audiopump_ctx);
    if (n_args > 3 && args[3] != mp_const_none) {
        const char *path = mp_obj_str_get_str(args[3]);
        audiopump_ctx.sink_fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
        if (audiopump_ctx.sink_fd < 0) {
            mp_raise_OSError(MP_ENOENT);
        }
    }
    if (pthread_create(&audiopump_thread, NULL, audiopump_entry,
        &audiopump_ctx) != 0) {
        mp_raise_OSError(MP_EIO);
    }
    audiopump_thread_live = true;
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(audiopump_spawn_obj, 3, 4,
    audiopump_spawn);

static mp_obj_t audiopump_join(void) {
    if (!audiopump_thread_live) {
        return mp_const_none;
    }
    pthread_join(audiopump_thread, NULL);
    audiopump_thread_live = false;
    if (audiopump_ctx.sink_fd >= 0) {
        close(audiopump_ctx.sink_fd);
        audiopump_ctx.sink_fd = -1;
    }
    MP_STATE_VM(audiopump_held) = MP_OBJ_NULL;
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(audiopump_join_obj, audiopump_join);

static mp_obj_t audiopump_stop(void) {
    audiopump_ctx.stop = true;
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(audiopump_stop_obj, audiopump_stop);

static const mp_rom_map_elem_t audiopump_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_audiopump) },
    { MP_ROM_QSTR(MP_QSTR_pull), MP_ROM_PTR(&audiopump_pull_obj) },
    { MP_ROM_QSTR(MP_QSTR_spawn), MP_ROM_PTR(&audiopump_spawn_obj) },
    { MP_ROM_QSTR(MP_QSTR_join), MP_ROM_PTR(&audiopump_join_obj) },
    { MP_ROM_QSTR(MP_QSTR_stop), MP_ROM_PTR(&audiopump_stop_obj) },
    { MP_ROM_QSTR(MP_QSTR_reset), MP_ROM_PTR(&audiopump_reset_graph_obj) },
    { MP_ROM_QSTR(MP_QSTR_STATUS_BYTES),
      MP_ROM_INT(AUDIOPUMP_STATUS_BYTES) },
};
static MP_DEFINE_CONST_DICT(audiopump_globals, audiopump_globals_table);

const mp_obj_module_t audiopump_module = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&audiopump_globals,
};
MP_REGISTER_MODULE(MP_QSTR_audiopump, audiopump_module);
