// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: Copyright (c) 2026 PyDevices
//
// audiopump - the spike's C pull loop, written against audioif's runtime
// neutral sample protocol.
//
// Three jobs, one loop:
//
//   1. `pull()` runs the loop on the calling thread and allocates NOTHING,
//      so `micropython.heap_lock()` around it turns "the audio pull does not
//      allocate" from a claim into a gate. `audiocore.get_buffer()` cannot
//      do this: it m_mallocs a copy of every block (audiocore/module.c), so
//      the harness fails the gate before any node gets a chance to.
//
//   2. `spawn()` runs the same loop off the interpreter thread -- a plain
//      pthread on unix, a FreeRTOS task pinned to the core the interpreter
//      is NOT on for esp32. Byte identity between the two is the whole
//      proof.
//
//   3. The loop's sink. On unix that is a file descriptor; on esp32 it is a
//      RAM ring the interpreter drains, an I2S TX channel, or both.
//
// The one thing the loop may not do is call into the MicroPython runtime.
// That rules out `audiosample_get_buffer()`, the funnel every node uses to
// pull the node behind it, because it calls `mp_proto_get_or_throw()` and
// `audiosample_check_for_deinit()` and both of those raise. So the protocol
// is resolved once, on the interpreter thread, into an
// `audioif_sample_source_t`, and the loop calls through that. Node-internal
// pulls still go through the funnel; see the spike notes for what that costs.

#include <stdint.h>
#include <string.h>

#include "py/mperrno.h"
#include "py/mphal.h"
#include "py/obj.h"
#include "py/runtime.h"

#include "audiocore/__init__.h"
#include "shared/audioif_sample.h"

#ifdef ESP_PLATFORM
#include "esp_attr.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/idf_additions.h"
#include "freertos/task.h"
#include "driver/i2s_std.h"
#define AUDIOPUMP_ESP (1)
#else
#include <fcntl.h>
#include <pthread.h>
#include <sched.h>
#include <time.h>
#include <unistd.h>
#define AUDIOPUMP_ESP (0)
#endif

// --- the runtime-neutral part ---------------------------------------------

// Layout of the caller's status bytearray: 24 x uint64_t, little endian,
// written by the loop and read by Python with struct.unpack_from. A
// bytearray rather than an array() so the width is not a typecode argument;
// MicroPython's GC blocks are 16-byte aligned, so the 64-bit stores are too.
#define AUDIOPUMP_STATUS_WORDS (24)
#define AUDIOPUMP_STATUS_BYTES (AUDIOPUMP_STATUS_WORDS * 8)

enum {
    STATUS_BLOCKS = 0,      // blocks pulled
    STATUS_BYTES = 1,       // bytes seen
    STATUS_DIGEST = 2,      // FNV-1a 64 over every byte, in order
    STATUS_LAST_RESULT = 3, // last audioif_buffer_result_t
    STATUS_RUNNING = 4,     // 1 while the pump thread is inside the loop
    STATUS_ERROR = 5,       // 0 none, 1 buffer error, 2 null buffer, 3 done
    STATUS_TID = 6,         // unix: pthread_self(); esp32: the pinned core
    STATUS_PARKED = 7,      // 1 while the pump is parked at a block boundary
    STATUS_RING_W = 8,      // bytes ever written into the ring
    STATUS_RING_R = 9,      // bytes ever drained out of it
    STATUS_RING_OVF = 10,   // blocks the ring had no room for
    STATUS_DRAIN_DIGEST = 11, // FNV-1a 64 over every byte drained, in order
    STATUS_PULL_US = 12,    // time inside audioif_sample_get, microseconds
    STATUS_SINK_US = 13,    // time inside the sink write
    STATUS_SINK_TIMEOUTS = 14,
    STATUS_SINK_BYTES = 15,
    STATUS_WALL_US = 16,    // first block to last, microseconds
    STATUS_PARKS = 17,      // times the pump parked
    STATUS_PARK_US = 18,    // total time parked
    STATUS_STACK_FREE = 19, // uxTaskGetStackHighWaterMark at the end
    STATUS_MAX_PULL_US = 20, // worst single block
    STATUS_DMA_BYTES = 21,  // bytes the I2S DMA actually clocked out
    STATUS_SPARE_22 = 22,
    STATUS_SPARE_23 = 23,
};

#define FNV_OFFSET (0xcbf29ce484222325ULL)
#define FNV_PRIME  (0x100000001b3ULL)

