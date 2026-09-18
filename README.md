# audiopump

A throwaway. It exists to answer questions for the live-audio-path spike —
[`docs/spikes/live-audio-path-notes.md`](../docs/spikes/live-audio-path-notes.md)
in the anchor — and it is not a PyDevices repository, not published, and not
built by anyone's `cmods` unless they ask for it.

Two functions, one loop, written against audioif's `audioif_sample_source_t`:

- `audiopump.pull(sample, blocks, status[, path])` runs the loop on the
  calling thread and allocates nothing, so `micropython.heap_lock()` around
  it is a real gate on "the audio pull does not allocate".
- `audiopump.spawn(sample, blocks, status[, path])` runs the same loop on a
  plain pthread with no interpreter state at all — the unix stand-in for a
  FreeRTOS task — and `audiopump.join()` waits for it.

`status` is a 64-byte `bytearray`, read back with `struct.unpack("<8Q", …)`:
blocks, bytes, an FNV-1a 64 digest of every byte pulled, the last buffer
result, a running flag, an error code, and the thread id that ran it.
`path`, when given, is a file the loop `write(2)`s each block to.

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

One global pump, no sink ring, no timing, no locking, nothing staged, no
safety around `deinit`. Every one of those is a finding rather than an
omission — see the notes.
