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
#include "shared/audioif_pump_lock.h"
#include "shared/audioif_sample.h"

#include "audiopump_events.h"
#include "audiopump_ring.h"
#include "audiopump_tap.h"

// The same acquire/release pair the push ring uses, and here for the same
// reason: `volatile` orders the compiler, not the machine, and a 64-bit store
// on RV32 or Xtensa is two 32-bit stores with a window between them.
#if defined(__GNUC__) || defined(__clang__)
#define AUDIOPUMP_LOAD_ACQ(p)     __atomic_load_n((p), __ATOMIC_ACQUIRE)
#define AUDIOPUMP_STORE_REL(p, v) __atomic_store_n((p), (v), __ATOMIC_RELEASE)
#else
#define AUDIOPUMP_LOAD_ACQ(p)     (*(volatile uint32_t *)(p))
#define AUDIOPUMP_STORE_REL(p, v) (*(volatile uint32_t *)(p) = (v))
#endif

// AUDIOPUMP_ESP32 comes from micropython.cmake, not from the IDF: a user C
// module is compiled without ESP_PLATFORM, and the POSIX branch below LINKS
// on esp32 (newlib has pthread.h), so keying off the wrong macro gets you a
// silently unpinned pump with no sink.
//
// AUDIOPUMP_WASM is the third case and it is a different axis: the
// WebAssembly build we ship has no threads at all (no -pthread, no
// SharedArrayBuffer), so `spawn()` cannot create one. Emscripten still has
// <pthread.h> and pthread_create() still LINKS -- it just aborts the whole
// module at runtime with "Tried to spawn a new thread, but this is not
// supported" -- which is the same "compiles and links, silently wrong" trap
// AUDIOPUMP_ESP32 exists for. So the branch is taken at compile time on
// __EMSCRIPTEN__ and there is no pthread in the binary.
#if defined(AUDIOPUMP_ESP32) || defined(ESP_PLATFORM)
#include "esp_attr.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/idf_additions.h"
#include "freertos/task.h"
#include "driver/i2s_std.h"
#define AUDIOPUMP_ESP (1)
#define AUDIOPUMP_WIN (0)
#define AUDIOPUMP_WASM (0)
#elif defined(_WIN32)
// The windows port, and it is a THIRD branch rather than a few #ifdefs
// inside the POSIX one, because nothing in the POSIX branch survives here:
//
//   MinGW-w64's gcc on this box is thread-model=win32, so <pthread.h>
//   compiles and pthread_create does not link. Even where winpthreads is
//   present it is a shim over the same CreateThread this branch calls
//   directly, with a DLL between the pump and the scheduler.
//
//   MicroPython's windows port has no `_thread` module at all, so the pump
//   being a native C thread is not an optimisation here -- it is the only
//   way a second thread exists in this interpreter.
//
//   mp_hal_delay_us() is DECLARED by py/mphal.h and DEFINED by no file the
//   windows port compiles. Calling it links on unix and fails here, so the
//   park spin below uses this branch's own microsecond sleep.
//
// WIN32_LEAN_AND_MEAN keeps <windows.h> from dragging in the RPC and OLE
// headers, whose `small` and `interface` typedefs collide with ordinary C;
// NOMINMAX keeps its min/max macros away from anything that uses those names.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <process.h>
#include <fcntl.h>
#include <io.h>
#include <sys/stat.h>
#define AUDIOPUMP_ESP (0)
#define AUDIOPUMP_WIN (1)
#define AUDIOPUMP_WASM (0)
#elif defined(__EMSCRIPTEN__)
#include <fcntl.h>
#include <time.h>
#include <unistd.h>
#define AUDIOPUMP_ESP (0)
#define AUDIOPUMP_WIN (0)
#define AUDIOPUMP_WASM (1)
#else
#include <fcntl.h>
#include <pthread.h>
#include <sched.h>
#include <time.h>
#include <unistd.h>
#define AUDIOPUMP_ESP (0)
#define AUDIOPUMP_WIN (0)
#define AUDIOPUMP_WASM (0)
#endif

// "A thread exists to run the loop on." False only on wasm, where the same
// loop is driven from the main thread by audiopump.service().
#define AUDIOPUMP_THREADED (!AUDIOPUMP_WASM)

// --- the runtime-neutral part ---------------------------------------------

// Layout of the caller's status bytearray: 24 x uint64_t, little endian,
// written by the loop and read by Python with struct.unpack_from. A
// bytearray rather than an array() so the width is not a typecode argument;
// MicroPython's GC blocks are 16-byte aligned, so the 64-bit stores are too.
#define AUDIOPUMP_STATUS_WORDS (32)
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
    STATUS_DMA_BYTES = 21,  // bytes the I2S TX DMA actually clocked out
    STATUS_RX_BYTES = 22,   // bytes the I2S RX DMA actually clocked in
    STATUS_IN_TIMEOUTS = 23, // Input blocks the RX channel could not fill
    // --- what audioif's pump lock says (shared/audioif_pump_lock.h) ---
    STATUS_FAULT = 24,          // audioif_pump_fault_get(): why a pull gave up
    STATUS_LOCK_PUMP_WAIT = 25, // worst us the PUMP waited for a control swap
    STATUS_LOCK_CTRL_WAIT = 26, // worst us a CONTROL call waited for a pull
    STATUS_LOCK_CTRL_HELD = 27, // worst us the audio stood still inside a swap
    STATUS_LOCK_PUMP_TAKES = 28,
    STATUS_LOCK_CTRL_TAKES = 29,
    STATUS_FRAMES = 30,         // frames pulled since spawn(), what now() reads
    STATUS_EVENT_US_MAX = 31,   // worst single apply pass at a block boundary
};

#define FNV_OFFSET (0xcbf29ce484222325ULL)
#define FNV_PRIME  (0x100000001b3ULL)

typedef struct {
    audioif_sample_source_t source;
    // The adapter the source's context points at. Lives here, not on a
    // stack, because the pump thread outlives the call that built it.
    const audiosample_p_t *protocol;
    mp_obj_t sample;
    // What the tail looked like when it was adopted. Checked at every block
    // boundary: if the type word behind `sample` is no longer this, the heap
    // that owned the graph has been reused under us and the only safe thing
    // left is to stop. See "teardown on soft reset" in the spike notes --
    // the finaliser below is the mechanism, this is the net under it.
    const void *sample_type;
    uint64_t *status;
    uint64_t blocks;
    // The RAM ring the interpreter drains. NULL when nobody asked for one.
    //
    // 32-BIT COUNTERS, as the push ring's are and for the reason it found:
    // these two words are the protocol between the pump thread and the
    // interpreter, and a 64-bit store is two stores on every 32-bit target we
    // ship. `ring_w - ring_r` in unsigned 32-bit arithmetic is the level even
    // across the wrap. The POSITIONS are tracked separately rather than as
    // `w % ring_len`, because a ring whose length does not divide 2^32 jumps
    // its position when the counter wraps -- at 48 kHz stereo that is once
    // every 6.2 hours, which is the kind of bug a customer finds.
    uint8_t *ring;
    uint32_t ring_len;
    uint32_t ring_w;            // pump stores, interpreter loads
    uint32_t ring_r;            // interpreter stores, pump loads
    uint32_t ring_wpos;         // pump only
    uint32_t ring_rpos;         // interpreter only
    uint64_t ring_w_total;      // pump only: the status word
    uint64_t ring_r_total;      // interpreter only
    uint64_t drain_digest;      // interpreter only
    // The clock, and what rides on it. `frames` is published with a release
    // store and read by audiopump.now(); see audiopump_events.c for why it is
    // 32 bits and what that costs.
    uint32_t frames;
    uint32_t frame_bytes;
    uint32_t block_frames;
    mp_obj_t events;            // an Events queue, or MP_OBJ_NULL
    mp_obj_t tap;               // a Tap, or MP_OBJ_NULL
    volatile bool stop;
    volatile bool park_req;
    volatile bool parked;
    volatile bool finished;
    bool to_sink;               // esp32: write every block to I2S
    uint32_t sink_timeout_ms;
    int sink_fd;                // unix only
    // unix only: hold each block until its wall-clock moment, so the desktop
    // pump runs at the rate a DMA sink would run it at. Nothing on the
    // desktop paces the pump otherwise, and without a pace ANY statement
    // about a Python-timed note being late is a statement about how fast this
    // machine spins. Off by default, and never compiled on esp32, where the
    // sink is the pace.
    bool paced;
    uint32_t pace_rate;
    volatile bool retarget_req; // re-read `sample` at the next block boundary
    // --- what the loop accumulates -------------------------------------
    //
    // These were locals in audiopump_run(). They live here so the SAME loop
    // can be entered a block at a time from audiopump.service() on a port with
    // no thread, and pick up exactly where it left off -- one digest, one
    // block count, one wall clock across every call. The threaded ports still
    // run the loop once, to completion, and never look at `service_mode`.
    uint64_t acc_digest;
    uint64_t acc_blocks;
    uint64_t acc_bytes;
    uint64_t acc_error;
    uint64_t acc_pull_us;
    uint64_t acc_sink_us;
    uint64_t acc_park_us;
    uint64_t acc_max_pull_us;
    uint64_t acc_sink_bytes;
    uint64_t acc_sink_timeouts;
    uint64_t acc_parks;
    uint64_t acc_ring_ovf;
    uint64_t acc_event_us_max;
    uint64_t wall_start;
    audioif_buffer_result_t acc_result;
    bool begun;                 // run_begin() has published the first words
    // wasm: the loop is entered from Python and must never block. It stops
    // when the output ring has no room for another block instead of dropping
    // one -- which is the "make the ring block the pump" fix the desktop
    // driver asks for, in the form a single-threaded port can have it.
    bool service_mode;
    uint32_t max_block_bytes;   // what the tail said it can hand back
    uint64_t park_enter_us;     // wasm: when the park the loop returned on began
} audiopump_ctx_t;

// Why a service() call gave the thread back. Two bits, so the answer and the
// block count fit in one small int and service() need not allocate.
#define AUDIOPUMP_SERVICE_SHIFT (2)
#define AUDIOPUMP_SERVICE_MASK (3)
enum {
    AUDIOPUMP_SERVICE_MORE = 0,   // budget spent; there is more to pull
    AUDIOPUMP_SERVICE_FULL = 1,   // the ring has no room for another block
    AUDIOPUMP_SERVICE_PARKED = 2, // a park was asked for
    AUDIOPUMP_SERVICE_DONE = 3,   // the loop left; status says why
};

static audiopump_ctx_t audiopump_ctx;

#if AUDIOPUMP_WIN
// QueryPerformanceCounter is the only monotonic microsecond clock Windows
// has: GetTickCount64 is one scheduler tick granular (15.6 ms by default --
// three blocks at 48 kHz/256), and timeGetTime is in winmm, which this box
// has wedged. The frequency is fixed for the life of the boot, so it is read
// once; audiopump_prepare() reads it on the interpreter thread before any
// pump thread exists, so the pump never races the initialisation.
//
// The counter is divided BEFORE it is scaled. `ticks * 1000000` overflows a
// signed 64-bit at 9.2e12 ticks, which on a 10 MHz QPC is ten days of
// uptime -- an ordinary desktop reaches it, and the pump would start
// reporting negative block times on a machine nobody had rebooted.
static LARGE_INTEGER audiopump_qpc_freq;
#endif

