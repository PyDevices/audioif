# The audio pump's platform driver

This is the hardware half of the live audio path: one C file that knows what
a thread is, what a mutex is, where the clock comes from and where the audio
goes. The portable half — the pull loop, `service()`, the push ring, the event
queue, the tap, the output ring, the status words, the fault register,
`retarget`/`park` and the finaliser guard — is in the DSP repo and ships with
it on every port. The Python module is still `audiopump` and its surface has
not moved.

Ask a firmware whether this half is in it:

```python
>>> import audiopump
>>> audiopump.driver()
'esp32'          # or 'pthread', 'win32', 'none'
```

`'none'` means no driver bound. That is a real answer — the engine's default
hooks are one thread and no hardware, which is how the WebAssembly build has
always run — but a build that should say `'esp32'` and says `'none'` has a
link problem, and now it says so out loud.

## `_audioif` — the module this half publishes

Private by convention, the way `usbif` ships a C `_usbif` under a Python
package; `audiodev` is the public face. It carries the hardware and nothing
else. The engine's counters — `lock_stats`, `lock_reset`, `fault` — stayed on
`audiopump`, because they are the engine's.

```python
import audiopump, _audioif

cushion = _audioif.i2s_start(port, bclk, ws, dout, 48000,
                             bits=16, channels=2, mclk=13, mclk_fs=256,
                             dma_desc=4, dma_frame=128)
audiopump.spawn(fx.output, 0x7FFFFFFF, status, sink=True)
...
audiopump.shutdown()          # closes the channel with the task
```

| call | what it does |
|---|---|
| `i2s_start(port, bclk, ws, dout, rate, …)` | Opens a TX channel the pull loop writes every block into, and returns the bytes the DMA holds when full — the block-to-wire latency floor. `bits`, `channels`, `mclk`, `mclk_fs`, `dma_desc`, `dma_frame` are keywords. |
| `i2s_start(…, din=PIN)` | Opens the RX half of the **same** channel pair, so one clock tree drives capture and playback and the two DMAs cannot drift. |
| `i2s_start(…, din=, in_port=, in_bclk=, in_ws=, in_mclk=)` | Opens RX on a **different** peripheral, for a board whose microphone is not on the speaker's port. See the warning below. |
| `i2s_stop()` | Closes both channels. |
| `i2s_dma_bytes()`, `i2s_rx_bytes()` | What the two DMAs actually clocked, from their ISRs. Bytes the DMA sent that the pump never wrote *are* the silence a listener heard, so these are how starvation gets measured at all. |
| `Input(sample_rate=, channel_count=, frames=, timeout_ms=)` | An audiosample whose `get_buffer` is an I2S read, so a live microphone is a source like any other and `audioeffects.create(name, Input(…), rate)` builds a graph on it. The read blocks, and that is the pacing. `stats()` reports what it has read and what it has missed. |
| `rt_probe(capture, frames=, lead=, prime=, level=, channels=, timeout_ms=)` | Round-trip latency in frames rather than in host time: it preloads a click into the TX DMA *before* either channel is enabled and captures RX from the same instant. Runs with no pump spawned — two owners of one channel is the failure that sounds like silence. |
| `driver()` | The same name `audiopump.driver()` returns. |

**Two ports are not sample-locked.** `din=` alone opens one channel pair, and
there BCLK and WS are generated once, so capture and playback cannot drift.
`in_port=` on a different peripheral is two clock dividers off one PLL: the
same nominal rate, nothing locking them frame to frame. Measured on the LilyGO
T-Embed S3, whose MAX98357A is on port 1 and whose ES7210 microphones are on
port 0, `rx − tx` stayed at **0 bytes** across forty seconds at a 4 × 128 ring
(0–512 bytes at 2 × 128). That is the honest claim: no drift at that
timescale, not proof of indefinite lock. An hour-long run is what would settle
it and it has not been done.

## What each port implements

| | thread | mutex | clock | sink | microphone |
|---|---|---|---|---|---|
| **ESP32 family** | a FreeRTOS task pinned to the core the interpreter is not on, optionally with its stack in PSRAM | `xSemaphoreCreateRecursiveMutex`, which is priority-inheriting | `esp_timer_get_time` | the I2S channel, written from the pull loop | `Input`, single-port or two-port |
| **unix** | `pthread` | recursive `pthread_mutex` | `clock_gettime` | a file the loop `write(2)`s each block to | — |
| **Windows** | `_beginthreadex` | `CRITICAL_SECTION` | `QueryPerformanceCounter` | a file descriptor | — |
| **WebAssembly** | none — **and none is needed** | — | — | — | — |

