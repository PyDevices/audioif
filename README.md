# audiopump — the pump's platform driver

**The engine is not here any more.** The portable half of the audio pump —
the pull loop, `service()`, the push ring, the event queue, the tap, the
output ring, the status words, the fault register, `retarget`/`park` and the
finaliser guard — lives in **audioif** now, and ships with it on every port.
The Python module is still called `audiopump` and its surface has not moved.

What is here is the one file that knows what a platform is: `_audioif.c`. The
thread (a FreeRTOS task pinned to the core the interpreter is not on, a
`_beginthreadex` CRT thread on Windows, a pthread on unix), the recursive
priority-inheriting mutex the pump lock is made of, the clock, the pacing, the
two waits, and the hardware — the I2S channel, `Input` (the microphone as an
audiosample) and the round-trip latency probe.

It binds itself to the engine by defining `audioif_port_driver()`, declared in
audioif's `src/shared/audioif_port.h`. Ask which driver bound from Python:

```python
>>> import audiopump
>>> audiopump.driver()
'esp32'          # or 'pthread', 'win32', 'none'
```

Its own module is **`_audioif`** — private by convention, the way `usbif`
ships a C `_usbif` under a Python package; `audiodev` is the public face. It
carries `i2s_start`, `i2s_stop`, `i2s_dma_bytes`, `i2s_rx_bytes`, `Input` and
`rt_probe`. The engine's `lock_stats`, `lock_reset` and `fault` stayed on
`audiopump`, because those are the engine's counters.

On WebAssembly this file compiles to nothing at all: that build has no threads
and no hardware, no driver binds, and `audiopump.driver()` says `"none"` —
which is exactly true, and is the shape the engine's default hooks give.

Why it is split: [live-audio-path-split.md](../docs/spikes/live-audio-path-split.md).

Still a throwaway, still not a PyDevices repository, still not published, and
still not built by anyone's `cmods` unless they ask for it. The rename that
gives this repo the name `audioif` is
[PyDevices/workspace#4](https://github.com/PyDevices/workspace/issues/4) and
nothing about it has happened yet.

---

## What the engine's surface still is, for reference

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
  100 Hz. `audiopump.retarget(sample)` points the pump at a different tail
  while it is parked, which is what a helper swapping the effect class needs
  and what `Phaser`'s cascade rebuild breaks without.
- `audiopump.shutdown()` stops the task, closes I2S and drops every root.
  **It also happens by itself on a soft reset** — see below.
  `audiopump.running()` says whether a pump is live.
- On esp32, `audiopump.i2s_start(port, bclk, ws, dout, rate, ..., din=PIN)`
  opens a TX channel the loop writes every block into, and with `din` the RX
  half of the *same* channel pair, so one clock tree drives both directions.
  `i2s_stop()` closes them; `i2s_dma_bytes()` and `i2s_rx_bytes()` report what
  the two DMAs actually clocked. `audiopump.drain(buf)` is the RAM ring's
  consumer, and `audiopump.info()` reports what the graph says it is.
- `audiopump.Input(sample_rate=, channel_count=, frames=)` is an audiosample
  whose `get_buffer` is an `i2s_channel_read`, so a live microphone is a
  source like any other and `audioeffects.create(name, Input(...), rate)`
  builds a graph on it. The read blocks, which is the pacing.
- `audiopump.rt_probe(capture, ...)` preloads a step into the TX DMA before
  either channel is enabled and captures RX from the same instant, so a
  round-trip latency comes out in frames rather than in host time.

## Dying with the VM

The esp32 port has no soft-reset hook a user C module can register in —
`soft_reset_exit` in `ports/esp32/main.c` calls a fixed list of `_deinit()`s
and this port has no `MICROPY_BOARD_END_SOFT_RESET`. But two lines above that
list it calls `gc_sweep_all()`, which runs `__del__` on **every** object that
has one, reachable or not. So `audiopump` allocates one `Guard` with
`mp_obj_malloc_with_finaliser`, roots it so an ordinary collection never
touches it, and lets the soft reset finalise it. No port patch.

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

One global pump, and nothing staged. `deinit` still has no safety around it —
park first, always. The tail is rooted but not the graph behind it, so the
Python side has to keep holding the components. The soft-reset hole is closed;
the rest are findings rather than omissions. See the notes.
