# HLauncher

A Raspberry Pi launcher for the original HondaLink head unit in my 2014 Civic.

The Pi acts as the phone side of the older HondaLink connection. Video goes over HDMI; the radio sends touch input back over Bluetooth. No desktop environment is needed. This path uses the radio's existing HondaLink feature, without a custom radio firmware image.

This is the working Pi 4 implementation from the V42 bench setup. It has a CarPlay page and a microphone test page. A plugin-based launcher is the next step; that refactor is not in this version.

## What works

- Opening the launcher from the radio's HondaLink icon.
- HDMI video and touchscreen input over the HondaLink Bluetooth connection.
- CarPlay through a supported Carlinkit USB dongle, including taps and swipes.
- Returning to the Pi launcher with CarPlay's Honda icon.
- A microphone level meter, with capture in a separate worker process.

CarPlay requests 60fps. That is the requested stream rate, not a guarantee for every phone, dongle or Pi. CarPlay audio and microphone forwarding are **not implemented**. The microphone test is separate and currently needs a short simulated hands-free call state to make the radio send microphone PCM. It does not dial a number.

## Hardware and setup

Tested with a Raspberry Pi 4, Raspberry Pi OS Lite Bookworm **64-bit**, and the HDMI-equipped 2014 Civic HondaLink radio. The Carlinkit dongle plugs directly into the Pi's USB host port. Pair the Pi with HandsFreeLink and connect HDMI to the radio. The Pi does not need a USB gadget connection to the radio for this HondaLink path.

See [setup](docs/setup.md) for dependencies, pairing, display setup and services. Other Honda models and newer Pi OS releases have not been verified.

```bash
git clone https://github.com/evy0311/HLauncher.git
cd HLauncher
sudo bash scripts/install.sh
```

The installer copies the application to `/opt/hlauncher` and installs service definitions. It does not start HLauncher or change HDMI boot settings. Finish the steps in the setup guide before enabling the launcher.

## Source

- `app/` — the current HondaLink protocol, launcher, touch and microphone code.
- `runtime/carplay/` — the Node USB bridge and vendored node-CarPlay modules.
- `runtime/video/` — H.264 parsing, decoding and RGB565 output.
- `bluetooth/` — background reconnect support.
- `packaging/` — systemd units and the Bluetooth workaround used by the bench setup.

The versioned Python filenames are retained from the working setup. Changes for this repo are limited to install paths, configurable radio address, per-Pi serial identity, the launcher title and an unlimited service runtime option.

```bash
bash scripts/test.sh
python3 scripts/check.py
```

The first command runs protocol, launcher and bridge tests without hardware. The second checks the installed Linux runtime and decodes a test stream. Neither launches CarPlay on the radio or claims the dongle.

## Credits

CarPlay dongle communication uses **[node-CarPlay by Rhys Morgan](https://github.com/rhysmorgan134/node-CarPlay)**. The vendored source and built modules retain its MIT license. This project is not a reimplementation of that USB driver.

The FFmpeg decoder comes from **[MirrorLink-Pi by rsyrnicki](https://github.com/rsyrnicki/mirror-link-pi)**, licensed under GPL-3.0. HLauncher uses that decoder without the MirrorLink network/video transport. FFmpeg, BlueZ and BlueALSA provide the underlying video and Bluetooth support.

See [third-party notices](THIRD_PARTY_NOTICES.md) for source versions and licenses. HLauncher is distributed under GPL-3.0; the vendored node-CarPlay files retain their MIT license.

This is an independent project, not affiliated with Honda, Apple or Carlinkit. No Honda firmware images, proprietary radio assets, pairing keys or device captures are included.