typedef struct {
    audioif_sample_source_t source;
    // The adapter the source's context points at. Lives here, not on a
    // stack, because the pump thread outlives the call that built it.
    const audiosample_p_t *protocol;
    mp_obj_t sample;
    uint64_t *status;
    uint64_t blocks;
    // The RAM ring the interpreter drains. NULL when nobody asked for one.
    uint8_t *ring;
    uint32_t ring_len;
    volatile uint64_t ring_w;
    volatile uint64_t ring_r;
    volatile uint64_t drain_digest;
    volatile bool stop;
    volatile bool park_req;
    volatile bool parked;
    volatile bool finished;
    bool to_sink;               // esp32: write every block to I2S
    uint32_t sink_timeout_ms;
    int sink_fd;                // unix only
} audiopump_ctx_t;

static audiopump_ctx_t audiopump_ctx;

static inline uint64_t audiopump_now_us(void) {
    #if AUDIOPUMP_ESP
    return (uint64_t)esp_timer_get_time();
    #else
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000ULL + (uint64_t)(ts.tv_nsec / 1000);
    #endif
}

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

// --- the I2S sink ---------------------------------------------------------
//
// Opened and closed from Python, exactly as usbif_i2s.c does it and for the
// same reason: the pins, the rate and the slot mode are board facts, and
// board facts stay in Python beside every other board decision.

#if AUDIOPUMP_ESP
static i2s_chan_handle_t audiopump_i2s_tx;
// Written from the driver's ISR, read by the interpreter. Counting what the
// DMA actually clocked out is how an underrun gets measured at all: with
// auto_clear on, a starved descriptor still fires on_sent, so DMA bytes
// running ahead of the bytes the pump supplied IS the underrun.
static volatile uint64_t audiopump_dma_bytes;

static IRAM_ATTR bool audiopump_on_sent(i2s_chan_handle_t handle,
    i2s_event_data_t *event, void *user_ctx) {
    (void)handle;
    (void)user_ctx;
    audiopump_dma_bytes += event->size;
    return false;
}
#endif