static inline uint64_t audiopump_now_us(void) {
    #if AUDIOPUMP_ESP
    return (uint64_t)esp_timer_get_time();
    #elif AUDIOPUMP_WIN
    if (audiopump_qpc_freq.QuadPart == 0) {
        QueryPerformanceFrequency(&audiopump_qpc_freq);
    }
    LARGE_INTEGER now;
    QueryPerformanceCounter(&now);
    const uint64_t freq = (uint64_t)audiopump_qpc_freq.QuadPart;
    const uint64_t ticks = (uint64_t)now.QuadPart;
    return (ticks / freq) * 1000000ULL + ((ticks % freq) * 1000000ULL) / freq;
    #else
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000ULL + (uint64_t)(ts.tv_nsec / 1000);
    #endif
}

#if AUDIOPUMP_WIN
// Hold for `wait_us`, accurately. Sleep()'s floor is the scheduler tick, so
// a pump paced with it would stutter by three blocks at a time; a waitable
// timer created with CREATE_WAITABLE_TIMER_HIGH_RESOLUTION is 100 ns
// granular on Windows 10 1803 and later. Where the flag is refused -- an
// older build, or a policy that disallows it -- the timer is created without
// it and the last millisecond is spun out against QPC, which is what the
// unix branch's nanosleep would have given for free.
//
// The handle belongs to whichever thread first paced; it is closed in
// teardown, from the interpreter thread, after the pump has been joined.
#ifndef CREATE_WAITABLE_TIMER_HIGH_RESOLUTION
#define CREATE_WAITABLE_TIMER_HIGH_RESOLUTION (0x00000002)
#endif
static HANDLE audiopump_pace_timer;
static bool audiopump_pace_coarse;

static void audiopump_sleep_us(uint64_t wait_us) {
    if (audiopump_pace_timer == NULL) {
        audiopump_pace_timer = CreateWaitableTimerExW(NULL, NULL,
            CREATE_WAITABLE_TIMER_HIGH_RESOLUTION, TIMER_ALL_ACCESS);
        if (audiopump_pace_timer == NULL) {
            audiopump_pace_timer = CreateWaitableTimerExW(NULL, NULL, 0,
                TIMER_ALL_ACCESS);
            audiopump_pace_coarse = (audiopump_pace_timer != NULL);
        }
    }
    const uint64_t deadline = audiopump_now_us() + wait_us;
    // A coarse timer rounds UP to the tick, so leave it a millisecond of
    // headroom and spin the rest. A high-resolution one gets the lot.
    const uint64_t sleep_us = audiopump_pace_coarse
        ? (wait_us > 1000 ? wait_us - 1000 : 0) : wait_us;
    if (audiopump_pace_timer != NULL && sleep_us) {
        LARGE_INTEGER due;
        due.QuadPart = -(LONGLONG)(sleep_us * 10ULL);   // 100 ns, relative
        if (SetWaitableTimer(audiopump_pace_timer, &due, 0, NULL, NULL,
            FALSE)) {
            WaitForSingleObject(audiopump_pace_timer, INFINITE);
        }
    } else if (audiopump_pace_timer == NULL && wait_us > 2000) {
        // No timer at all: do not burn a core for a whole block. Sleep the
        // whole milliseconds bar one and let the spin below close the gap.
        Sleep((DWORD)((wait_us - 1000) / 1000ULL));
    }
    while (audiopump_now_us() < deadline) {
        YieldProcessor();
    }
}
#endif

