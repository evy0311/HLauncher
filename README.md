# HLauncher

A Raspberry Pi app launcher for the original HondaLink head unit in my 2014 Civic.

Honda never released a factory CarPlay update for this generation of Civic radio. HLauncher is my first step toward bringing it to the original hardware. Using a Pi through the existing HondaLink connection is the least invasive approach I've tested so far: the radio firmware stays intact, and we can run our own software and plugins on the Pi. It also gives us the flexibility to try things beyond CarPlay.

Future experiments will focus on getting CarPlay running **natively on the head unit itself**. For more on the reverse engineering, experiments and progress, check out [my blog](https://www.evanhorsley.com/blog/).

The radio thinks the Pi is a phone running the older HondaLink app. The Pi sends video over HDMI, while Bluetooth carries the HondaLink handshake and touchscreen input. Opening HondaLink on the radio opens HLauncher. No desktop environment or radio firmware patch is required for this connection.

HLauncher handles the radio connection and provides a home screen for plugins. CarPlay is the first working plugin, using a Carlinkit USB dongle and node-CarPlay.

## Current state

This is working development code, tested on a bench with a **Raspberry Pi 4 2GB**, **Raspberry Pi OS Lite Bookworm 64-bit**, and the HDMI-equipped **2014 Civic HondaLink radio**.

What has been tested:

- Opening the launcher from the radio's HondaLink icon.
- A three-column, two-row tile layout, with Settings built in.
- Enabling/disabling installed plugins and saving a default startup app.
- CarPlay video, taps and swipes through a Carlinkit dongle connected directly to the Pi.
- Returning to HLauncher with the Honda icon inside CarPlay.
- HDMI output without a Linux desktop or login cursor over the app.

The touch path now retains both contacts through the plugin API, and the CarPlay bridge forwards two-finger gestures using node-CarPlay's multi-touch messages. Normal taps, swipes and Maps pinch-to-zoom—including placing both fingers together—were confirmed on the bench. Display presentation uses offscreen buffers and synchronized DRM page flips; the owner confirmed the previous horizontal tearing was gone. See the [plugin API](docs/plugins.md) and [display setup](docs/setup.md#hdmi) for details.

CarPlay requests **60fps**. That is the requested stream rate, not a guarantee for every phone, dongle or Pi. The panel is **800×480**, but the working **HDMI input is 720×480**. Forcing 800×480 produced a picture with the right side cropped, so the setup uses the radio's advertised 720×480 mode. The radio scales that input to its panel; HLauncher scales video and touch to the actual framebuffer. See [HDMI setup](docs/setup.md#hdmi).

What is still missing:

- **CarPlay audio and microphone forwarding.** The video and touch path works, but this is not yet a complete CarPlay replacement.
- Android Auto and OBD gauges. These are planned plugins, not included working apps.
- A microphone test page in the new launcher. Earlier experiments received microphone PCM through Bluetooth HFP, but the radio required a hands-free call state. The core retains capture support; CarPlay does not use it yet.
- Verification on other Honda radios, Pi models and OS releases.

## Hardware

- Raspberry Pi 4, with the tested setup using 2GB RAM.
- A microSD card running Raspberry Pi OS Lite **Bookworm, 64-bit**.
- A HondaLink radio with HDMI input and the older phone-app integration.
- Micro-HDMI-to-HDMI connection from the Pi to the radio.
- Bluetooth pairing between the Pi and HandsFreeLink.
- A compatible Carlinkit USB dongle for the CarPlay plugin, plus an iPhone.
- Suitable power for the Pi.

Connect the display to the Pi 4's **HDMI0** port, nearest USB-C power. The Carlinkit dongle plugs into a **Pi USB host port**. HLauncher does not need a USB data connection from the Pi to the radio. USB/IP and VirtualHere are not needed for this setup.

## Setup

The full [setup guide](docs/setup.md) covers pairing, display configuration, migration and troubleshooting. For a fresh Pi:

### 1. Install

```bash
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/evy0311/HLauncher.git
cd HLauncher
sudo bash scripts/install.sh
```

The installer installs dependencies, copies the application to `/opt/hlauncher`, installs the service files and checks the USB/video runtime. It does **not** start HLauncher or edit HDMI boot settings.

It also installs a Bluetooth workaround that disables AVRCP and restarts BlueZ after a daemon failure. This was needed during bench testing. Review the [Bluetooth setup](docs/setup.md#bluetooth) if the Pi already has Bluetooth services or overrides configured; only one BlueALSA daemon should run.

### 2. Pair with the radio

Follow the [pairing steps](docs/setup.md#bluetooth). The Pi must advertise the audio profiles as well as provide the HondaLink control connection. Confirm the pairing code and trust the HandsFreeLink device.

Set the **radio's Bluetooth address**, not the Pi's address, in:

```bash
sudoedit /etc/hlauncher.env
```

```text
HLAUNCHER_RADIO_ADDRESS=AA:BB:CC:DD:EE:FF
HLAUNCHER_LOG_DIR=/var/log/hlauncher
```

Replace the example address with the paired radio's address. The listener only accepts that peer. Pairing records and Wi-Fi credentials are not included in this repository.

### 3. Check the display

Connect HDMI and run:

```bash
sudo fbset -depth 16
sudo python3 /opt/hlauncher/scripts/check.py --display
```

The renderer requires RGB565, 16 bits per pixel. If HDMI is not detected, follow the [display setup](docs/setup.md#hdmi), including the optional forced output mode. The service hides the console cursor while it is running.

### 4. Start HLauncher

Stop any older launcher or application using the same framebuffer, Bluetooth profiles or USB dongle first. Then:

```bash
sudo systemctl enable --now hlauncher-audio hlauncher-connect hlauncher
```

Open **HondaLink** on the radio. You should see Settings and CarPlay in the launcher. Open CarPlay and connect the iPhone to the dongle. The Honda icon in CarPlay returns to HLauncher; the waiting-for-phone screen also has a Home button.

### 5. Choose your apps

In **Settings**, enable or disable installed plugins. Tap **Start with** to cycle between Launcher and an enabled plugin. Settings are saved to `/var/lib/hlauncher/settings.json` and survive a service restart.

Launcher is the initial default. Disabling the selected default plugin resets it to Launcher. Returning through CarPlay's Honda icon always opens the launcher, even if CarPlay is the startup default.

## Plugins

Bundled plugins live in `plugins/`. CarPlay is included and enabled initially. You can install an external plugin from a local folder or Git repository, or submit one as a pull request to include it here.

```bash
cd /opt/hlauncher
sudo python3 -m hlauncher plugins list
sudo python3 -m hlauncher plugins install /path/to/plugin
# Or:
sudo python3 -m hlauncher plugins install https://github.com/OWNER/REPO.git --subdir plugins/NAME
sudo systemctl restart hlauncher
```

External plugins are disabled until enabled in Settings. Read the author's dependency instructions before enabling one; the installer copies source without running install hooks.

The core owns Bluetooth, the HondaLink protocol, framebuffer presentation, touch routing and radio audio access. Plugins run in separate processes and use a two-way API for lifecycle, input, frames and supported audio requests. A plugin failure can return to the launcher without stopping the radio connection.

See the [plugin API](docs/plugins.md) and [example plugin](examples/hello). Process separation is for failure recovery, not a security sandbox: the current services and plugins run as root.

## Logs and troubleshooting

```bash
sudo systemctl status hlauncher hlauncher-audio hlauncher-connect --no-pager
sudo journalctl -u hlauncher -n 100 --no-pager
sudo systemctl restart hlauncher
```

Protocol logs are in `/var/log/hlauncher`; plugin logs are under `/var/log/hlauncher/plugins/ID`. Logs can contain device identifiers and packet data. Log rotation is not implemented yet.

If the radio cannot open HondaLink, check Bluetooth pairing, `/etc/hlauncher.env`, and the audio/reconnect services. After a Bluetooth daemon restart, restart HLauncher to register its profiles again. If the Linux console appears over HDMI, check the launcher journal and framebuffer format. See [setup and recovery](docs/setup.md#logs-and-recovery) for dongle checks and other failure cases.

## Development

- `hlauncher/` — launcher, Settings, radio protocol, display, touch and audio broker.
- `plugins/carplay/` — CarPlay worker, Node USB bridge and video decoder.
- `sdk/hlauncher_sdk/` — plugin control transport and shared frame buffers.
- `bluetooth/` — background reconnect support.
- `packaging/` — systemd service definitions.

```bash
bash scripts/test.sh
python3 scripts/check.py
```

The tests cover protocol framing, launcher behavior, settings persistence, plugin transport and failure recovery. The runtime check decodes a video fixture. These checks do not open the dongle, register radio profiles or draw on the radio. The plugin refactor also passed a live bench test: launcher tiles responded, CarPlay displayed, and the Honda icon returned to the launcher.

See [development](docs/development.md) and the [bench migration notes](docs/migration.md). A fresh installation uses the services above; the development Pi currently reuses its existing Bluetooth services through a local drop-in.

## Credits and license

CarPlay dongle communication uses **[node-CarPlay by Rhys Morgan](https://github.com/rhysmorgan134/node-CarPlay)**. Its source and built modules retain their MIT license.

The FFmpeg decoder helper is by **[rsyrnicki](https://github.com/rsyrnicki)** and is GPL-3.0. FFmpeg, BlueZ, BlueALSA and ALSA provide the underlying video and Bluetooth support. See [third-party notices](THIRD_PARTY_NOTICES.md) for versions and licenses.

HLauncher is GPL-3.0. This is an independent project, not affiliated with Honda, Apple or Carlinkit. No Honda firmware images, proprietary radio assets, pairing keys or device captures are included.
