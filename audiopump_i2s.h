// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: Copyright (c) 2026 PyDevices
//
// The I2S channel, as C rather than as `_audioif.i2s_start(...)`.
//
// `audiobusio.I2SOut` opens the same peripheral the same way -- it is the
// CircuitPython-shaped face of exactly this -- and it lives in its own
// translation unit, so the open has to be reachable from outside
// `_audioif.c`. The Python entry point is now an argument parser in front of
// `audiopump_i2s_open`; there is one implementation and it is this one.

#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// -1 in any pin or port field means "not wired". `in_port` >= 0 and different
// from `port` is the two-peripheral duplex the T-Embed needs; see the long
// comment at the call site in _audioif.c.
typedef struct {
    int port;
    int bclk;
    int ws;
    int dout;
    int rate;
    int bits;
    int channels;
    int mclk;
    int mclk_fs;
    int dma_desc;
    int dma_frame;
    int din;
    int in_port;
    int in_bclk;
    int in_ws;
    int in_mclk;
} audiopump_i2s_cfg_t;

// True where this build has an I2S peripheral at all -- false on every
// desktop port, which is how audiobusio decides what it is.
bool audiopump_i2s_have(void);

// True while a channel is open.
bool audiopump_i2s_is_open(void);

// Open TX (and RX when `din` >= 0) and enable the channel. Raises, so it
// needs an nlr handler above it. Returns how many bytes the DMA holds when
// full -- the block-to-wire latency floor.
uint32_t audiopump_i2s_open(const audiopump_i2s_cfg_t *cfg);

// Close it. Safe to call when nothing is open.
void audiopump_i2s_shutdown(void);

// Silence on the wire since the count was armed: audio that should have
// played by now and did not, in bytes. Takes two witnesses -- the DMA's own
// byte count and the wall clock -- because on the ESP32-S3 neither one sees
// both ways the wire goes quiet; the definition carries the measurement that
// settles it. 0 on a build with no I2S.
//
// Meaningless while the output is PAUSED, because a park is silence somebody
// asked for and the clock does not know that; `resume()` restarts the count.
uint64_t audiopump_i2s_starved(void);

// Start counting again from here, and do not charge whatever the DMA clocked
// while nothing was playing. Called wherever feeding legitimately begins --
// the channel opening, `play()`, `resume()` -- because silence that was asked
// for is not starvation and only the caller knows which is which. It ARMS the
// count rather than starting it: counting begins once the DMA has clocked one
// whole ring, so the wait for the pump's first block -- and the zeros the
// ring was enabled on -- read as the latency they are.
void audiopump_i2s_starved_reset(void);

#ifdef __cplusplus
}
#endif