#if !AUDIOPUMP_ESP
// The desktop sink is a file descriptor and the loop only ever writes to it.
// On Windows the open carries _O_BINARY, and that is not a detail: without
// it the CRT turns every 0x0A byte of PCM into 0x0D 0x0A on the way out, so
// the file is longer than the audio, every frame after the first newline-
// valued sample is shifted, and the byte-identity proof compares a mangled
// file against a good one. It is the one difference between the two opens.
static int audiopump_sink_open(const char *path) {
    #if AUDIOPUMP_WIN
    return _open(path, _O_WRONLY | _O_CREAT | _O_TRUNC | _O_BINARY,
        _S_IREAD | _S_IWRITE);
    #else
    return open(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    #endif
}

static void audiopump_sink_close(int fd) {
    #if AUDIOPUMP_WIN
    _close(fd);
    #else
    close(fd);
    #endif
}
#endif

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
    // The tail's deinit check, which nothing else does. This adapter calls
    // the protocol DIRECTLY -- that is the whole point of resolving it once
    // on the interpreter thread -- so it bypasses audiosample_get_buffer and
    // the guard that lives there. The guard covers every node INSIDE the
    // graph and not the one the pump is holding.
    //
    // Found by the storm: a class deinit()ing its own Mixer while the pump
    // held it, and mix_down_one_voice writing into word_buffer=0x0. Under
    // the lock now, deinit cannot land mid-pull; this catches the case where
    // it landed between two pulls, which is legitimate and must be silence
    // with a reason rather than a write through NULL.
    if (audiosample_deinited((audiosample_base_t *)MP_OBJ_TO_PTR(ctx->sample))) {
        audioif_pump_fault_set(AUDIOIF_PUMP_FAULT_DEINITED);
        *buffer = NULL;
        *buffer_length = 0;
        *result = AUDIOIF_BUFFER_ERROR;
        return AUDIOIF_STATUS_DEINITIALIZED;
    }
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
// The other half of the same clock tree. i2s_new_channel(&cfg, &tx, &rx)
// fills both handles from one port, so BCLK, WS and MCLK are generated once
// and the capture is frame-aligned with the playback by construction. That
// is what machine.I2S cannot do on this board -- it opens one direction per
// port object, which is why board_peripherals runs its AudioSession with
// duplex=False.
static i2s_chan_handle_t audiopump_i2s_rx;
// Written from the driver's ISR, read by the interpreter. Counting what the
// DMA actually clocked out is how an underrun gets measured at all: with
// auto_clear on, a starved descriptor still fires on_sent, so DMA bytes
// running ahead of the bytes the pump supplied IS the underrun.
static volatile uint64_t audiopump_dma_bytes;
static volatile uint64_t audiopump_rx_bytes;

static IRAM_ATTR bool audiopump_on_sent(i2s_chan_handle_t handle,
    i2s_event_data_t *event, void *user_ctx) {
    (void)handle;
    (void)user_ctx;
    audiopump_dma_bytes += event->size;
    return false;
}

static IRAM_ATTR bool audiopump_on_recv(i2s_chan_handle_t handle,
    i2s_event_data_t *event, void *user_ctx) {
    (void)handle;
    (void)user_ctx;
    audiopump_rx_bytes += event->size;
    return false;
}

static void audiopump_i2s_close(void) {
    if (audiopump_i2s_rx != NULL) {
        i2s_channel_disable(audiopump_i2s_rx);
    }
    if (audiopump_i2s_tx != NULL) {
        i2s_channel_disable(audiopump_i2s_tx);
    }
    if (audiopump_i2s_rx != NULL) {
        i2s_del_channel(audiopump_i2s_rx);
        audiopump_i2s_rx = NULL;
    }
    if (audiopump_i2s_tx != NULL) {
        i2s_del_channel(audiopump_i2s_tx);
        audiopump_i2s_tx = NULL;
    }
}
#endif

// The loop, in three pieces: what it publishes before the first block, the
// blocks themselves, and what it publishes after the last one. A threaded port
// calls all three back to back (audiopump_run below) and never notices the
// seam; wasm calls the middle one once per timer tick.
//
// No mp_* call, no allocation, no libc that could take a lock the interpreter
// also takes -- in the middle piece. That rule is what makes heap_lock() a
// gate, and splitting the function does not relax it.
static void audiopump_run_begin(audiopump_ctx_t *ctx) {
    ctx->acc_digest = FNV_OFFSET;
    ctx->acc_result = AUDIOIF_BUFFER_MORE_DATA;
    ctx->status[STATUS_RUNNING] = 1;
    #if AUDIOPUMP_ESP
    ctx->status[STATUS_TID] = (uint64_t)xPortGetCoreID();
    #elif AUDIOPUMP_WIN
    ctx->status[STATUS_TID] = (uint64_t)GetCurrentThreadId();
    #elif AUDIOPUMP_WASM
    // There is one thread and it is the interpreter's. Saying 0 is the
    // honest answer and it is what the byte-identity probe asserts against:
    // on wasm the pull is NOT off the interpreter thread and the notes say so.
    ctx->status[STATUS_TID] = 0;
    #else
    ctx->status[STATUS_TID] = (uint64_t)(uintptr_t)pthread_self();
    #endif
    ctx->wall_start = audiopump_now_us();
    ctx->begun = true;
}

static void audiopump_run_end(audiopump_ctx_t *ctx) {
    ctx->status[STATUS_WALL_US] = audiopump_now_us() - ctx->wall_start;
    ctx->status[STATUS_DIGEST] = ctx->acc_digest;
    ctx->status[STATUS_LAST_RESULT] = (uint64_t)ctx->acc_result;
    ctx->status[STATUS_ERROR] = ctx->acc_error;
    #if AUDIOPUMP_ESP
    ctx->status[STATUS_STACK_FREE] = (uint64_t)uxTaskGetStackHighWaterMark(NULL);
    ctx->status[STATUS_DMA_BYTES] = audiopump_dma_bytes;
    #endif
    ctx->status[STATUS_RUNNING] = 0;
    ctx->finished = true;
}

// Pull at most `budget` blocks. Returns one of AUDIOPUMP_SERVICE_*; a threaded
// caller passes UINT64_MAX and only ever gets DONE.
static int audiopump_run_blocks(audiopump_ctx_t *ctx, uint64_t budget) {
    uint64_t digest = ctx->acc_digest;
    uint64_t blocks = ctx->acc_blocks;
    uint64_t bytes = ctx->acc_bytes;
    uint64_t error = ctx->acc_error;
    uint64_t pull_us = ctx->acc_pull_us;
    uint64_t sink_us = ctx->acc_sink_us;
    uint64_t park_us = ctx->acc_park_us;
    uint64_t max_pull_us = ctx->acc_max_pull_us;
    uint64_t sink_bytes = ctx->acc_sink_bytes;
    uint64_t sink_timeouts = ctx->acc_sink_timeouts;
    uint64_t parks = ctx->acc_parks;
    uint64_t ring_ovf = ctx->acc_ring_ovf;
    uint64_t event_us_max = ctx->acc_event_us_max;
    audioif_buffer_result_t result = ctx->acc_result;
    const uint64_t wall_start = ctx->wall_start;
    (void)wall_start;   // the pace below is the only reader, and it is unix-only
    uint64_t spent = 0;
    int why = AUDIOPUMP_SERVICE_DONE;

    while (blocks < ctx->blocks && !ctx->stop) {
        if (spent >= budget) {
            why = AUDIOPUMP_SERVICE_MORE;
            break;
        }
        // wasm: the ring is the pace. A block that will not fit is not
        // dropped and not overwritten -- the loop stops and the caller comes
        // back when its drain has made room. On a threaded port the ring
        // still drops, because a thread that stopped here would have to spin.
        if (ctx->service_mode && ctx->ring != NULL) {
            const uint32_t level = ctx->ring_w - ctx->ring_r;
            const uint32_t room = ctx->ring_len - level;
            const uint32_t need = ctx->max_block_bytes ? ctx->max_block_bytes : 1;
            if (room < need) {
                why = AUDIOPUMP_SERVICE_FULL;
                break;
            }
        }
        // The park, at the block boundary and nowhere else. The control
        // thread asks; the pump finishes the block it is in, says it has
        // parked, and waits. See docs/spikes/live-audio-path-handoff.md.
        if (ctx->park_req) {
            #if AUDIOPUMP_WASM
            // Nothing can clear park_req while this call holds the only
            // thread, so waiting here is a hang, not a park. Give the thread
            // back parked, count the park once however many service() calls
            // arrive while it lasts, and charge the time when it ends.
            if (ctx->service_mode) {
                if (!ctx->parked) {
                    parks++;
                    ctx->parked = true;
                    ctx->status[STATUS_PARKED] = 1;
                    ctx->status[STATUS_PARKS] = parks;
                    ctx->acc_parks = parks;
                    ctx->park_enter_us = audiopump_now_us();
                }
                why = AUDIOPUMP_SERVICE_PARKED;
                break;
            }
            #endif
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
                #elif AUDIOPUMP_WIN
                // SwitchToThread, not Sleep(0): Sleep(0) only yields to a
                // thread of equal or higher priority ON THIS CORE, so a
                // parked pump can spin a core against an interpreter the
                // scheduler put elsewhere. SwitchToThread gives the rest of
                // the quantum to any ready thread on any processor.
                SwitchToThread();
                #elif AUDIOPUMP_WASM
                // Unreachable -- service_mode leaves above, and nothing else
                // runs on this port to set park_req. Break rather than spin,
                // so a pull() that somehow got here returns instead of
                // hanging the browser tab. (sched_yield is not declared by
                // emscripten's headers, which is how this was found.)
                break;
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
        #if AUDIOPUMP_WASM
        // The other end of the park above: park_req has gone, so charge the
        // time it lasted and let the block through.
        if (ctx->service_mode && ctx->parked) {
            ctx->parked = false;
            ctx->status[STATUS_PARKED] = 0;
            park_us += audiopump_now_us() - ctx->park_enter_us;
            ctx->status[STATUS_PARK_US] = park_us;
        }
        #endif

        const uint8_t *buffer = NULL;
        uint32_t length = 0;
        const uint64_t t0 = audiopump_now_us();
        // The lock, held for exactly one block pull and nothing else. The
        // control path takes the same lock around its final swap, so a
        // rewire can no longer land in the middle of a pull -- which is what
        // killed Phaser 5 times out of 5 on the desktop and panicked core 0
        // on the P4 at the same statement. Nobody has to call park() for
        // this; the lock is inside audioif, at the write.
        //
        // NOT held across the sink write below: that blocks for up to a DMA
        // block, and holding it there would make every knob wait for the
        // speaker instead of for the arithmetic.
        audioif_pump_lock_acquire_pump();
        // Re-read the tail INSIDE the lock. A retarget that swapped it is
        // holding this lock while it does, so either we see the whole swap or
        // none of it -- the registry entry the handoff page designs, which is
        // one word of state and one lock rather than a park.
        if (ctx->retarget_req) {
            ctx->retarget_req = false;
            ctx->sample_type = (const void *)
                ((mp_obj_base_t *)MP_OBJ_TO_PTR(ctx->sample))->type;
        }
        // The net under the finaliser, and it has to be INSIDE the lock and
        // AFTER the retarget: a retarget to a different class legitimately
        // changes the type word, and checking before the swap was applied
        // called every live class swap a re-inited heap. A type word that is
        // no longer the one adopted, with no retarget pending, does mean the
        // heap holding the graph has been re-inited and re-used: stop, rather
        // than hand the DSP a pointer out of somebody else's object.
        if (ctx->sample_type != NULL
            && (const void *)((mp_obj_base_t *)MP_OBJ_TO_PTR(ctx->sample))->type
               != ctx->sample_type) {
            audioif_pump_lock_release_pump();
            error = 4;
            break;
        }
        // The timestamped events, applied at the top of the block and
        // nowhere else -- inside the lock the pump already holds, so an
        // insert from the interpreter either lands wholly before this pass or
        // wholly after it. Every event whose frame falls inside the block
        // about to be pulled goes now; one already behind goes now too and is
        // counted late. That is block-accurate and no better: the nodes
        // produce fixed-length blocks and splitting one is not a small
        // change. See docs/spikes/live-audio-path-events.md.
        if (ctx->events != MP_OBJ_NULL) {
            const uint64_t e0 = audiopump_now_us();
            (void)audiopump_events_apply(ctx->events, ctx->frames,
                ctx->block_frames);
            const uint64_t edt = audiopump_now_us() - e0;
            if (edt > event_us_max) {
                event_us_max = edt;
                ctx->status[STATUS_EVENT_US_MAX] = event_us_max;
            }
        }
        audioif_status_t status = audioif_sample_get(&ctx->source, false, 0,
            &buffer, &length, &result);
        audioif_pump_lock_release_pump();
        const uint64_t dt = audiopump_now_us() - t0;
        pull_us += dt;
        if (dt > max_pull_us) {
            max_pull_us = dt;
        }
        // A pull no longer raises: audioif's funnel returns GET_BUFFER_ERROR
        // and leaves a code in its fault register instead of longjmping off a
        // thread that has no interpreter state to allocate the exception
        // from. So a deinited node, a missing protocol or a file-backed
        // source in the graph all arrive HERE, as a number, and the pump
        // stops pulling that source and publishes why.
        if (status != AUDIOIF_STATUS_OK || result == AUDIOIF_BUFFER_ERROR) {
            error = 1;
            ctx->status[STATUS_FAULT] = audioif_pump_fault_get();
            break;
        }
        const uint32_t fault = audioif_pump_fault_get();
        if (fault != AUDIOIF_PUMP_FAULT_NONE) {
            // A node swallowed the error into silence -- every node in the
            // palette treats GET_BUFFER_ERROR from its source as "produce
            // zeros" -- so the result came back clean and the graph is quietly
            // wrong. That is the failure worth catching: stop, and say which.
            error = 5;
            ctx->status[STATUS_FAULT] = fault;
            break;
        }
        if (buffer == NULL) {
            error = 2;
            break;
        }
        // A stop that arrived while the pull was running must not be followed
        // by a sink write: the write blocks for up to sink_timeout_ms, and a
        // teardown waiting for this task is waiting exactly that long.
        if (ctx->stop) {
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
            const uint32_t r = AUDIOPUMP_LOAD_ACQ(&ctx->ring_r);
            if (ctx->ring_w - r + length > ctx->ring_len) {
                ring_ovf++;
                ctx->status[STATUS_RING_OVF] = ring_ovf;
            } else {
                uint32_t at = ctx->ring_wpos;
                uint32_t first = ctx->ring_len - at;
                if (first > length) {
                    first = length;
                }
                memcpy(ctx->ring + at, buffer, first);
                if (length > first) {
                    memcpy(ctx->ring, buffer + first, length - first);
                }
                ctx->ring_wpos = (at + length) % ctx->ring_len;
                ctx->ring_w_total += length;
                // Release, and last: the bytes are in place before the
                // interpreter is told they are there.
                AUDIOPUMP_STORE_REL(&ctx->ring_w, ctx->ring_w + length);
                ctx->status[STATUS_RING_W] = ctx->ring_w_total;
            }
        }

        // The tap. One memcpy after the tail, out of the path: nothing the
        // reader does can stall the audio, and a reader that falls behind
        // loses old audio rather than new.
        if (ctx->tap != MP_OBJ_NULL && length) {
            audiopump_tap_write(ctx->tap, buffer, length);
        }

        // The clock. Published AFTER the block is in the ring and in the tap,
        // so now() never names a frame the pump has not finished producing.
        if (ctx->frame_bytes) {
            const uint32_t nframes = length / ctx->frame_bytes;
            if (nframes) {
                ctx->block_frames = nframes;
            }
            AUDIOPUMP_STORE_REL(&ctx->frames, ctx->frames + nframes);
            ctx->status[STATUS_FRAMES] = ctx->frames;
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
            #if AUDIOPUMP_WIN
            const int written = _write(ctx->sink_fd, buffer, (unsigned int)length);
            #else
            ssize_t written = write(ctx->sink_fd, buffer, length);
            #endif
            sink_us += audiopump_now_us() - s0;
            if (written > 0) {
                sink_bytes += (uint64_t)written;
            }
        }
        #endif

        #if !AUDIOPUMP_ESP && !AUDIOPUMP_WASM
        // The pace, if one was asked for: hold until this block's moment.
        // Absolute deadlines against the run's start, so a late block is
        // caught up rather than accumulated -- the same reason the drum
        // machine's step timer uses a deadline and not a sleep.
        if (ctx->paced && ctx->pace_rate && ctx->frame_bytes) {
            const uint64_t due = wall_start
                + (uint64_t)ctx->frames * 1000000ULL / ctx->pace_rate;
            const uint64_t at = audiopump_now_us();
            if (due > at) {
                #if AUDIOPUMP_WIN
                audiopump_sleep_us(due - at);
                #else
                struct timespec ts;
                const uint64_t wait = due - at;
                ts.tv_sec = (time_t)(wait / 1000000ULL);
                ts.tv_nsec = (long)((wait % 1000000ULL) * 1000ULL);
                nanosleep(&ts, NULL);
                #endif
            }
        }
        #endif

        bytes += length;
        blocks++;
        spent++;
        // Publish as we go so a watching interpreter sees progress.
        ctx->status[STATUS_BLOCKS] = blocks;
        ctx->status[STATUS_BYTES] = bytes;
        ctx->status[STATUS_PULL_US] = pull_us;
        ctx->status[STATUS_SINK_US] = sink_us;
        ctx->status[STATUS_SINK_BYTES] = sink_bytes;
        ctx->status[STATUS_SINK_TIMEOUTS] = sink_timeouts;
        ctx->status[STATUS_MAX_PULL_US] = max_pull_us;
        const audioif_pump_lock_stats_t *lock = audioif_pump_lock_stats();
        ctx->status[STATUS_LOCK_PUMP_WAIT] = lock->pump_wait_us_max;
        ctx->status[STATUS_LOCK_CTRL_WAIT] = lock->ctrl_wait_us_max;
        ctx->status[STATUS_LOCK_CTRL_HELD] = lock->ctrl_held_us_max;
        ctx->status[STATUS_LOCK_PUMP_TAKES] = lock->pump_takes;
        ctx->status[STATUS_LOCK_CTRL_TAKES] = lock->ctrl_takes;
        #if AUDIOPUMP_ESP
        ctx->status[STATUS_DMA_BYTES] = audiopump_dma_bytes;
        ctx->status[STATUS_RX_BYTES] = audiopump_rx_bytes;
        #endif
        if (result == AUDIOIF_BUFFER_DONE) {
            error = 3;
            break;
        }
    }

    ctx->acc_digest = digest;
    ctx->acc_blocks = blocks;
    ctx->acc_bytes = bytes;
    ctx->acc_error = error;
    ctx->acc_pull_us = pull_us;
    ctx->acc_sink_us = sink_us;
    ctx->acc_park_us = park_us;
    ctx->acc_max_pull_us = max_pull_us;
    ctx->acc_sink_bytes = sink_bytes;
    ctx->acc_sink_timeouts = sink_timeouts;
    ctx->acc_parks = parks;
    ctx->acc_ring_ovf = ring_ovf;
    ctx->acc_event_us_max = event_us_max;
    ctx->acc_result = result;
    return why;
}

// What every threaded port runs: one call, start to finish.
static void audiopump_run(audiopump_ctx_t *ctx) {
    audiopump_run_begin(ctx);
    (void)audiopump_run_blocks(ctx, UINT64_MAX);
    audiopump_run_end(ctx);
}

// --- the MicroPython side, all of it on the interpreter thread ------------

// The pump's pointers are invisible to the collector, so everything it
// touches is rooted here: the graph tail, the status bytearray, the ring and
// the guard object whose finaliser is the soft-reset teardown.
// See the spike notes, "what the pump holds".
// 4 is the event queue and 5 the tap: the pump holds a raw pointer to each,
// and a queue holding a Note nobody else references any more is exactly the
// case the collector would otherwise be right about.
MP_REGISTER_ROOT_POINTER(mp_obj_t audiopump_held[6]);
#define AUDIOPUMP_HELD_EVENTS (4)
#define AUDIOPUMP_HELD_TAP (5)

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
    audioif_pump_fault_clear();

    ctx->protocol = protocol;
    ctx->sample = sample;
    ctx->sample_type = (const void *)((mp_obj_base_t *)MP_OBJ_TO_PTR(sample))->type;
    // The clock's units, off the graph rather than guessed. `block_frames` is
    // only a seed: the loop replaces it with the length of the block it
    // actually got, every block, so a graph whose tail produces something
    // other than its declared maximum corrects itself on the first pull.
    audiosample_base_t *base = MP_OBJ_TO_PTR(sample);
    // What one pull can hand back. The service loop needs it to know whether
    // the ring has room for another block BEFORE it pulls one, because after
    // the pull there is nowhere to put what it got.
    ctx->max_block_bytes = (uint32_t)base->max_buffer_length;
    ctx->frame_bytes = (uint32_t)base->channel_count
        * (uint32_t)(base->bits_per_sample / 8);
    ctx->block_frames = ctx->frame_bytes
        ? base->max_buffer_length / ctx->frame_bytes : 0;
    if (ctx->block_frames == 0) {
        ctx->block_frames = 1;
    }
    // Whatever was attached stays attached across a respawn: the roots are
    // the authority, not the context, which prepare() has just memset.
    ctx->events = MP_STATE_VM(audiopump_held)[AUDIOPUMP_HELD_EVENTS];
    ctx->tap = MP_STATE_VM(audiopump_held)[AUDIOPUMP_HELD_TAP];
    ctx->status = info.buf;
    // Read the clock once here, on the interpreter thread, before any pump
    // thread exists. On Windows that is what latches QueryPerformanceFrequency
    // -- lazily, from whichever thread asks first -- and doing it here means
    // the pump never races the interpreter for it.
    (void)audiopump_now_us();
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
        ctx->sink_fd = audiopump_sink_open(path);
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
        audiopump_sink_close(ctx->sink_fd);
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
#elif AUDIOPUMP_WIN
// _beginthreadex, not CreateThread. The loop's sink write is a CRT call and
// a CRT thread wants the per-thread state _beginthreadex installs; and the
// handle it returns belongs to the caller, so join() closes it. A
// CreateThread handle dropped on the floor would be one handle leaked per
// spawn, which in a player that stops and starts a note at a time is a leak
// per note.
//
// No priority is raised. On a board the pump runs above the interpreter
// because one core has to be given up; on a desktop there are cores to
// spare, and a pump at ABOVE_NORMAL would starve the very interpreter that
// has to reach shutdown().
static HANDLE audiopump_thread;
static bool audiopump_thread_live;

static unsigned __stdcall audiopump_entry(void *arg) {
    audiopump_run((audiopump_ctx_t *)arg);
    return 0;
}
#elif AUDIOPUMP_WASM
// No thread. `audiopump_service_live` is what `audiopump_thread_live` is on
// unix: "spawn() has adopted a tail and nothing has torn it down yet". The
// loop advances only inside audiopump.service().
static bool audiopump_service_live;
#else
static pthread_t audiopump_thread;
static bool audiopump_thread_live;

static void *audiopump_entry(void *arg) {
    audiopump_run((audiopump_ctx_t *)arg);
    return NULL;
}
#endif

// AUDIOPUMP_THREADED, not !AUDIOPUMP_ESP: the windows branch factored the
// pthread/_beginthreadex difference out into these two, and on wasm there is
// no `audiopump_thread` to start -- `audiopump_service_live` stands in for it
// and spawn() never reaches here.
#if !AUDIOPUMP_ESP && AUDIOPUMP_THREADED
static bool audiopump_thread_start(void) {
    #if AUDIOPUMP_WIN
    audiopump_thread = (HANDLE)_beginthreadex(NULL, 0, audiopump_entry,
        &audiopump_ctx, 0, NULL);
    return audiopump_thread != NULL;
    #else
    return pthread_create(&audiopump_thread, NULL, audiopump_entry,
        &audiopump_ctx) == 0;
    #endif
}

static void audiopump_thread_join(void) {
    #if AUDIOPUMP_WIN
    if (audiopump_thread != NULL) {
        WaitForSingleObject(audiopump_thread, INFINITE);
        CloseHandle(audiopump_thread);
        audiopump_thread = NULL;
    }
    #else
    pthread_join(audiopump_thread, NULL);
    #endif
    audiopump_thread_live = false;
}
#endif

// --- teardown, and the thing that makes it happen on a soft reset ---------
//
// The board half found that a soft reset frees the graph out from under a
// running pump and nothing notices: MicroPython re-inits the GC over the same
// region, the FreeRTOS task is a C task and keeps pulling, and the audio goes
// on until something reuses the memory. A pump that survives the heap that
// owns its graph is worse than one that crashes.
//
// The esp32 port has no hook a user C module can register in its soft-reset
// path -- main.c's soft_reset_exit calls a fixed list of `_deinit()`s and
// there is no MICROPY_BOARD_END_SOFT_RESET on this port. But two lines above
// that list it calls `gc_sweep_all()`, which runs `__del__` on EVERY object
// that has one, reachable or not (py/gc.c:604, gc_sweep_run_finalisers).
// So the cheapest robust mechanism is an object with a finaliser: it is
// rooted here so an ordinary collection never touches it, and a soft reset
// finalises it anyway. No port patch.
//
// Finalisers run before gc_sweep_free_blocks, so the graph is still intact
// while this runs -- and audioif has no finalisers of its own outside
// audiomp3, so nothing can deinit a node ahead of us.

// `release_guard` is true only when the finaliser itself is calling: the guard
// object is being swept, so the root must be dropped or it dangles into a heap
// that is about to be re-inited -- and `arm_guard` would then see a non-NULL
// slot and never make a live one, leaving the NEXT soft reset with nothing to
// finalise. An explicit shutdown() keeps it: the object is still alive and
// still rooted, and unrooting it there would leave it unreachable but not yet
// swept, so the next gc.collect() would finalise it and tear down whatever
// pump had been spawned in between. Two opposite failures, one flag.
static void audiopump_teardown(bool release_guard) {
    audiopump_ctx.stop = true;
    audiopump_ctx.park_req = false;
    audioif_pump_set_active(false);
    #if AUDIOPUMP_ESP
    TaskHandle_t handle = audiopump_task_handle;
    if (handle != NULL) {
        xTaskNotifyGive(handle);
        // The loop checks `stop` at the block boundary and again between the
        // pull and the sink write, so the longest it can be away is one pull.
        // vTaskDelay, not mp_hal_delay_ms: this runs inside a finaliser under
        // the GC mutex, and mp_hal_delay_ms ends in mp_handle_pending, which
        // can raise.
        uint32_t waited = 0;
        while (!audiopump_ctx.finished && waited < 2000) {
            vTaskDelay(1);      // 10 ms at this port's 100 Hz tick
            waited += 10;
        }
        audiopump_task_handle = NULL;
        if (audiopump_task_psram) {
            vTaskDeleteWithCaps(handle);
        } else {
            vTaskDelete(handle);
        }
    }
    audiopump_i2s_close();
    #elif AUDIOPUMP_WASM
    // Nothing to join: the loop only ever runs inside a service() call, and
    // this is not one. `stop` above means the next service() leaves at once.
    audiopump_service_live = false;
    if (audiopump_ctx.sink_fd >= 0) {
        close(audiopump_ctx.sink_fd);
    }
    #else
    if (audiopump_thread_live) {
        audiopump_thread_join();
    }
    if (audiopump_ctx.sink_fd >= 0) {
        audiopump_sink_close(audiopump_ctx.sink_fd);
    }
    #if AUDIOPUMP_WIN
    // The pace timer belongs to whichever thread first paced -- which is the
    // pump, and it has just been joined. Closing it here, from the
    // interpreter thread, is the only moment nobody is waiting on it.
    if (audiopump_pace_timer != NULL) {
        CloseHandle(audiopump_pace_timer);
        audiopump_pace_timer = NULL;
        audiopump_pace_coarse = false;
    }
    #endif
    #endif
    // Everything in here points into a heap that is about to be re-inited.
    memset(&audiopump_ctx, 0, sizeof(audiopump_ctx));
    audiopump_ctx.sink_fd = -1;
    MP_STATE_VM(audiopump_held)[0] = MP_OBJ_NULL;
    MP_STATE_VM(audiopump_held)[1] = MP_OBJ_NULL;
    MP_STATE_VM(audiopump_held)[2] = MP_OBJ_NULL;
    // The queue and the tap go with everything else. A queue holds Notes and
    // samples out of a heap that is about to be re-inited, and holding it
    // past a soft reset would be the same bug as holding the graph.
    MP_STATE_VM(audiopump_held)[AUDIOPUMP_HELD_EVENTS] = MP_OBJ_NULL;
    MP_STATE_VM(audiopump_held)[AUDIOPUMP_HELD_TAP] = MP_OBJ_NULL;
    if (release_guard) {
        MP_STATE_VM(audiopump_held)[3] = MP_OBJ_NULL;
    }
}

typedef struct {
    mp_obj_base_t base;
} audiopump_guard_obj_t;

static mp_obj_t audiopump_guard_del(mp_obj_t self_in) {
    (void)self_in;
    audiopump_teardown(true);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(audiopump_guard_del_obj, audiopump_guard_del);

static const mp_rom_map_elem_t audiopump_guard_locals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___del__), MP_ROM_PTR(&audiopump_guard_del_obj) },
};
static MP_DEFINE_CONST_DICT(audiopump_guard_locals,
    audiopump_guard_locals_table);

