# Third-party code

## node-CarPlay

- Author: Rhys Morgan
- Source: https://github.com/rhysmorgan134/node-CarPlay
- Commit: `670f19eda2a0b0047a5a538b9602b263f442433a`
- License: MIT, Copyright (c) 2022 Rhys Morgan
- Included: `plugins/carplay/runtime/usb/vendor/node-carplay/`, with TypeScript source and the JavaScript modules used by the working Pi.
- License text: `plugins/carplay/runtime/usb/vendor/node-carplay/LICENSE` and `third_party/licenses/node-carplay-MIT.txt`.

Our `plugins/carplay/runtime/usb/bridge.mjs` adapts those modules to a headless video/touch stream. The underlying dongle protocol implementation is node-CarPlay's work.

## MirrorLink-Pi

- Source: https://github.com/rsyrnicki/mirror-link-pi
- Commit used by the original integration: `7319b5da4d0df88f8d74b3196163cbe40b0d6043`
- License: GPL-3.0
- Included: `plugins/carplay/runtime/video/avdecode.py`, unchanged from that source snapshot.
- License text: `LICENSE`.

`plugins/carplay/runtime/video/h264.py` contains the streaming parser extracted from our existing integration. The unrelated MirrorLink server is not required by this launcher.

## Installed dependencies

The Node `usb` dependency and its transitive dependencies are recorded in `plugins/carplay/runtime/usb/package-lock.json`; their licenses ship with their npm packages. Python, Pillow, PyGObject, dbus-python, FFmpeg, BlueZ, BlueALSA and ALSA are installed from the OS repositories rather than bundled. Their own licenses apply.
