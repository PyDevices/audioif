# audioif

**audioif has moved.** It now lives in
[micropython-pydevices, `modules/audioif`](https://github.com/PyDevices/micropython-pydevices/tree/main/modules/audioif), with its history.
It never published on its own: it reaches you in firmware built by
micropython-pydevices' `build_mp.py`, so that is where it is built, tested and
changed now.

Name it in a build as before: `build_mp.py ... --modules audioif` (or `all`).

Your code doesn't change: `audiobusio` and `_audioif` import as before. Open issues and pull
requests against [micropython-pydevices](https://github.com/PyDevices/micropython-pydevices).
This repository is kept read-only as a record.