WebAssembly is not a gap. That build has no threads (no `-pthread`, no
`SharedArrayBuffer`) and no hardware to drive, and Emscripten's
`pthread_create` *links* and then aborts the whole module at run time with
"Tried to spawn a new thread, but this is not supported" — which would be the
same compiles-links-silently-wrong trap in a new place. So this file compiles
to nothing there, no driver binds, the engine's default hooks take over, and
`audiopump.driver()` says `'none'`, which is exactly true.

Two more things the desktop ports are honest about. There is no audio device
on either: the sink is a file, and what plays it is `audiodev`'s own
transport. And Windows has no `_thread` module at all, so the pump being a
native C thread there is not an optimisation — it is the only way a second
thread exists in that interpreter.

## Building it into a firmware

It is a user C module beside the engine. Both have to be on `USER_C_MODULES`,
and the driver finds the engine's headers itself: `AUDIOIF_DIR` for Make
ports, `AUDIOPUMP_AUDIOIF_DIR` for CMake ports, each defaulting to a sibling
checkout.

A Make port (unix, windows, webassembly) globs one level down, so point it at
the parent of both:

```bash
cd ~/gh/pydevices/cmods
mkdir -p .ucmods_split
ln -sfn ../../audioif    .ucmods_split/audioif
ln -sfn ../../audiopump  .ucmods_split/audiopump
MP_MAKE_EXTRA="USER_C_MODULES=$PWD/.ucmods_split BUILD=build-split FROZEN_MANIFEST=" \
  ./build_mp.sh --port unix
```

A CMake port (esp32) takes the directory itself, and the link must come out
afterwards or the module joins every other build in the workspace:

```bash
ln -sfn ../audiopump ~/gh/pydevices/cmods/audiopump
cd ~/gh/pydevices/cmods
./build_mp.sh --port esp32 --board ESP32_GENERIC_P4 --variant PRE_REV3_C6_WIFI
rm -f ~/gh/pydevices/cmods/audiopump
```

**`micropython.cmake` defines `AUDIOIF_DRIVER_ESP32` itself**, and that is not
belt-and-braces. The IDF does not hand `ESP_PLATFORM` to a user C module, and
the POSIX branch of this file compiles *and links* on esp32 because the IDF's
newlib has `pthread.h` — so keying off the wrong macro gets you an unpinned
pump on a default stack with no sink and nothing failing to say so. That cost
the spike a whole firmware once, and it is most of the reason
`audiopump.driver()` exists.

## Adding a port

RP2 is the obvious next one, and there is nothing to design: the engine's
`src/shared/audioif_port.h` is the whole interface, every one of its sixteen
hooks may be NULL, and a table of nothing but NULLs is a complete one-thread
port. Fill in `thread_start` and the mutex first — those are what turn
`service()` into a pump that runs by itself — then the sink.

The page for it is the engine's own `docs/pump-ports.md`: what each hook must
guarantee, how the weak-symbol binding works and the static-archive trap it
dodges, and the portability gate that keeps platform includes out of the
engine. The one rule to carry away before reading it is the binding rule:
**put the hook table in the same C file as `MP_REGISTER_MODULE`**, or a static
archive can let the engine's weak default win in silence.

A new port belongs in this file, in a fifth branch beside the four above. The
branches are whole rather than a few `#ifdef`s inside one another on purpose —
nothing in the POSIX branch survives on Windows, and mixing them is how the
esp32 trap happened.

## Where this fits

The split, what moved and what it cost:
[live-audio-path-split.md](../docs/spikes/live-audio-path-split.md).

Still a throwaway, still not a PyDevices repository, still not published, and
still not built by anyone's `cmods` unless they ask for it. The rename is
[PyDevices/workspace#4](https://github.com/PyDevices/workspace/issues/4) and
nothing about it has happened yet.

## What it is not

One global pump, and nothing staged. The tail is rooted but not the graph
behind it, so the Python side has to keep holding the components. `deinit` has
no safety around it beyond the engine's lock — build first, re-point, release
last.

The soft-reset hole is closed and worth knowing about, because it is the one
piece of platform trickery that is not behind a hook. The esp32 port has no
soft-reset callback a user C module can register in: `soft_reset_exit` calls a
fixed list of `_deinit()`s and this port has no `MICROPY_BOARD_END_SOFT_RESET`.
But two lines above that list it calls `gc_sweep_all()`, which runs `__del__`
on **every** object that has one, reachable or not. So the engine allocates
one `Guard` with a finaliser, roots it so an ordinary collection never touches
it, and lets the soft reset finalise it — which reaches `teardown` here and
closes the channel. No port patch, and Ctrl-D always leaves the board quiet.
