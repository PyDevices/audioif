# Changelog

## Unreleased

- **`audiobusio.I2SOut.starved()` reports silence on the wire, in bytes.** It
  used to return the engine's sink-refusal count, which needs the pump running
  and the DMA full -- the one case that is not an underrun -- so it read 0
  through a stall that plainly starved the wire, on both chips. It now reports
  audio that should have played and did not, taking whichever of two witnesses
  is further on: the DMA's own byte count, which is right when the ring runs
  dry and `auto_clear` clocks zeros, and the wall clock, which is right when
  the DMA itself stops -- which is what a flash erase does on the ESP32-S3,
  measured at 1.14 seconds of audio lost from one 32 kB write with the pump
  sitting level with the DMA throughout. Neither witness alone sees both. The
  old number keeps its meaning under its real name, `sink_timeouts()`, and
  `_audioif` gains `i2s_sink_bytes()` and `i2s_starved_bytes()` so the
  subtraction is checkable from Python. Silence that was asked for -- a
  stopped or paused output -- is not charged: the count restarts wherever
  feeding legitimately begins, and arms for one ring period so the wait for
  the pump's first block reads as the latency it is.
  ([#8](https://github.com/PyDevices/audioif/issues/8))

## v0.1.0 (2026-09-21)

- **This repository is `audioif`**, the audio hardware layer, and public. It was
  the private `audiopump` driver repo until today; the name belonged to the DSP
  repository, which is [audiodsp](https://github.com/PyDevices/audiodsp) now.
- **First public shape.** The audio pump's platform driver: the `_audioif` C
  module (`i2s_start` with a one-port and a two-port form, `i2s_stop`,
  `i2s_dma_bytes`, `i2s_rx_bytes`, `Input`, `rt_probe`) and a
  CircuitPython-shaped `audiobusio.I2SOut` (`play`, `stop`, `pause`, `resume`,
  `playing`, `paused`, `deinit`, plus `retarget()`, `.status` and `starved()`).
  Drivers for ESP32 (a pinned FreeRTOS task and the I2S peripheral), unix
  (`pthread`) and Windows (`_beginthreadex`); WebAssembly and any port without
  threads run the engine through `audiopump.service()` and need nothing from
  here.
- The portable half — the pull loop, the ring, the event queue, the tap and the
  lock as port hooks — lives in
  [audiodsp](https://github.com/PyDevices/audiodsp). This repository binds to
  it by defining `audiodsp_port_driver()`.
- Proved on an ESP32-P4 (ES8311 codec) and an ESP32-S3 (MAX98357A amplifier),
  on unix and on Windows. What is open is in the issues.
