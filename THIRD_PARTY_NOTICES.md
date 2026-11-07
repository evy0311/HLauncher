# Third-party code

## node-CarPlay

- Author: Rhys Morgan
- Source: https://github.com/rhysmorgan134/node-CarPlay
- Commit: `670f19eda2a0b0047a5a538b9602b263f442433a`
- License: MIT, Copyright (c) 2022 Rhys Morgan
- Fetched separately by `scripts/fetch_dependencies.py` into an ignored build directory at `plugins/carplay/runtime/usb/vendor/node-carplay/`. The pinned source and local changes are recorded in `third_party/dependencies.json` and `third_party/patches/node-carplay.patch`.
- License text: `plugins/carplay/runtime/usb/vendor/node-carplay/LICENSE` and `third_party/licenses/node-carplay-MIT.txt`.

Our `plugins/carplay/runtime/usb/bridge.mjs` adapts those modules to a headless video/touch stream. The underlying dongle protocol implementation is node-CarPlay's work.

## FFmpeg decoder helper

- Author: rsyrnicki (https://github.com/rsyrnicki)
- Commit used by the original integration: `7319b5da4d0df88f8d74b3196163cbe40b0d6043`
- License: GPL-3.0
- Adapted in `sdk/hlauncher_sdk/video/avdecode.py` for HLauncher, including color handling and background decoding. The old CarPlay path remains a compatibility import.
- License text: `LICENSE`. Original attribution is retained here; HLauncher modifications are covered by the same GPL license.

`sdk/hlauncher_sdk/video/h264.py` contains the streaming parser extracted from our existing integration. The old CarPlay path is a compatibility import.

## Installed dependencies

The Node `usb` dependency and its transitive dependencies are recorded in `plugins/carplay/runtime/usb/package-lock.json`; their licenses ship with their npm packages. Python, Pillow, PyGObject, dbus-python, Bleak, dbus-fast, FFmpeg, BlueZ, BlueALSA and ALSA are installed from the OS repositories rather than bundled. Their own licenses apply.


## Roboto

Launcher and plugin UI use Roboto from Google's official fonts repository:
https://github.com/google/fonts/tree/main/ofl/roboto . The unmodified variable
font and SIL Open Font License 1.1 are included in
`sdk/hlauncher_sdk/assets/fonts/`. The SDK selects normal-width Regular,
Medium, SemiBold and Bold weights at runtime.

## OpenAuto and aasdk

Android Auto uses the OpenAuto projection engine, fetched separately; no upstream
engine source or compiled libraries are committed to HLauncher.

- OpenAuto: https://github.com/opencardev/openauto, revision
  `4cc739b813622739b09352655581072fc4d39280`, GPL-3.0-or-later.
- aasdk: https://github.com/opencardev/aasdk, revision
  `9bf6adf933665dee26532201719fac14a047ccf1`, GPL-3.0-or-later as stated in its
  source-file notices (the pinned repository lacks a top-level LICENSE file).
- Original authors include Michal Szwaj / f1x.studio and OpenCarDev contributors;
  preserve individual source-file notices.
- `scripts/install_android_auto.sh` fetches those exact revisions into
  `/opt/hlauncher-deps/src` and builds the engine outside HLauncher. Our small
  adaptation patches are `third_party/patches/openauto.patch` and
  `third_party/patches/aasdk.patch` (the latter completes upstream
  fallback logging macros on the pinned version).
- The `plugins/android-auto/native` adapter connects OpenAuto's public services
  to HLauncher's display/audio/touch interfaces. Qt and the other build/runtime
  dependencies retain their own licenses.

If distributing binaries, include the applicable notices/licenses and provide
corresponding source, including these patches and build instructions. Fetching
upstream code during installation does not remove those obligations. Crankshaft
is not installed or bundled.

## SoXR, libsamplerate and PipeWire audio processing

Production sample-rate conversion dynamically uses the OS-provided SoXR library
(https://sourceforge.net/projects/soxr/), VHQ 28-bit linear-phase mode, through its
public C API. SoXR is LGPL-2.1-or-later licensed; its source and binaries are not
bundled here. The distribution supplies the library and its license.

The benchmark reference in scripts/reference_libsamplerate.py uses the
OS-provided BSD-2-Clause libsamplerate library
(https://github.com/libsndfile/libsamplerate), SRC_SINC_BEST_QUALITY. It is not a
production fallback. No upstream library source or binary is bundled here.
NumPy and the OS-provided PipeWire/ALSA libraries retain their own licenses.
The private EQ graph uses PipeWire's built-in biquad filters. The original native
PCM bridge is built locally and dynamically links the OS PipeWire libraries.

## BlueALSA button integration

The optional button-aware daemon is built separately from BlueALSA 4.0.0
(commit dd05a1baa261b94da9ba977b5e3392c8b4dc7a5e),
https://github.com/arkq/bluez-alsa, licensed under MIT. Upstream source and its
license remain under /opt/hlauncher-deps/src/bluealsa-buttons. HLauncher changes
only configuration defaults using scripts/patch_button_audio.py.
