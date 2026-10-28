# HLauncher

A Raspberry Pi launcher for the original HondaLink head unit in my 2014 Civic.

The Pi acts as the phone side of the older HondaLink connection. Video goes over HDMI; the radio sends touch input back over Bluetooth. No desktop environment or custom radio firmware is needed.

The launcher owns the HondaLink connection, display, touch routing and radio audio access. Apps run as separate plugin processes. Settings is built in; CarPlay is the first bundled plugin.

## Current features

- Six tile positions per page, arranged three across and two high.
- Settings to enable installed plugins and choose what opens when HondaLink starts.
- CarPlay through a supported Carlinkit USB dongle, using node-CarPlay.
- Taps and swipes, with CarPlay's Honda icon returning to the launcher.
- Separate plugin workers and bounded frame buffers, so an app failure can return to the launcher.

CarPlay requests 60fps. Actual performance depends on the phone, dongle and Pi. CarPlay audio and microphone forwarding are not implemented. Android Auto and OBD gauges are future plugins.

## Setup

Tested with a Raspberry Pi 4, Raspberry Pi OS Lite Bookworm **64-bit**, and the HDMI-equipped 2014 Civic HondaLink radio. Connect HDMI and pair Bluetooth with the radio. Plug the Carlinkit dongle directly into the Pi's USB host port.

```bash
git clone https://github.com/evy0311/HLauncher.git
cd HLauncher
sudo bash scripts/install.sh
```

Finish [setup](docs/setup.md) before starting the service. The installer does not start HLauncher or edit HDMI boot settings. Other radio models and OS releases have not been verified.

## Plugins

Bundled plugins live in `plugins/`. You can install another plugin from a folder or Git repository, or submit it as a pull request. External plugins are disabled until enabled in Settings. Settings itself cannot be disabled.

See the [plugin API and installation guide](docs/plugins.md) and the small [example plugin](examples/hello). Plugins are trusted code running under the launcher's account; process isolation is for failure recovery, not a security sandbox.

## Source

- `hlauncher/` — core launcher, settings, framebuffer, radio protocol, touch and audio broker.
- `plugins/carplay/` — CarPlay worker, USB bridge and video decoder.
- `sdk/hlauncher_sdk/` — two-way plugin transport and shared frame buffers.
- `bluetooth/` and `packaging/` — reconnect support and system services.

```bash
bash scripts/test.sh
python3 scripts/check.py
```

The tests use simulated plugins and a video fixture. They do not open a dongle, register Bluetooth profiles or draw on the radio. See [development](docs/development.md) for more.

## Credits

CarPlay dongle communication uses **[node-CarPlay by Rhys Morgan](https://github.com/rhysmorgan134/node-CarPlay)**. The vendored source and built modules retain its MIT license.

The FFmpeg decoder comes from **[MirrorLink-Pi by rsyrnicki](https://github.com/rsyrnicki/mirror-link-pi)**, licensed under GPL-3.0. HLauncher uses that decoder without the MirrorLink network/video transport. FFmpeg, BlueZ and BlueALSA provide the underlying video and Bluetooth support.

See [third-party notices](THIRD_PARTY_NOTICES.md) for source versions and licenses. HLauncher is GPL-3.0; vendored node-CarPlay files retain their MIT license.

This is an independent project, not affiliated with Honda, Apple or Carlinkit. No Honda firmware images, proprietary radio assets, pairing keys or device captures are included.