MP_DEFINE_CONST_OBJ_TYPE(
    audiopump_guard_type,
    MP_QSTR_Guard,
    MP_TYPE_FLAG_NONE,
    locals_dict, &audiopump_guard_locals
    );

// Called by anything that takes ownership of hardware or a graph. Rooted, so
// a normal gc.collect() never finalises it; unrooted objects are finalised by
// gc_sweep_all() regardless, which is the whole point.
static void audiopump_arm_guard(void) {
    if (MP_STATE_VM(audiopump_held)[3] == MP_OBJ_NULL) {
        MP_STATE_VM(audiopump_held)[3] = MP_OBJ_FROM_PTR(
            mp_obj_malloc_with_finaliser(audiopump_guard_obj_t,
                &audiopump_guard_type));
    }
}

static bool audiopump_is_running(void) {
    #if AUDIOPUMP_ESP
    return audiopump_task_handle != NULL && !audiopump_ctx.finished;
    #elif AUDIOPUMP_WASM
    return audiopump_service_live && !audiopump_ctx.finished;
    #else
    return audiopump_thread_live && !audiopump_ctx.finished;
    #endif
}

static mp_obj_t audiopump_running(void) {
    return mp_obj_new_bool(audiopump_is_running());
}
static MP_DEFINE_CONST_FUN_OBJ_0(audiopump_running_obj, audiopump_running);