// The loop. No mp_* call, no allocation, no libc that could take a lock the
// interpreter also takes.
static void audiopump_run(audiopump_ctx_t *ctx) {
    uint64_t digest = FNV_OFFSET;
    uint64_t blocks = 0;
    uint64_t bytes = 0;
    uint64_t error = 0;
    uint64_t pull_us = 0;
    uint64_t sink_us = 0;
    uint64_t park_us = 0;
    uint64_t max_pull_us = 0;
    uint64_t sink_bytes = 0;
    uint64_t sink_timeouts = 0;
    uint64_t parks = 0;
    uint64_t ring_ovf = 0;
    audioif_buffer_result_t result = AUDIOIF_BUFFER_MORE_DATA;

    ctx->status[STATUS_RUNNING] = 1;
    #if AUDIOPUMP_ESP
    ctx->status[STATUS_TID] = (uint64_t)xPortGetCoreID();
    #else
    ctx->status[STATUS_TID] = (uint64_t)(uintptr_t)pthread_self();
    #endif
    const uint64_t wall_start = audiopump_now_us();

    while (blocks < ctx->blocks && !ctx->stop) {
        // The park, at the block boundary and nowhere else. The control
        // thread asks; the pump finishes the block it is in, says it has
        // parked, and waits. See docs/spikes/live-audio-path-handoff.md.
        if (ctx->park_req) {
            const uint64_t park_start = audiopump_now_us();
            parks++;
            ctx->parked = true;
            ctx->status[STATUS_PARKED] = 1;
            ctx->status[STATUS_PARKS] = parks;
            while (ctx->park_req && !ctx->stop) {
                #if AUDIOPUMP_ESP
                // Not vTaskDelay(1): this port's tick is 100 Hz, so the
                // shortest delay is 10 ms and a parked pump would underrun
                // whatever it is feeding. A direct-to-task notify wakes on
                // the give, in a context switch.
                ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(100));
                #else
                sched_yield();
                #endif
            }
            ctx->parked = false;
            ctx->status[STATUS_PARKED] = 0;
            park_us += audiopump_now_us() - park_start;
            ctx->status[STATUS_PARK_US] = park_us;
            if (ctx->stop) {
                break;
            }
        }

        const uint8_t *buffer = NULL;
        uint32_t length = 0;
        const uint64_t t0 = audiopump_now_us();
        audioif_status_t status = audioif_sample_get(&ctx->source, false, 0,
            &buffer, &length, &result);
        const uint64_t dt = audiopump_now_us() - t0;
        pull_us += dt;
        if (dt > max_pull_us) {
            max_pull_us = dt;
        }
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
            digest *= FNV_PRIME;
        }

        // The ring, if there is one. Single producer (here), single consumer
        // (audiopump.drain on the interpreter thread). Overrun drops the
        // block rather than overwriting what the consumer has not taken, so
        // "the interpreter could not keep up" is a counter rather than a
        // corruption.
        if (ctx->ring != NULL && length) {
            const uint64_t r = ctx->ring_r;
            if (ctx->ring_w - r + length > ctx->ring_len) {
                ring_ovf++;
                ctx->status[STATUS_RING_OVF] = ring_ovf;
            } else {
                uint32_t at = (uint32_t)(ctx->ring_w % ctx->ring_len);
                uint32_t first = ctx->ring_len - at;
                if (first > length) {
                    first = length;
                }
                memcpy(ctx->ring + at, buffer, first);
                if (length > first) {
                    memcpy(ctx->ring, buffer + first, length - first);
                }
                ctx->ring_w += length;
                ctx->status[STATUS_RING_W] = ctx->ring_w;
            }
        }

        #if AUDIOPUMP_ESP
        if (ctx->to_sink && audiopump_i2s_tx != NULL && length) {
            size_t written = 0;
            const uint64_t s0 = audiopump_now_us();
            esp_err_t err = i2s_channel_write(audiopump_i2s_tx, buffer, length,
                &written, pdMS_TO_TICKS(ctx->sink_timeout_ms));
            sink_us += audiopump_now_us() - s0;
            if (err == ESP_ERR_TIMEOUT) {
                sink_timeouts++;
            }
            sink_bytes += written;
        }
        #else
        if (ctx->sink_fd >= 0 && length) {
            const uint64_t s0 = audiopump_now_us();
            ssize_t written = write(ctx->sink_fd, buffer, length);
            sink_us += audiopump_now_us() - s0;
            if (written > 0) {
                sink_bytes += (uint64_t)written;
            }
        }
        #endif

        bytes += length;
        blocks++;
        // Publish as we go so a watching interpreter sees progress.
        ctx->status[STATUS_BLOCKS] = blocks;
        ctx->status[STATUS_BYTES] = bytes;
        ctx->status[STATUS_PULL_US] = pull_us;
        ctx->status[STATUS_SINK_US] = sink_us;
        ctx->status[STATUS_SINK_BYTES] = sink_bytes;
        ctx->status[STATUS_SINK_TIMEOUTS] = sink_timeouts;
        ctx->status[STATUS_MAX_PULL_US] = max_pull_us;
        #if AUDIOPUMP_ESP
        ctx->status[STATUS_DMA_BYTES] = audiopump_dma_bytes;
        #endif
        if (result == AUDIOIF_BUFFER_DONE) {
            error = 3;
            break;
        }
    }

    ctx->status[STATUS_WALL_US] = audiopump_now_us() - wall_start;
    ctx->status[STATUS_DIGEST] = digest;
    ctx->status[STATUS_LAST_RESULT] = (uint64_t)result;
    ctx->status[STATUS_ERROR] = error;
    #if AUDIOPUMP_ESP
    ctx->status[STATUS_STACK_FREE] = (uint64_t)uxTaskGetStackHighWaterMark(NULL);
    ctx->status[STATUS_DMA_BYTES] = audiopump_dma_bytes;
    #endif
    ctx->status[STATUS_RUNNING] = 0;
    ctx->finished = true;
}

// --- the MicroPython side, all of it on the interpreter thread ------------

// The pump's pointers are invisible to the collector, so everything it
// touches is rooted here: the graph tail, the status bytearray and the ring.
// See the spike notes, "what the pump holds".
MP_REGISTER_ROOT_POINTER(mp_obj_t audiopump_held[3]);

