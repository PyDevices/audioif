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

#ifdef __cplusplus
}
#endif
