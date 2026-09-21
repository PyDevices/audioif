# Changelog

## Unreleased

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