static void audiopump_prepare(mp_obj_t sample, mp_obj_t blocks_in,
    mp_obj_t status_in, mp_obj_t ring_in, audiopump_ctx_t *ctx) {
    mp_buffer_info_t info;
    mp_get_buffer_raise(status_in, &info, MP_BUFFER_WRITE);
    if (info.len < AUDIOPUMP_STATUS_BYTES) {
        mp_raise_ValueError(MP_ERROR_TEXT("status too small"));
    }
    memset(info.buf, 0, AUDIOPUMP_STATUS_BYTES);

    memset(ctx, 0, sizeof(*ctx));

    if (ring_in != MP_OBJ_NULL && ring_in != mp_const_none) {
        mp_buffer_info_t ring;
        mp_get_buffer_raise(ring_in, &ring, MP_BUFFER_WRITE);
        if (ring.len < 64) {
            mp_raise_ValueError(MP_ERROR_TEXT("ring too small"));
        }
        ctx->ring = ring.buf;
        ctx->ring_len = (uint32_t)ring.len;
    }

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
    ctx->sink_timeout_ms = 200;
    ctx->source.ops = &audiopump_ops;
    ctx->source.context = ctx;
    ctx->source.info = NULL;

    MP_STATE_VM(audiopump_held)[0] = sample;
    MP_STATE_VM(audiopump_held)[1] = status_in;
    MP_STATE_VM(audiopump_held)[2] = ring_in;
}

