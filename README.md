# audiopump

A throwaway. It exists to answer questions for the live-audio-path spike —
[`docs/spikes/live-audio-path-notes.md`](../docs/spikes/live-audio-path-notes.md)
in the anchor — and it is not a PyDevices repository, not published, and not
built by anyone's `cmods` unless they ask for it.

Three jobs, one loop, written against audioif's `audioif_sample_source_t`:

- `audiopump.pull(sample, blocks, status[, path])` runs the loop on the
  calling thread and allocates nothing, so `micropython.heap_lock()` around
  it is a real gate on "the audio pull does not allocate".
- `audiopump.spawn(sample, blocks, status, ...)` runs the same loop off the
  interpreter thread — a plain pthread on unix, on esp32 a **FreeRTOS task
  pinned to the core the interpreter is not on** — and `audiopump.join()`
  waits for it. Keywords: `sink`, `ring`, `core`, `prio`, `stack`, `psram`,
  `timeout_ms`.
- `audiopump.park()` / `unpark()` is the handoff: the pump finishes the block
  it is in, parks, and does not touch the graph until unparked. On esp32 it
  wakes on a direct-to-task notify, never `vTaskDelay` — this port's tick is
  100 Hz.
- On esp32, `audiopump.i2s_start(port, bclk, ws, dout, rate, ...)` opens a TX
  channel the loop writes every block into, `i2s_stop()` closes it, and
  `i2s_dma_bytes()` reports what the DMA actually clocked out.
  `audiopump.drain(buf)` is the RAM ring's consumer, and `audiopump.info()`
  reports what the graph says it is.

`status` is a 192-byte `bytearray`, read back with `struct.unpack("<24Q", …)`:
blocks, bytes, an FNV-1a 64 digest of every byte pulled, the last buffer
result, a running flag, an error code, and the thread id that ran it.
`path` (unix) is a file the loop `write(2)`s each block to. The rest of the
words are the ring, the sink and the timings; the enum in `audiopump.c` is the
list.

Building it for esp32 is the same symlink trick, into `cmods` itself so the
board's other usermods come too — and the link must come out afterwards or the
module joins every other build in the workspace:

```bash
ln -sfn ../audiopump ~/gh/pydevices/cmods/audiopump
cd ~/gh/pydevices/cmods && ./build_mp.sh --port esp32 --board ESP32_GENERIC_P4 --variant PRE_REV3_C6_WIFI
rm -f ~/gh/pydevices/cmods/audiopump
```

The IDF does **not** define `ESP_PLATFORM` for a user C module, and the POSIX
branch of this file compiles and links on esp32 anyway (newlib has
`pthread.h`), so `micropython.cmake` defines `AUDIOPUMP_ESP32` itself. Getting
that wrong gives you an unpinned pump with no I2S and nothing saying so.

## Building it

It is a Make-port user C module. The workspace builds it through a slim
usermod tree so nothing else in `cmods` changes:

```bash
cd ~/gh/pydevices/cmods
mkdir -p .ucmods_spike
ln -sfn ../../audioif .ucmods_spike/audioif
ln -sfn ../../audiopump .ucmods_spike/audiopump
MP_MAKE_EXTRA="USER_C_MODULES=$PWD/.ucmods_spike BUILD=build-spike FROZEN_MANIFEST=" \
  ./build_mp.sh --port unix --variant standard
```

`AUDIOIF_DIR` defaults to the sibling `audioif` checkout; set it if yours is
somewhere else.

## What it is not

One global pump. Nothing staged, no safety around `deinit`, and — the one
that matters — nothing tears it down on a soft reset, so the task outlives the
heap that owns its graph and goes on playing memory nobody owns. Every one of
those is a finding rather than an omission; see the notes.