// The explicit form of what the finaliser does. Safe to call twice.
static mp_obj_t audiopump_shutdown(void) {
    audiopump_teardown(false);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(audiopump_shutdown_obj, audiopump_shutdown);

// A file-backed source cannot be pulled by a pump: it reads through the VFS
// from inside get_buffer, which re-enters the interpreter, and it raises
// there. audioif's WaveFile and MP3Decoder now refuse it from the inside --
// they publish AUDIOIF_PUMP_FAULT_UNPUMPABLE and go silent rather than
// crash -- but a graph that is nothing BUT a file is worth refusing at the
// door, with a sentence, instead of playing silence and leaving a number to
// be looked up.
//
// This catches the tail only. A file source sits at the HEAD of a graph, and
// the audiosample protocol has no "what is behind you" accessor to walk, so a
// deep one is caught at the first block instead of at the door. That is the
// honest limit of this check and it is written down in the notes.
static void audiopump_refuse_unpumpable(mp_obj_t sample) {
    const qstr name = mp_obj_get_type(sample)->name;
    if (name == MP_QSTR_WaveFile || name == MP_QSTR_MP3Decoder) {
        mp_raise_ValueError(MP_ERROR_TEXT(
            "a file-backed source cannot be pumped; it reads through the VFS "
            "inside the pull. Fill a ring from the interpreter instead."));
    }
}

static mp_obj_t audiopump_spawn(size_t n_args, const mp_obj_t *pos_args,
    mp_map_t *kw_args) {
    enum { ARG_sample, ARG_blocks, ARG_status, ARG_sink, ARG_ring, ARG_core,
           ARG_prio, ARG_stack, ARG_psram, ARG_timeout_ms, ARG_pace };
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
        // unix only; see `paced` in the context struct.
        { MP_QSTR_pace,       MP_ARG_BOOL, { .u_bool = false } },
    };
    mp_arg_val_t args[MP_ARRAY_SIZE(allowed)];
    mp_arg_parse_all(n_args, pos_args, kw_args, MP_ARRAY_SIZE(allowed),
        allowed, args);

    // One global pump, so a second spawn would silently orphan the first --
    // the task that is already pulling, and the graph behind it. Refuse, and
    // say what to call. shutdown() is the door out; it is also what the soft
    // reset finaliser calls.
    #if AUDIOPUMP_ESP
    if (audiopump_task_handle != NULL) {
        mp_raise_ValueError(MP_ERROR_TEXT(
            "a pump is already spawned; call audiopump.shutdown() first"));
    }
    #elif AUDIOPUMP_WASM
    if (audiopump_service_live) {
        mp_raise_ValueError(MP_ERROR_TEXT(
            "a pump is already spawned; call audiopump.shutdown() first"));
    }
    #else
    if (audiopump_thread_live) {
        mp_raise_ValueError(MP_ERROR_TEXT(
            "a pump is already spawned; call audiopump.shutdown() first"));
    }
    #endif

    audiopump_refuse_unpumpable(args[ARG_sample].u_obj);
    audiopump_arm_guard();
    audiopump_prepare(args[ARG_sample].u_obj, args[ARG_blocks].u_obj,
        args[ARG_status].u_obj, args[ARG_ring].u_obj, &audiopump_ctx);
    audiopump_ctx.sink_timeout_ms = (uint32_t)args[ARG_timeout_ms].u_int;
    // From here on audioif knows a pump exists, so the file-backed sources
    // refuse to be pulled and the funnel reports rather than raises. Set
    // BEFORE the thread is created, cleared after it has gone, both from this
    // thread -- so there is a happens-before at each end and no flag race.
    audioif_pump_lock_stats_reset();
    audioif_pump_set_active(true);

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
    #elif AUDIOPUMP_WASM
    // The shape a port with no thread gets: spawn() adopts the tail, publishes
    // the first status words and returns. Not one block has been pulled. The
    // loop advances only when audiopump.service() is called -- from the
    // audiodev driver's timer in a browser, from a probe's while loop here.
    if (args[ARG_sink].u_obj != mp_const_none) {
        const char *path = mp_obj_str_get_str(args[ARG_sink].u_obj);
        audiopump_ctx.sink_fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
        if (audiopump_ctx.sink_fd < 0) {
            mp_raise_OSError(MP_ENOENT);
        }
    }
    audiopump_ctx.service_mode = true;
    audiopump_service_live = true;
    audiopump_run_begin(&audiopump_ctx);
    // -2, not -1: a caller that prints what spawn() returned should be able to
    // tell "no core affinity" from "no thread at all".
    return mp_obj_new_int(-2);
    #else
    if (args[ARG_sink].u_obj != mp_const_none) {
        const char *path = mp_obj_str_get_str(args[ARG_sink].u_obj);
        audiopump_ctx.sink_fd = audiopump_sink_open(path);
        if (audiopump_ctx.sink_fd < 0) {
            mp_raise_OSError(MP_ENOENT);
        }
    }
    if (args[ARG_pace].u_bool) {
        audiopump_ctx.paced = true;
        audiopump_ctx.pace_rate =
            ((audiosample_base_t *)MP_OBJ_TO_PTR(args[ARG_sample].u_obj))
            ->sample_rate;
    }
    if (!audiopump_thread_start()) {
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
    #elif AUDIOPUMP_WASM
    (void)timeout_ms;
    if (!audiopump_service_live) {
        return mp_const_true;
    }
    // There is no thread to wait for and join() must not quietly become the
    // driver: a join that pulled the rest of the graph itself would make every
    // "the timer was late" measurement on this port a measurement of join().
    // So it reports, and the caller keeps calling service().
    if (!audiopump_ctx.finished) {
        return mp_const_false;
    }
    audiopump_service_live = false;
    if (audiopump_ctx.sink_fd >= 0) {
        close(audiopump_ctx.sink_fd);
        audiopump_ctx.sink_fd = -1;
    }
    #else
    (void)timeout_ms;
    if (!audiopump_thread_live) {
        return mp_const_true;
    }
    audiopump_thread_join();
    if (audiopump_ctx.sink_fd >= 0) {
        audiopump_sink_close(audiopump_ctx.sink_fd);
        audiopump_ctx.sink_fd = -1;
    }
    #endif
    audioif_pump_set_active(false);
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
    (void)timeout_us;   // wasm has nothing to wait for; see below
    #if AUDIOPUMP_ESP
    if (audiopump_task_handle == NULL || audiopump_ctx.finished) {
        return mp_const_true;
    }
    #elif AUDIOPUMP_WASM
    if (!audiopump_service_live || audiopump_ctx.finished) {
        return mp_const_true;
    }
    // The loop is not running -- this call IS the only thread -- so the pump
    // is already at a block boundary by construction and park() is a store.
    // The wait below would spin until the timeout and then report success
    // anyway; saying so straight is the same answer without the 200 ms.
    audiopump_ctx.park_req = true;
    return mp_const_true;
    #else
    if (!audiopump_thread_live || audiopump_ctx.finished) {
        return mp_const_true;
    }
    #endif
    #if !AUDIOPUMP_WASM
    audiopump_ctx.park_req = true;
    uint32_t waited = 0;
    while (!audiopump_ctx.parked && !audiopump_ctx.finished
           && waited < timeout_us) {
        mp_hal_delay_us(20);
        waited += 20;
    }
    return (audiopump_ctx.parked || audiopump_ctx.finished)
        ? mp_const_true : mp_const_false;
    #endif
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(audiopump_park_obj, 0, 1,
    audiopump_park);

// --- the port with no thread ----------------------------------------------
//
// The same loop, entered from the interpreter. `max_blocks` caps how many
// blocks one call produces; 0 means "as many as the output ring has room
// for", which is the natural budget because the ring is what paces the pump
// here.
//
// Returns ONE small int, `blocks << 2 | why`, and the packing is not
// premature cleverness: on this port service() IS the pull's entry point, so
// micropython.heap_lock() around it has to hold, and a two-element tuple is
// an allocation per call. A small int is not. Unpack it with
// `why = r & 3; blocks = r >> 2`.
//
// On a threaded port it is a no-op that returns MORE with no blocks: the
// thread is already doing this, and a driver written against the wasm shape
// should not have to know which port it is on.
static mp_obj_t audiopump_service(size_t n_args, const mp_obj_t *args) {
    uint64_t budget = n_args > 0 ? (uint64_t)mp_obj_get_int(args[0]) : 0;
    if (budget == 0) {
        budget = UINT64_MAX;
    }
    int why = AUDIOPUMP_SERVICE_MORE;
    uint64_t before = audiopump_ctx.acc_blocks;
    #if AUDIOPUMP_WASM
    if (audiopump_service_live && !audiopump_ctx.finished) {
        why = audiopump_run_blocks(&audiopump_ctx, budget);
        if (why == AUDIOPUMP_SERVICE_DONE) {
            audiopump_run_end(&audiopump_ctx);
        }
    } else {
        why = AUDIOPUMP_SERVICE_DONE;
        before = audiopump_ctx.acc_blocks;
    }
    #else
    (void)budget;
    #endif
    const mp_uint_t done = (mp_uint_t)(audiopump_ctx.acc_blocks - before);
    return MP_OBJ_NEW_SMALL_INT((done << AUDIOPUMP_SERVICE_SHIFT) | why);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(audiopump_service_obj, 0, 1,
    audiopump_service);

// True where spawn() puts the loop on a thread of its own. False on wasm,
// where audiopump.service() is the driver. One question, asked once, rather
// than every caller sniffing for i2s_start or sys.platform.
static mp_obj_t audiopump_threaded(void) {
    return mp_obj_new_bool(AUDIOPUMP_THREADED);
}
static MP_DEFINE_CONST_FUN_OBJ_0(audiopump_threaded_obj, audiopump_threaded);

// Point the pump at a different tail. The handoff page's registry entry, cut
// down to the one thing the spike needs: a helper that swaps the effect class
// parks, builds the new graph, retargets, unparks. The protocol lookup and
// the deinit check happen here, on the interpreter thread, exactly as they do
// in spawn() -- both of them raise, and the pump thread has nothing to raise
// from.
static mp_obj_t audiopump_retarget(mp_obj_t sample) {
    // No park. Everything that can raise or allocate happens first, on this
    // thread: the protocol lookup, the deinit check, the refusal. Then the
    // lock, then three stores, then the unlock -- and the pump either sees
    // the whole new tail or the whole old one.
    //
    // This is the handoff page's registry entry. The pump holds the entry,
    // not the tail object, so a Component that replaces its own `.output`
    // (Phaser._install_cascade does, on every macro-5 move) can say so
    // without the pump ever pulling the orphan it left behind.
    audiopump_refuse_unpumpable(sample);
    const audiosample_p_t *protocol = mp_proto_get_or_throw(
        MP_QSTR_protocol_audiosample, sample);
    audiosample_check_for_deinit(MP_OBJ_TO_PTR(sample));
    MP_STATE_VM(audiopump_held)[0] = sample;

    audioif_pump_lock_acquire();
    audiopump_ctx.protocol = protocol;
    audiopump_ctx.sample = sample;
    // The type word is re-read by the loop, inside the same lock, so the
    // soft-reset guard cannot see a half-updated pair.
    audiopump_ctx.retarget_req = true;
    audioif_pump_lock_release();
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(audiopump_retarget_obj, audiopump_retarget);

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
    uint32_t available = AUDIOPUMP_LOAD_ACQ(&ctx->ring_w) - ctx->ring_r;
    uint32_t take = (uint32_t)(available > out.len ? out.len : available);
    if (take == 0) {
        return MP_OBJ_NEW_SMALL_INT(0);
    }
    uint32_t at = ctx->ring_rpos;
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
    ctx->ring_rpos = (at + take) % ctx->ring_len;
    ctx->ring_r_total += take;
    // Release: the bytes are out before the space is given back, so the pump
    // cannot land on top of them.
    AUDIOPUMP_STORE_REL(&ctx->ring_r, ctx->ring_r + take);
    ctx->status[STATUS_RING_R] = ctx->ring_r_total;
    ctx->status[STATUS_DRAIN_DIGEST] = digest;
    return mp_obj_new_int_from_uint(take);
}
static MP_DEFINE_CONST_FUN_OBJ_1(audiopump_drain_obj, audiopump_drain);

// --- the clock, the queue and the tap -------------------------------------

// Frames the pump has PULLED since spawn(). Not frames heard: what is
// audible is this minus whatever the sink is holding -- the ring depth on a
// board, which the board half measured at 0.85-3.5 ms. Schedule against this
// one, because it is the number the pump compares your event's frame against;
// subtract the depth only when you are asking what a listener has heard.
//
// Wraps at 2^32 frames, 24.9 hours at 48 kHz. Nothing has to be done about
// that in Python: `now() + n` is an ordinary int and `at()` masks it.
static mp_obj_t audiopump_now(void) {
    return mp_obj_new_int_from_uint(
        AUDIOPUMP_LOAD_ACQ(&audiopump_ctx.frames));
}
static MP_DEFINE_CONST_FUN_OBJ_0(audiopump_now_obj, audiopump_now);

// Attach or detach, and report. One pointer either way, so the lock is held
// for a store -- but it IS held, because a pump reading the pointer half-way
// through is the whole class of bug this spike is about.
static mp_obj_t audiopump_set_events(size_t n_args, const mp_obj_t *args) {
    if (n_args > 0) {
        mp_obj_t q = args[0];
        if (q != mp_const_none && !mp_obj_is_type(q, &audiopump_events_type)) {
            mp_raise_TypeError(MP_ERROR_TEXT("expected an Events queue"));
        }
        if (q == mp_const_none) {
            // Detach: the pump lets go first, then the root does.
            audioif_pump_lock_acquire();
            audiopump_ctx.events = MP_OBJ_NULL;
            audioif_pump_lock_release();
            MP_STATE_VM(audiopump_held)[AUDIOPUMP_HELD_EVENTS] = MP_OBJ_NULL;
        } else {
            // Attach: the root takes hold first, so the queue is reachable
            // before the pump can reach it.
            audiopump_arm_guard();
            MP_STATE_VM(audiopump_held)[AUDIOPUMP_HELD_EVENTS] = q;
            audioif_pump_lock_acquire();
            audiopump_ctx.events = q;
            audioif_pump_lock_release();
        }
    }
    mp_obj_t held = MP_STATE_VM(audiopump_held)[AUDIOPUMP_HELD_EVENTS];
    return held == MP_OBJ_NULL ? mp_const_none : held;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(audiopump_set_events_obj, 0, 1,
    audiopump_set_events);

static mp_obj_t audiopump_set_tap(size_t n_args, const mp_obj_t *args) {
    if (n_args > 0) {
        mp_obj_t t = args[0];
        if (t != mp_const_none && !mp_obj_is_type(t, &audiopump_tap_type)) {
            mp_raise_TypeError(MP_ERROR_TEXT("expected a Tap"));
        }
        if (t == mp_const_none) {
            audioif_pump_lock_acquire();
            audiopump_ctx.tap = MP_OBJ_NULL;
            audioif_pump_lock_release();
            MP_STATE_VM(audiopump_held)[AUDIOPUMP_HELD_TAP] = MP_OBJ_NULL;
        } else {
            audiopump_arm_guard();
            MP_STATE_VM(audiopump_held)[AUDIOPUMP_HELD_TAP] = t;
            audioif_pump_lock_acquire();
            audiopump_ctx.tap = t;
            audioif_pump_lock_release();
        }
    }
    mp_obj_t held = MP_STATE_VM(audiopump_held)[AUDIOPUMP_HELD_TAP];
    return held == MP_OBJ_NULL ? mp_const_none : held;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(audiopump_set_tap_obj, 0, 1,
    audiopump_set_tap);

// --- the I2S sink, opened from Python -------------------------------------

#if AUDIOPUMP_ESP
static mp_obj_t audiopump_i2s_start(size_t n_args, const mp_obj_t *pos_args,
    mp_map_t *kw_args) {
    enum { ARG_port, ARG_bclk, ARG_ws, ARG_dout, ARG_rate, ARG_bits,
           ARG_channels, ARG_mclk, ARG_mclk_fs, ARG_dma_desc, ARG_dma_frame,
           ARG_din, ARG_in_port, ARG_in_bclk, ARG_in_ws, ARG_in_mclk };
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
        // >= 0 opens the RX half of the SAME channel pair, so one clock tree
        // drives both directions.
        { MP_QSTR_din,       MP_ARG_INT,  { .u_int = -1 } },
        // ... unless the capture device is on a DIFFERENT I2S peripheral,
        // which is what the LilyGO T-Embed is: a MAX98357A on port 1 and an
        // ES7210 on port 0, with their own pins. Then RX is a second
        // channel with its own clock divider, and the two are NOT
        // sample-locked -- see the note below the call.
        { MP_QSTR_in_port,   MP_ARG_INT,  { .u_int = -1 } },
        { MP_QSTR_in_bclk,   MP_ARG_INT,  { .u_int = -1 } },
        { MP_QSTR_in_ws,     MP_ARG_INT,  { .u_int = -1 } },
        { MP_QSTR_in_mclk,   MP_ARG_INT,  { .u_int = -1 } },
    };
    mp_arg_val_t args[MP_ARRAY_SIZE(allowed)];
    mp_arg_parse_all(n_args, pos_args, kw_args, MP_ARRAY_SIZE(allowed),
        allowed, args);

    if (audiopump_i2s_tx != NULL) {
        mp_raise_ValueError(MP_ERROR_TEXT("i2s already open"));
    }
    audiopump_arm_guard();

    const bool duplex = args[ARG_din].u_int >= 0;
    // Two ports means two clock dividers. They start from the same PLL, so
    // they are nominally the same rate, but nothing locks them sample to
    // sample: over minutes the capture and the playback drift apart and the
    // pump, which is paced by the Input's read, ends up handing TX slightly
    // more or slightly less than it consumes. A single-port duplex has no
    // such thing -- there BCLK and WS are generated once.
    const bool split = duplex && args[ARG_in_port].u_int >= 0
        && args[ARG_in_port].u_int != args[ARG_port].u_int;

    i2s_chan_config_t chan_config = I2S_CHANNEL_DEFAULT_CONFIG(
        (i2s_port_t)args[ARG_port].u_int, I2S_ROLE_MASTER);
    chan_config.dma_desc_num = (uint32_t)args[ARG_dma_desc].u_int;
    chan_config.dma_frame_num = (uint32_t)args[ARG_dma_frame].u_int;
    chan_config.auto_clear = true;   // zeros on underrun, never stale data
    esp_err_t err = i2s_new_channel(&chan_config, &audiopump_i2s_tx,
        (duplex && !split) ? &audiopump_i2s_rx : NULL);
    if (err == ESP_OK && split) {
        i2s_chan_config_t rx_config = I2S_CHANNEL_DEFAULT_CONFIG(
            (i2s_port_t)args[ARG_in_port].u_int, I2S_ROLE_MASTER);
        rx_config.dma_desc_num = (uint32_t)args[ARG_dma_desc].u_int;
        rx_config.dma_frame_num = (uint32_t)args[ARG_dma_frame].u_int;
        rx_config.auto_clear = true;
        err = i2s_new_channel(&rx_config, NULL, &audiopump_i2s_rx);
    }
    if (err != ESP_OK) {
        audiopump_i2s_close();
        audiopump_i2s_tx = NULL;
        audiopump_i2s_rx = NULL;
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
            // Not on the split path: there `din` belongs to the other
            // peripheral, and claiming it here would route the microphone
            // into the speaker's port as well.
            .din = (duplex && !split) ? (gpio_num_t)args[ARG_din].u_int
                                      : I2S_GPIO_UNUSED,
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
    if (err == ESP_OK && duplex && !split) {
        // The same std config on both halves. On one port that is not a
        // convenience -- the IDF derives BCLK/WS once and the second channel
        // has to agree with it or the init is refused.
        err = i2s_channel_init_std_mode(audiopump_i2s_rx, &std_cfg);
    } else if (err == ESP_OK && split) {
        // Its own pins, its own MCLK. The ES7210 needs one and there is no
        // MCLK on the speaker's wire at all, so this is not a variation on
        // the TX config -- it is a second device.
        i2s_std_config_t rx_cfg = std_cfg;
        rx_cfg.gpio_cfg.bclk = (gpio_num_t)(args[ARG_in_bclk].u_int < 0
            ? args[ARG_bclk].u_int : args[ARG_in_bclk].u_int);
        rx_cfg.gpio_cfg.ws = (gpio_num_t)(args[ARG_in_ws].u_int < 0
            ? args[ARG_ws].u_int : args[ARG_in_ws].u_int);
        rx_cfg.gpio_cfg.dout = I2S_GPIO_UNUSED;
        rx_cfg.gpio_cfg.din = (gpio_num_t)args[ARG_din].u_int;
        rx_cfg.gpio_cfg.mclk = args[ARG_in_mclk].u_int < 0
            ? I2S_GPIO_UNUSED : (gpio_num_t)args[ARG_in_mclk].u_int;
        err = i2s_channel_init_std_mode(audiopump_i2s_rx, &rx_cfg);
    }
    if (err == ESP_OK) {
        i2s_event_callbacks_t cbs = { .on_sent = audiopump_on_sent };
        err = i2s_channel_register_event_callback(audiopump_i2s_tx, &cbs, NULL);
    }
    if (err == ESP_OK && duplex) {
        i2s_event_callbacks_t rx_cbs = { .on_recv = audiopump_on_recv };
        err = i2s_channel_register_event_callback(audiopump_i2s_rx, &rx_cbs,
            NULL);
    }
    if (err == ESP_OK) {
        audiopump_dma_bytes = 0;
        audiopump_rx_bytes = 0;
        // RX first: it is the half that must not miss the beginning of what
        // TX emits, and enabling it first makes any gap between the two an
        // over-estimate of the round trip rather than an under-estimate.
        if (duplex) {
            err = i2s_channel_enable(audiopump_i2s_rx);
        }
    }
    if (err == ESP_OK) {
        err = i2s_channel_enable(audiopump_i2s_tx);
    }
    if (err != ESP_OK) {
        audiopump_i2s_close();
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
    audiopump_i2s_close();
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(audiopump_i2s_stop_obj, audiopump_i2s_stop);

static mp_obj_t audiopump_i2s_dma_bytes(void) {
    return mp_obj_new_int_from_uint((mp_uint_t)audiopump_dma_bytes);
}
static MP_DEFINE_CONST_FUN_OBJ_0(audiopump_i2s_dma_bytes_obj,
    audiopump_i2s_dma_bytes);

static mp_obj_t audiopump_i2s_rx_bytes(void) {
    return mp_obj_new_int_from_uint((mp_uint_t)audiopump_rx_bytes);
}
static MP_DEFINE_CONST_FUN_OBJ_0(audiopump_i2s_rx_bytes_obj,
    audiopump_i2s_rx_bytes);

// --- audiopump.Input: the capture side, as an audiosample ------------------
//
// An audiosample whose get_buffer is an i2s_channel_read. That makes the live
// microphone a source like any other, so
//
//     audioeffects.create("Overdrive", audiopump.Input(...), rate)
//
// builds a real effect graph on it and the pump pulls the whole thing. The
// read blocks, which is the pacing: RX is the clock, and because RX and TX
// came out of one i2s_new_channel they are the SAME clock.
//
// Nothing in here calls into the MicroPython runtime, because everything in
// here runs on the pump task.

typedef struct {
    audiosample_base_t base;
    uint8_t *buf[2];            // ping-pong, so a node may hold the last block
    uint32_t len;               // bytes per block
    uint8_t which;
    uint32_t timeout_ms;
    volatile uint64_t blocks;
    volatile uint64_t timeouts;
    volatile uint64_t short_reads;
} audiopump_input_obj_t;

extern const mp_obj_type_t audiopump_input_type;

static void audiopump_input_reset_buffer(audiopump_input_obj_t *self,
    bool single_channel_output, uint8_t channel) {
    (void)single_channel_output;
    (void)channel;
    self->which = 0;
}

static audioio_get_buffer_result_t audiopump_input_get_buffer(
    audiopump_input_obj_t *self, bool single_channel_output, uint8_t channel,
    uint8_t **buffer, uint32_t *buffer_length) {
    (void)single_channel_output;
    (void)channel;
    uint8_t *dst = self->buf[self->which];
    self->which ^= 1;
    size_t got = 0;
    if (audiopump_i2s_rx != NULL) {
        esp_err_t err = i2s_channel_read(audiopump_i2s_rx, dst, self->len,
            &got, pdMS_TO_TICKS(self->timeout_ms));
        if (err != ESP_OK) {
            self->timeouts++;
        }
    }
    if (got < self->len) {
        // Silence rather than stale audio: a short read is a starve, and a
        // starve should sound like a hole, not like a stutter.
        memset(dst + got, 0, self->len - got);
        if (got != self->len) {
            self->short_reads++;
        }
    }
    self->blocks++;
    *buffer = dst;
    *buffer_length = self->len;
    return GET_BUFFER_MORE_DATA;
}

static mp_obj_t audiopump_input_make_new(const mp_obj_type_t *type,
    size_t n_args, size_t n_kw, const mp_obj_t *all_args) {
    enum { ARG_rate, ARG_channels, ARG_frames, ARG_timeout_ms };
    static const mp_arg_t allowed[] = {
        { MP_QSTR_sample_rate,  MP_ARG_INT | MP_ARG_KW_ONLY, { .u_int = 48000 } },
        { MP_QSTR_channel_count, MP_ARG_INT | MP_ARG_KW_ONLY, { .u_int = 2 } },
        { MP_QSTR_frames,       MP_ARG_INT | MP_ARG_KW_ONLY, { .u_int = 256 } },
        { MP_QSTR_timeout_ms,   MP_ARG_INT | MP_ARG_KW_ONLY, { .u_int = 500 } },
    };
    mp_arg_val_t args[MP_ARRAY_SIZE(allowed)];
    mp_arg_parse_all_kw_array(n_args, n_kw, all_args, MP_ARRAY_SIZE(allowed),
        allowed, args);

    const uint32_t channels = (uint32_t)args[ARG_channels].u_int;
    const uint32_t frames = (uint32_t)args[ARG_frames].u_int;
    if (channels < 1 || channels > 2 || frames < 16) {
        mp_raise_ValueError(MP_ERROR_TEXT("bad channel_count or frames"));
    }

    audiopump_input_obj_t *self = mp_obj_malloc(audiopump_input_obj_t,
        (const mp_obj_type_t *)&audiopump_input_type);
    self->len = frames * channels * 2;
    self->buf[0] = m_new(uint8_t, self->len);
    self->buf[1] = m_new(uint8_t, self->len);
    memset(self->buf[0], 0, self->len);
    memset(self->buf[1], 0, self->len);
    self->which = 0;
    self->timeout_ms = (uint32_t)args[ARG_timeout_ms].u_int;
    self->blocks = 0;
    self->timeouts = 0;
    self->short_reads = 0;

    self->base.sample_rate = (uint32_t)args[ARG_rate].u_int;
    self->base.max_buffer_length = self->len;
    self->base.bits_per_sample = 16;
    self->base.channel_count = (uint8_t)channels;
    self->base.samples_signed = true;
    // Two buffers, so a node downstream may keep the previous block.
    self->base.single_buffer = false;
    return MP_OBJ_FROM_PTR(self);
}

static mp_obj_t audiopump_input_stats(mp_obj_t self_in) {
    audiopump_input_obj_t *self = MP_OBJ_TO_PTR(self_in);
    mp_obj_t items[4] = {
        mp_obj_new_int_from_uint((mp_uint_t)self->blocks),
        mp_obj_new_int_from_uint((mp_uint_t)self->timeouts),
        mp_obj_new_int_from_uint((mp_uint_t)self->short_reads),
        mp_obj_new_int_from_uint(self->len),
    };
    return mp_obj_new_tuple(4, items);
}
static MP_DEFINE_CONST_FUN_OBJ_1(audiopump_input_stats_obj,
    audiopump_input_stats);

static const mp_rom_map_elem_t audiopump_input_locals_table[] = {
    { MP_ROM_QSTR(MP_QSTR_stats), MP_ROM_PTR(&audiopump_input_stats_obj) },
    AUDIOSAMPLE_FIELDS,
};
static MP_DEFINE_CONST_DICT(audiopump_input_locals,
    audiopump_input_locals_table);

static const audiosample_p_t audiopump_input_proto = {
    MP_PROTO_IMPLEMENT(MP_QSTR_protocol_audiosample)
    .reset_buffer = (audiosample_reset_buffer_fun)audiopump_input_reset_buffer,
    .get_buffer = (audiosample_get_buffer_fun)audiopump_input_get_buffer,
};

MP_DEFINE_CONST_OBJ_TYPE(
    audiopump_input_type,
    MP_QSTR_Input,
    MP_TYPE_FLAG_HAS_SPECIAL_ACCESSORS,
    make_new, audiopump_input_make_new,
    attr, cp_compat_attr,
    locals_dict, &audiopump_input_locals,
    protocol, &audiopump_input_proto
    );

// --- the round-trip latency probe -----------------------------------------
//
// DAC to speaker to microphone to ADC, measured in frames rather than in host
// time. TX and RX share one frame clock, so RX frame N is sampled as TX frame
// N goes out; the only thing needed is a known origin, and
// i2s_channel_preload_data gives one -- the click is written into the DMA
// BEFORE the channels are enabled, so it leaves at a frame this code chose.
//
// Runs on the interpreter thread with no pump spawned; two owners of one
// channel is the failure that sounds like silence.
static mp_obj_t audiopump_rt_probe(size_t n_args, const mp_obj_t *pos_args,
    mp_map_t *kw_args) {
    enum { ARG_capture, ARG_frames, ARG_lead, ARG_prime, ARG_level,
           ARG_channels, ARG_timeout_ms };
    static const mp_arg_t allowed[] = {
        { MP_QSTR_capture,    MP_ARG_REQUIRED | MP_ARG_OBJ, { .u_obj = MP_OBJ_NULL } },
        { MP_QSTR_frames,     MP_ARG_INT, { .u_int = 256 } },
        { MP_QSTR_lead,       MP_ARG_INT, { .u_int = 0 } },
        { MP_QSTR_prime,      MP_ARG_INT, { .u_int = 0 } },
        { MP_QSTR_level,      MP_ARG_INT, { .u_int = 24000 } },
        { MP_QSTR_channels,   MP_ARG_INT, { .u_int = 2 } },
        { MP_QSTR_timeout_ms, MP_ARG_INT, { .u_int = 2000 } },
    };
    mp_arg_val_t args[MP_ARRAY_SIZE(allowed)];
    mp_arg_parse_all(n_args, pos_args, kw_args, MP_ARRAY_SIZE(allowed),
        allowed, args);

    if (audiopump_i2s_tx == NULL || audiopump_i2s_rx == NULL) {
        mp_raise_ValueError(MP_ERROR_TEXT("open i2s with din= first"));
    }
    if (audiopump_is_running()) {
        mp_raise_ValueError(MP_ERROR_TEXT("stop the pump first"));
    }

    mp_buffer_info_t cap;
    mp_get_buffer_raise(args[ARG_capture].u_obj, &cap, MP_BUFFER_WRITE);

    const uint32_t channels = (uint32_t)args[ARG_channels].u_int;
    const uint32_t frames = (uint32_t)args[ARG_frames].u_int;
    const uint32_t lead = (uint32_t)args[ARG_lead].u_int;
    const uint32_t frame_bytes = channels * 2;
    const uint32_t click_bytes = frames * frame_bytes;

    // Silence the whole path, then rebuild both DMAs from zero.
    i2s_channel_disable(audiopump_i2s_tx);
    i2s_channel_disable(audiopump_i2s_rx);

    // One block: `lead` frames of silence and then a hard step. The step is a
    // step, not an impulse -- a single frame gets swallowed by the codec's
    // reconstruction filter, and a step's leading edge is just as findable.
    uint8_t *click = m_new(uint8_t, click_bytes);
    memset(click, 0, click_bytes);
    int16_t *s = (int16_t *)click;
    const int16_t level = (int16_t)args[ARG_level].u_int;
    for (uint32_t f = lead; f < frames; f++) {
        for (uint32_t c = 0; c < channels; c++) {
            // A few hundred microseconds of square wave: loud, broadband and
            // unmistakable against a quiet room.
            s[f * channels + c] = ((f - lead) / 8) % 2 ? level : (int16_t)-level;
        }
    }

    size_t loaded = 0;
    // `prime` blocks of silence ahead of the click model a TX ring that is
    // already full -- which is what a live pump keeps it. prime=0 measures
    // the path with both rings empty.
    uint8_t *quiet = NULL;
    if (args[ARG_prime].u_int > 0) {
        quiet = m_new(uint8_t, click_bytes);
        memset(quiet, 0, click_bytes);
        for (int i = 0; i < args[ARG_prime].u_int; i++) {
            size_t n = 0;
            i2s_channel_preload_data(audiopump_i2s_tx, quiet, click_bytes, &n);
            loaded += n;
        }
    }
    size_t click_at = loaded;
    size_t n = 0;
    esp_err_t err = i2s_channel_preload_data(audiopump_i2s_tx, click,
        click_bytes, &n);
    loaded += n;

    const uint64_t t_rx = audiopump_now_us();
    if (err == ESP_OK) {
        err = i2s_channel_enable(audiopump_i2s_rx);
    }
    const uint64_t t_tx = audiopump_now_us();
    if (err == ESP_OK) {
        err = i2s_channel_enable(audiopump_i2s_tx);
    }
    size_t got = 0;
    if (err == ESP_OK) {
        err = i2s_channel_read(audiopump_i2s_rx, cap.buf, cap.len, &got,
            pdMS_TO_TICKS(args[ARG_timeout_ms].u_int));
    }

    mp_obj_t items[6] = {
        mp_obj_new_int_from_uint((mp_uint_t)got),
        // Frame index at which the step leaves the DAC, in the TX stream.
        mp_obj_new_int_from_uint((mp_uint_t)((click_at + lead * frame_bytes)
            / frame_bytes)),
        mp_obj_new_int_from_uint((mp_uint_t)(loaded / frame_bytes)),
        // Microseconds between enabling RX and enabling TX: the one piece of
        // host timing in the measurement, reported rather than assumed away.
        mp_obj_new_int_from_uint((mp_uint_t)(t_tx - t_rx)),
        mp_obj_new_int((mp_int_t)err),
        mp_obj_new_int_from_uint((mp_uint_t)frame_bytes),
    };
    m_del(uint8_t, click, click_bytes);
    if (quiet != NULL) {
        m_del(uint8_t, quiet, click_bytes);
    }
    return mp_obj_new_tuple(6, items);
}
static MP_DEFINE_CONST_FUN_OBJ_KW(audiopump_rt_probe_obj, 1,
    audiopump_rt_probe);
#endif

// --- what the lock cost, and why a pull gave up ---------------------------
//
// The status block carries these too, but a storm wants them without a pump
// running and wants to zero them between rounds.

static mp_obj_t audiopump_lock_stats(void) {
    const audioif_pump_lock_stats_t *s = audioif_pump_lock_stats();
    mp_obj_t items[7] = {
        mp_obj_new_int_from_ull(s->pump_takes),
        mp_obj_new_int_from_ull(s->pump_wait_us),
        mp_obj_new_int_from_ull(s->pump_wait_us_max),
        mp_obj_new_int_from_ull(s->ctrl_takes),
        mp_obj_new_int_from_ull(s->ctrl_wait_us),
        mp_obj_new_int_from_ull(s->ctrl_wait_us_max),
        mp_obj_new_int_from_ull(s->ctrl_held_us_max),
    };
    return mp_obj_new_tuple(7, items);
}
static MP_DEFINE_CONST_FUN_OBJ_0(audiopump_lock_stats_obj,
    audiopump_lock_stats);

static mp_obj_t audiopump_lock_reset(void) {
    audioif_pump_lock_stats_reset();
    audioif_pump_fault_clear();
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(audiopump_lock_reset_obj,
    audiopump_lock_reset);

static mp_obj_t audiopump_fault(void) {
    return mp_obj_new_int_from_uint(audioif_pump_fault_get());
}
static MP_DEFINE_CONST_FUN_OBJ_0(audiopump_fault_obj, audiopump_fault);

static const mp_rom_map_elem_t audiopump_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR_lock_stats), MP_ROM_PTR(&audiopump_lock_stats_obj) },
    { MP_ROM_QSTR(MP_QSTR_lock_reset), MP_ROM_PTR(&audiopump_lock_reset_obj) },
    { MP_ROM_QSTR(MP_QSTR_fault), MP_ROM_PTR(&audiopump_fault_obj) },
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_audiopump) },
    { MP_ROM_QSTR(MP_QSTR_pull), MP_ROM_PTR(&audiopump_pull_obj) },
    { MP_ROM_QSTR(MP_QSTR_spawn), MP_ROM_PTR(&audiopump_spawn_obj) },
    { MP_ROM_QSTR(MP_QSTR_join), MP_ROM_PTR(&audiopump_join_obj) },
    { MP_ROM_QSTR(MP_QSTR_stop), MP_ROM_PTR(&audiopump_stop_obj) },
    { MP_ROM_QSTR(MP_QSTR_park), MP_ROM_PTR(&audiopump_park_obj) },
    { MP_ROM_QSTR(MP_QSTR_unpark), MP_ROM_PTR(&audiopump_unpark_obj) },
    { MP_ROM_QSTR(MP_QSTR_retarget), MP_ROM_PTR(&audiopump_retarget_obj) },
    { MP_ROM_QSTR(MP_QSTR_drain), MP_ROM_PTR(&audiopump_drain_obj) },
    { MP_ROM_QSTR(MP_QSTR_reset), MP_ROM_PTR(&audiopump_reset_graph_obj) },
    { MP_ROM_QSTR(MP_QSTR_info), MP_ROM_PTR(&audiopump_info_obj) },
    { MP_ROM_QSTR(MP_QSTR_running), MP_ROM_PTR(&audiopump_running_obj) },
    { MP_ROM_QSTR(MP_QSTR_shutdown), MP_ROM_PTR(&audiopump_shutdown_obj) },
    // The port with no thread, and the one question that tells a driver
    // whether it has to call service() itself. Both exist on every port.
    { MP_ROM_QSTR(MP_QSTR_service), MP_ROM_PTR(&audiopump_service_obj) },
    { MP_ROM_QSTR(MP_QSTR_threaded), MP_ROM_PTR(&audiopump_threaded_obj) },
    { MP_ROM_QSTR(MP_QSTR_SERVICE_MORE), MP_ROM_INT(AUDIOPUMP_SERVICE_MORE) },
    { MP_ROM_QSTR(MP_QSTR_SERVICE_FULL), MP_ROM_INT(AUDIOPUMP_SERVICE_FULL) },
    { MP_ROM_QSTR(MP_QSTR_SERVICE_PARKED),
      MP_ROM_INT(AUDIOPUMP_SERVICE_PARKED) },
    { MP_ROM_QSTR(MP_QSTR_SERVICE_DONE), MP_ROM_INT(AUDIOPUMP_SERVICE_DONE) },
    { MP_ROM_QSTR(MP_QSTR_SERVICE_MASK), MP_ROM_INT(AUDIOPUMP_SERVICE_MASK) },
    { MP_ROM_QSTR(MP_QSTR_SERVICE_SHIFT),
      MP_ROM_INT(AUDIOPUMP_SERVICE_SHIFT) },
    #if AUDIOPUMP_ESP
    { MP_ROM_QSTR(MP_QSTR_i2s_start), MP_ROM_PTR(&audiopump_i2s_start_obj) },
    { MP_ROM_QSTR(MP_QSTR_i2s_stop), MP_ROM_PTR(&audiopump_i2s_stop_obj) },
    { MP_ROM_QSTR(MP_QSTR_i2s_dma_bytes),
      MP_ROM_PTR(&audiopump_i2s_dma_bytes_obj) },
    { MP_ROM_QSTR(MP_QSTR_i2s_rx_bytes),
      MP_ROM_PTR(&audiopump_i2s_rx_bytes_obj) },
    { MP_ROM_QSTR(MP_QSTR_Input), MP_ROM_PTR(&audiopump_input_type) },
    { MP_ROM_QSTR(MP_QSTR_rt_probe), MP_ROM_PTR(&audiopump_rt_probe_obj) },
    #endif
    // The push side. Every port, not just esp32: the ring is RAM and a
    // memcpy, so the unix build is where its correctness is settled.
    { MP_ROM_QSTR(MP_QSTR_Ring), MP_ROM_PTR(&audiopump_ring_type) },
    // Sequenced music, and the way out to a meter. Same reasoning: RAM,
    // arithmetic and a memcpy, so the unix build settles both.
    { MP_ROM_QSTR(MP_QSTR_Events), MP_ROM_PTR(&audiopump_events_type) },
    { MP_ROM_QSTR(MP_QSTR_Tap), MP_ROM_PTR(&audiopump_tap_type) },
    { MP_ROM_QSTR(MP_QSTR_now), MP_ROM_PTR(&audiopump_now_obj) },
    { MP_ROM_QSTR(MP_QSTR_events), MP_ROM_PTR(&audiopump_set_events_obj) },
    { MP_ROM_QSTR(MP_QSTR_tap), MP_ROM_PTR(&audiopump_set_tap_obj) },
    // The closed set, as module constants rather than strings: an op is
    // compared on the pump thread and a qstr lookup there is a runtime call.
    { MP_ROM_QSTR(MP_QSTR_PRESS), MP_ROM_INT(AUDIOPUMP_OP_PRESS) },
    { MP_ROM_QSTR(MP_QSTR_RELEASE), MP_ROM_INT(AUDIOPUMP_OP_RELEASE) },
    { MP_ROM_QSTR(MP_QSTR_RELEASE_ALL), MP_ROM_INT(AUDIOPUMP_OP_RELEASE_ALL) },
    { MP_ROM_QSTR(MP_QSTR_PLAY), MP_ROM_INT(AUDIOPUMP_OP_PLAY) },
    { MP_ROM_QSTR(MP_QSTR_STOP), MP_ROM_INT(AUDIOPUMP_OP_STOP) },
    { MP_ROM_QSTR(MP_QSTR_LEVEL), MP_ROM_INT(AUDIOPUMP_OP_LEVEL) },
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