static mp_obj_t audiopump_pull(size_t n_args, const mp_obj_t *args) {
    // The one global context, so drain() and park() mean the same thing
    // whether the loop is on this thread or the pump's.
    audiopump_ctx_t *ctx = &audiopump_ctx;
    audiopump_prepare(args[0], args[1], args[2],
        n_args > 4 ? args[4] : MP_OBJ_NULL, ctx);
    #if !AUDIOPUMP_ESP
    if (n_args > 3 && args[3] != mp_const_none) {
        // Opened here so the loop only ever does write(2).
        const char *path = mp_obj_str_get_str(args[3]);
        ctx->sink_fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
        if (ctx->sink_fd < 0) {
            mp_raise_OSError(MP_ENOENT);
        }
    }
    #else
    if (n_args > 3 && args[3] != mp_const_none && mp_obj_is_true(args[3])) {
        if (audiopump_i2s_tx == NULL) {
            mp_raise_ValueError(MP_ERROR_TEXT("no i2s sink open"));
        }
        ctx->to_sink = true;
    }
    #endif
    audiopump_run(ctx);
    #if !AUDIOPUMP_ESP
    if (ctx->sink_fd >= 0) {
        close(ctx->sink_fd);
        ctx->sink_fd = -1;
    }
    #endif
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(audiopump_pull_obj, 3, 5,
    audiopump_pull);

static mp_obj_t audiopump_reset_graph(mp_obj_t sample) {
    const audiosample_p_t *protocol = mp_proto_get_or_throw(
        MP_QSTR_protocol_audiosample, sample);
    protocol->reset_buffer(sample, false, 0);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(audiopump_reset_graph_obj,
    audiopump_reset_graph);

// What the graph says it is, so the caller can open a sink that matches it
// without guessing. Every field is read straight out of audiosample_base_t.
static mp_obj_t audiopump_info(mp_obj_t sample) {
    (void)mp_proto_get_or_throw(MP_QSTR_protocol_audiosample, sample);
    audiosample_base_t *base = MP_OBJ_TO_PTR(sample);
    mp_obj_t items[6] = {
        mp_obj_new_int_from_uint(base->sample_rate),
        mp_obj_new_int_from_uint(base->channel_count),
        mp_obj_new_int_from_uint(base->bits_per_sample),
        mp_obj_new_int_from_uint(base->max_buffer_length),
        mp_obj_new_bool(base->samples_signed),
        mp_obj_new_bool(base->single_buffer),
    };
    return mp_obj_new_tuple(6, items);
}
static MP_DEFINE_CONST_FUN_OBJ_1(audiopump_info_obj, audiopump_info);

// --- the pump thread ------------------------------------------------------

#if AUDIOPUMP_ESP
static TaskHandle_t audiopump_task_handle;
static bool audiopump_task_psram;

static void audiopump_task(void *arg) {
    audiopump_run((audiopump_ctx_t *)arg);
    // Never self-delete. A WithCaps task must be freed with
    // vTaskDeleteWithCaps, and IDF's own note says to do that from another
    // task's context; join() does it. Suspending here also means the stack
    // high-water mark above is still readable.
    for (;;) {
        vTaskSuspend(NULL);
    }
}
#else
static pthread_t audiopump_thread;
static bool audiopump_thread_live;

static void *audiopump_entry(void *arg) {
    audiopump_run((audiopump_ctx_t *)arg);
    return NULL;
}
#endif

static mp_obj_t audiopump_spawn(size_t n_args, const mp_obj_t *pos_args,
    mp_map_t *kw_args) {
    enum { ARG_sample, ARG_blocks, ARG_status, ARG_sink, ARG_ring, ARG_core,
           ARG_prio, ARG_stack, ARG_psram, ARG_timeout_ms };
    static const mp_arg_t allowed[] = {
        { MP_QSTR_sample,     MP_ARG_REQUIRED | MP_ARG_OBJ, { .u_obj = MP_OBJ_NULL } },
        { MP_QSTR_blocks,     MP_ARG_REQUIRED | MP_ARG_OBJ, { .u_obj = MP_OBJ_NULL } },
        { MP_QSTR_status,     MP_ARG_REQUIRED | MP_ARG_OBJ, { .u_obj = MP_OBJ_NULL } },
        { MP_QSTR_sink,       MP_ARG_OBJ,  { .u_obj = mp_const_none } },
        { MP_QSTR_ring,       MP_ARG_OBJ,  { .u_obj = mp_const_none } },
        { MP_QSTR_core,       MP_ARG_INT,  { .u_int = -1 } },
        { MP_QSTR_prio,       MP_ARG_INT,  { .u_int = 4 } },
        { MP_QSTR_stack,      MP_ARG_INT,  { .u_int = 16384 } },
        { MP_QSTR_psram,      MP_ARG_BOOL, { .u_bool = false } },
        { MP_QSTR_timeout_ms, MP_ARG_INT,  { .u_int = 200 } },
    };
    mp_arg_val_t args[MP_ARRAY_SIZE(allowed)];
    mp_arg_parse_all(n_args, pos_args, kw_args, MP_ARRAY_SIZE(allowed),
        allowed, args);

    #if AUDIOPUMP_ESP
    if (audiopump_task_handle != NULL) {
        mp_raise_ValueError(MP_ERROR_TEXT("pump already running"));
    }
    #else
    if (audiopump_thread_live) {
        mp_raise_ValueError(MP_ERROR_TEXT("pump already running"));
    }
    #endif

    audiopump_prepare(args[ARG_sample].u_obj, args[ARG_blocks].u_obj,
        args[ARG_status].u_obj, args[ARG_ring].u_obj, &audiopump_ctx);
    audiopump_ctx.sink_timeout_ms = (uint32_t)args[ARG_timeout_ms].u_int;

    #if AUDIOPUMP_ESP
    if (mp_obj_is_true(args[ARG_sink].u_obj)) {
        if (audiopump_i2s_tx == NULL) {
            mp_raise_ValueError(MP_ERROR_TEXT("no i2s sink open"));
        }
        audiopump_ctx.to_sink = true;
    }
    int core = args[ARG_core].u_int;
    if (core < 0) {
        // The core the interpreter is NOT on. MP_TASK_COREID is 1 on every
        // dual-core esp32 this workspace builds for.
        core = (xPortGetCoreID() == 0) ? 1 : 0;
    }
    BaseType_t ok;
    audiopump_task_psram = args[ARG_psram].u_bool;
    if (args[ARG_psram].u_bool) {
        ok = xTaskCreatePinnedToCoreWithCaps(audiopump_task, "audiopump",
            (configSTACK_DEPTH_TYPE)args[ARG_stack].u_int, &audiopump_ctx,
            (UBaseType_t)args[ARG_prio].u_int, &audiopump_task_handle,
            (BaseType_t)core, MALLOC_CAP_SPIRAM);
    } else {
        ok = xTaskCreatePinnedToCore(audiopump_task, "audiopump",
            (uint32_t)args[ARG_stack].u_int, &audiopump_ctx,
            (UBaseType_t)args[ARG_prio].u_int, &audiopump_task_handle,
            (BaseType_t)core);
    }
    if (ok != pdPASS) {
        audiopump_task_handle = NULL;
        mp_raise_OSError(MP_ENOMEM);
    }
    return mp_obj_new_int(core);
    #else
    if (args[ARG_sink].u_obj != mp_const_none) {
        const char *path = mp_obj_str_get_str(args[ARG_sink].u_obj);
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
    return mp_obj_new_int(-1);
    #endif
}
static MP_DEFINE_CONST_FUN_OBJ_KW(audiopump_spawn_obj, 3, audiopump_spawn);

static mp_obj_t audiopump_join(size_t n_args, const mp_obj_t *args) {
    uint32_t timeout_ms = n_args > 0 ? (uint32_t)mp_obj_get_int(args[0]) : 30000;
    #if AUDIOPUMP_ESP
    if (audiopump_task_handle == NULL) {
        return mp_const_true;
    }
    uint32_t waited = 0;
    while (!audiopump_ctx.finished && waited < timeout_ms) {
        mp_hal_delay_ms(2);
        waited += 2;
    }
    if (!audiopump_ctx.finished) {
        return mp_const_false;
    }
    // The task is parked in vTaskSuspend by now; deleting it from here is
    // the supported direction.
    TaskHandle_t handle = audiopump_task_handle;
    audiopump_task_handle = NULL;
    if (audiopump_task_psram) {
        // A WithCaps task must be freed with the matching call, and IDF's
        // own note says to do it from another task's context -- which this
        // is. Self-deleting one aborts.
        vTaskDeleteWithCaps(handle);
    } else {
        vTaskDelete(handle);
    }
    #else
    (void)timeout_ms;
    if (!audiopump_thread_live) {
        return mp_const_true;
    }
    pthread_join(audiopump_thread, NULL);
    audiopump_thread_live = false;
    if (audiopump_ctx.sink_fd >= 0) {
        close(audiopump_ctx.sink_fd);
        audiopump_ctx.sink_fd = -1;
    }
    #endif
    MP_STATE_VM(audiopump_held)[0] = MP_OBJ_NULL;
    MP_STATE_VM(audiopump_held)[1] = MP_OBJ_NULL;
    MP_STATE_VM(audiopump_held)[2] = MP_OBJ_NULL;
    return mp_const_true;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(audiopump_join_obj, 0, 1,
    audiopump_join);

static mp_obj_t audiopump_stop(void) {
    audiopump_ctx.stop = true;
    audiopump_ctx.park_req = false;
    #if AUDIOPUMP_ESP
    if (audiopump_task_handle != NULL) {
        xTaskNotifyGive(audiopump_task_handle);
    }
    #endif
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(audiopump_stop_obj, audiopump_stop);

// --- the park protocol ----------------------------------------------------
//
// park() returns True when the pump is sitting at a block boundary and will
// not touch the graph again until unpark(). Everything the handoff page
// calls a rewire goes between the two.

static mp_obj_t audiopump_park(size_t n_args, const mp_obj_t *args) {
    uint32_t timeout_us = n_args > 0
        ? (uint32_t)mp_obj_get_int(args[0]) : 100000;
    #if AUDIOPUMP_ESP
    if (audiopump_task_handle == NULL || audiopump_ctx.finished) {
        return mp_const_true;
    }
    #else
    if (!audiopump_thread_live || audiopump_ctx.finished) {
        return mp_const_true;
    }
    #endif
    audiopump_ctx.park_req = true;
    uint32_t waited = 0;
    while (!audiopump_ctx.parked && !audiopump_ctx.finished
           && waited < timeout_us) {
        mp_hal_delay_us(20);
        waited += 20;
    }
    return (audiopump_ctx.parked || audiopump_ctx.finished)
        ? mp_const_true : mp_const_false;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(audiopump_park_obj, 0, 1,
    audiopump_park);

static mp_obj_t audiopump_unpark(void) {
    audiopump_ctx.park_req = false;
    #if AUDIOPUMP_ESP
    if (audiopump_task_handle != NULL) {
        xTaskNotifyGive(audiopump_task_handle);
    }
    #endif
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(audiopump_unpark_obj, audiopump_unpark);

// --- the ring's consumer --------------------------------------------------

static mp_obj_t audiopump_drain(mp_obj_t out_in) {
    mp_buffer_info_t out;
    mp_get_buffer_raise(out_in, &out, MP_BUFFER_WRITE);
    audiopump_ctx_t *ctx = &audiopump_ctx;
    if (ctx->ring == NULL) {
        return MP_OBJ_NEW_SMALL_INT(0);
    }
    uint64_t available = ctx->ring_w - ctx->ring_r;
    uint32_t take = (uint32_t)(available > out.len ? out.len : available);
    if (take == 0) {
        return MP_OBJ_NEW_SMALL_INT(0);
    }
    uint32_t at = (uint32_t)(ctx->ring_r % ctx->ring_len);
    uint32_t first = ctx->ring_len - at;
    if (first > take) {
        first = take;
    }
    memcpy(out.buf, ctx->ring + at, first);
    if (take > first) {
        memcpy((uint8_t *)out.buf + first, ctx->ring, take - first);
    }
    uint64_t digest = ctx->drain_digest ? ctx->drain_digest : FNV_OFFSET;
    const uint8_t *bytes = out.buf;
    for (uint32_t i = 0; i < take; i++) {
        digest ^= bytes[i];
        digest *= FNV_PRIME;
    }
    ctx->drain_digest = digest;
    ctx->ring_r += take;
    ctx->status[STATUS_RING_R] = ctx->ring_r;
    ctx->status[STATUS_DRAIN_DIGEST] = digest;
    return mp_obj_new_int_from_uint(take);
}
static MP_DEFINE_CONST_FUN_OBJ_1(audiopump_drain_obj, audiopump_drain);

// --- the I2S sink, opened from Python -------------------------------------

#if AUDIOPUMP_ESP
static mp_obj_t audiopump_i2s_start(size_t n_args, const mp_obj_t *pos_args,
    mp_map_t *kw_args) {
    enum { ARG_port, ARG_bclk, ARG_ws, ARG_dout, ARG_rate, ARG_bits,
           ARG_channels, ARG_mclk, ARG_mclk_fs, ARG_dma_desc, ARG_dma_frame };
    static const mp_arg_t allowed[] = {
        { MP_QSTR_port,      MP_ARG_REQUIRED | MP_ARG_INT, { .u_int = 0 } },
        { MP_QSTR_bclk,      MP_ARG_REQUIRED | MP_ARG_INT, { .u_int = -1 } },
        { MP_QSTR_ws,        MP_ARG_REQUIRED | MP_ARG_INT, { .u_int = -1 } },
        { MP_QSTR_dout,      MP_ARG_REQUIRED | MP_ARG_INT, { .u_int = -1 } },
        { MP_QSTR_rate,      MP_ARG_REQUIRED | MP_ARG_INT, { .u_int = 48000 } },
        { MP_QSTR_bits,      MP_ARG_INT,  { .u_int = 16 } },
        { MP_QSTR_channels,  MP_ARG_INT,  { .u_int = 2 } },
        { MP_QSTR_mclk,      MP_ARG_INT,  { .u_int = -1 } },
        { MP_QSTR_mclk_fs,   MP_ARG_INT,  { .u_int = 256 } },
        { MP_QSTR_dma_desc,  MP_ARG_INT,  { .u_int = 6 } },
        { MP_QSTR_dma_frame, MP_ARG_INT,  { .u_int = 240 } },
    };
    mp_arg_val_t args[MP_ARRAY_SIZE(allowed)];
    mp_arg_parse_all(n_args, pos_args, kw_args, MP_ARRAY_SIZE(allowed),
        allowed, args);

    if (audiopump_i2s_tx != NULL) {
        mp_raise_ValueError(MP_ERROR_TEXT("i2s already open"));
    }

    i2s_chan_config_t chan_config = I2S_CHANNEL_DEFAULT_CONFIG(
        (i2s_port_t)args[ARG_port].u_int, I2S_ROLE_MASTER);
    chan_config.dma_desc_num = (uint32_t)args[ARG_dma_desc].u_int;
    chan_config.dma_frame_num = (uint32_t)args[ARG_dma_frame].u_int;
    chan_config.auto_clear = true;   // zeros on underrun, never stale data
    esp_err_t err = i2s_new_channel(&chan_config, &audiopump_i2s_tx, NULL);
    if (err != ESP_OK) {
        audiopump_i2s_tx = NULL;
        mp_raise_OSError(MP_EIO);
    }

    const int bits = args[ARG_bits].u_int;
    i2s_std_slot_config_t slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
        bits == 32 ? I2S_DATA_BIT_WIDTH_32BIT :
        (bits == 24 ? I2S_DATA_BIT_WIDTH_24BIT : I2S_DATA_BIT_WIDTH_16BIT),
        args[ARG_channels].u_int == 1 ? I2S_SLOT_MODE_MONO
                                      : I2S_SLOT_MODE_STEREO);
    slot_cfg.slot_mask = I2S_STD_SLOT_BOTH;

    i2s_std_config_t std_cfg = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG((uint32_t)args[ARG_rate].u_int),
        .slot_cfg = slot_cfg,
        .gpio_cfg = {
            .mclk = args[ARG_mclk].u_int < 0 ? I2S_GPIO_UNUSED
                                             : (gpio_num_t)args[ARG_mclk].u_int,
            .bclk = (gpio_num_t)args[ARG_bclk].u_int,
            .ws = (gpio_num_t)args[ARG_ws].u_int,
            .dout = (gpio_num_t)args[ARG_dout].u_int,
            .din = I2S_GPIO_UNUSED,
            .invert_flags = { false, false, false },
        },
    };
    switch (args[ARG_mclk_fs].u_int) {
        case 128: std_cfg.clk_cfg.mclk_multiple = I2S_MCLK_MULTIPLE_128; break;
        case 384: std_cfg.clk_cfg.mclk_multiple = I2S_MCLK_MULTIPLE_384; break;
        case 512: std_cfg.clk_cfg.mclk_multiple = I2S_MCLK_MULTIPLE_512; break;
        default:  std_cfg.clk_cfg.mclk_multiple = I2S_MCLK_MULTIPLE_256; break;
    }

    err = i2s_channel_init_std_mode(audiopump_i2s_tx, &std_cfg);
    if (err == ESP_OK) {
        i2s_event_callbacks_t cbs = { .on_sent = audiopump_on_sent };
        err = i2s_channel_register_event_callback(audiopump_i2s_tx, &cbs, NULL);
    }
    if (err == ESP_OK) {
        audiopump_dma_bytes = 0;
        err = i2s_channel_enable(audiopump_i2s_tx);
    }
    if (err != ESP_OK) {
        i2s_del_channel(audiopump_i2s_tx);
        audiopump_i2s_tx = NULL;
        mp_raise_OSError(MP_EIO);
    }
    // Bytes the DMA holds when full: the block-to-wire latency floor.
    return mp_obj_new_int_from_uint(chan_config.dma_desc_num
        * chan_config.dma_frame_num * (uint32_t)(bits / 8)
        * (uint32_t)(args[ARG_channels].u_int == 1 ? 1 : 2));
}
static MP_DEFINE_CONST_FUN_OBJ_KW(audiopump_i2s_start_obj, 5,
    audiopump_i2s_start);

static mp_obj_t audiopump_i2s_stop(void) {
    if (audiopump_i2s_tx != NULL) {
        i2s_channel_disable(audiopump_i2s_tx);
        i2s_del_channel(audiopump_i2s_tx);
        audiopump_i2s_tx = NULL;
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(audiopump_i2s_stop_obj, audiopump_i2s_stop);

static mp_obj_t audiopump_i2s_dma_bytes(void) {
    return mp_obj_new_int_from_uint((mp_uint_t)audiopump_dma_bytes);
}
static MP_DEFINE_CONST_FUN_OBJ_0(audiopump_i2s_dma_bytes_obj,
    audiopump_i2s_dma_bytes);
#endif

static const mp_rom_map_elem_t audiopump_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_audiopump) },
    { MP_ROM_QSTR(MP_QSTR_pull), MP_ROM_PTR(&audiopump_pull_obj) },
    { MP_ROM_QSTR(MP_QSTR_spawn), MP_ROM_PTR(&audiopump_spawn_obj) },
    { MP_ROM_QSTR(MP_QSTR_join), MP_ROM_PTR(&audiopump_join_obj) },
    { MP_ROM_QSTR(MP_QSTR_stop), MP_ROM_PTR(&audiopump_stop_obj) },
    { MP_ROM_QSTR(MP_QSTR_park), MP_ROM_PTR(&audiopump_park_obj) },
    { MP_ROM_QSTR(MP_QSTR_unpark), MP_ROM_PTR(&audiopump_unpark_obj) },
    { MP_ROM_QSTR(MP_QSTR_drain), MP_ROM_PTR(&audiopump_drain_obj) },
    { MP_ROM_QSTR(MP_QSTR_reset), MP_ROM_PTR(&audiopump_reset_graph_obj) },
    { MP_ROM_QSTR(MP_QSTR_info), MP_ROM_PTR(&audiopump_info_obj) },
    #if AUDIOPUMP_ESP
    { MP_ROM_QSTR(MP_QSTR_i2s_start), MP_ROM_PTR(&audiopump_i2s_start_obj) },
    { MP_ROM_QSTR(MP_QSTR_i2s_stop), MP_ROM_PTR(&audiopump_i2s_stop_obj) },
    { MP_ROM_QSTR(MP_QSTR_i2s_dma_bytes),
      MP_ROM_PTR(&audiopump_i2s_dma_bytes_obj) },
    #endif
    { MP_ROM_QSTR(MP_QSTR_STATUS_BYTES),
      MP_ROM_INT(AUDIOPUMP_STATUS_BYTES) },
    { MP_ROM_QSTR(MP_QSTR_STATUS_WORDS),
      MP_ROM_INT(AUDIOPUMP_STATUS_WORDS) },
};
static MP_DEFINE_CONST_DICT(audiopump_globals, audiopump_globals_table);

const mp_obj_module_t audiopump_module = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&audiopump_globals,
};
MP_REGISTER_MODULE(MP_QSTR_audiopump, audiopump_module);
