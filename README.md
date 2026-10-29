# HLauncher

A Raspberry Pi app launcher for the original HondaLink head unit in my 2014 Civic.

Honda never released a factory CarPlay update for this generation of Civic radio. HLauncher is my first step toward bringing it to the original hardware. Using a Pi through the existing HondaLink connection is the least invasive approach I've tested so far: the radio firmware stays intact, and we can run our own software and plugins on the Pi. It also gives us the flexibility to try things beyond CarPlay.

Future experiments will focus on getting CarPlay running **natively on the head unit itself**. For more on the reverse engineering, experiments and progress, check out [my blog](https://www.evanhorsley.com/blog/).

The radio thinks the Pi is a phone running the older HondaLink app. The Pi sends video over HDMI, while Bluetooth carries the HondaLink handshake and touchscreen input. Opening HondaLink on the radio opens HLauncher. No desktop environment or radio firmware patch is required for this connection.

HLauncher handles the radio connection and provides a home screen for **plugins**. Working plugins now include **CarPlay**, **Android Auto** and **live OBD gauges**. You can enable the apps you want, choose a default, and add your own plugins without rebuilding the launcher.

## Current state

This is working development code, tested on a bench with a **Raspberry Pi 4 2GB**, **Raspberry Pi OS Lite Bookworm 64-bit**, and the HDMI-equipped **2014 Civic HondaLink radio**.

What has been tested:

- Opening the launcher from the radio's HondaLink icon.
- A three-column, two-row tile layout, with Settings built in.
- Enabling/disabling installed plugins and saving a default startup app.
- CarPlay video, taps and swipes through a Carlinkit dongle connected directly to the Pi.
- Returning to HLauncher with the Honda icon inside CarPlay.
- Android Auto through OpenAuto, with the Android phone connected directly to the Pi over USB.
- Live OBD gauges over a Bluetooth LE ELM327 adapter: coolant temperature, oil temperature, long-term fuel trim and MAF, where supported by the vehicle.
- Installing and managing plugins independently of the launcher.
- HDMI output without a Linux desktop or login cursor over the app.

The touch path now retains both contacts through the plugin API, and the CarPlay bridge forwards two-finger gestures using node-CarPlay's multi-touch messages. Normal taps, swipes and Maps pinch-to-zoom—including placing both fingers together—were confirmed on the bench. Display presentation uses offscreen buffers and synchronized DRM page flips; the owner confirmed the previous horizontal tearing was gone. See the [plugin API](docs/plugins.md) and [display setup](docs/setup.md#hdmi) for details.

CarPlay requests **60fps**. That is the requested stream rate, not a guarantee for every phone, dongle or Pi. The panel is **800×480**, but the working **HDMI input is 720×480**. Forcing 800×480 produced a picture with the right side cropped, so the setup uses the radio's advertised 720×480 mode. The radio scales that input to its panel; HLauncher scales video and touch to the actual framebuffer. See [HDMI setup](docs/setup.md#hdmi).

What is still missing:

- **Microphone forwarding.** CarPlay output audio now has an HDMI playback path; audible playback inside HondaLink still needs hardware confirmation. Microphone input is not forwarded to CarPlay.
- A microphone test page in the new launcher. Earlier experiments received microphone PCM through Bluetooth HFP, but the radio required a hands-free call state. The core retains capture support; CarPlay does not use it yet.
- Verification on other Honda radios, Pi models and OS releases.

Android Auto and live OBD gauges are now confirmed working on the project setup.
Android Auto's current build still hard-codes a parked state for bench testing;
see [bench parking state](plugins/android-auto/README.md#bench-parking-state).
OBD sensor availability depends on what the vehicle and adapter expose.

## Hardware

- Raspberry Pi 4, with the tested setup using 2GB RAM.
- A microSD card running Raspberry Pi OS Lite **Bookworm, 64-bit**.
- A HondaLink radio with HDMI input and the older phone-app integration.
- Micro-HDMI-to-HDMI connection from the Pi to the radio.
- Bluetooth pairing between the Pi and HandsFreeLink.
- For CarPlay: a compatible Carlinkit USB dongle and an iPhone.
- For Android Auto: an Android phone connected directly to a Pi USB host port.
- For OBD Gauges: a compatible Bluetooth LE ELM327 adapter.
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

Open **HondaLink** on the radio. You should see CarPlay, Android Auto, OBD Gauges and Settings in the launcher. Android Auto requires its separate engine build. Open CarPlay and connect the iPhone to the dongle. The Honda icon in CarPlay returns to HLauncher; the waiting-for-phone screen also has a Back button.

### 5. Choose your apps

In **Settings → Plugins**, enable or disable installed plugins. Tap **Start with** to cycle between Launcher and an enabled plugin. Settings are saved to `/var/lib/hlauncher/settings.json` and survive a service restart.

Launcher is the initial default. Disabling the selected default plugin resets it to Launcher. Returning through CarPlay's Honda icon always opens the launcher, even if CarPlay is the startup default.

## Plugins

Plugins are separate apps shown as tiles on the launcher. The bundled plugins live in `plugins/`:

| Plugin | What it does | Connection |
| --- | --- | --- |
| CarPlay | iPhone projection using node-CarPlay | Carlinkit USB dongle |
| Android Auto | Android phone projection using OpenAuto | Phone connected directly over USB |
| OBD Gauges | Live coolant/oil temperature, long-term fuel trim and MAF readings | Bluetooth LE ELM327 adapter |

All three are working and included in the default plugin catalog. Android Auto needs the optional engine build, and OBD Gauges needs a compatible BLE ELM327 connection. You can install an external plugin from a local folder or Git repository, or submit one as a pull request to include it here.

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

Protocol logs are in `/var/log/hlauncher`; plugin logs are under `/var/log/hlauncher/plugins/ID`. Logs can contain device identifiers and packet data. Android Auto and BLE OBD logs rotate; other logs may still need manual cleanup.

If the radio cannot open HondaLink, check Bluetooth pairing, `/etc/hlauncher.env`, and the audio/reconnect services. After a Bluetooth daemon restart, restart HLauncher to register its profiles again. If the Linux console appears over HDMI, check the launcher journal and framebuffer format. See [setup and recovery](docs/setup.md#logs-and-recovery) for dongle checks and other failure cases.

## Development

- `hlauncher/` — launcher, Settings, radio protocol, display, touch and audio broker.
- `plugins/carplay/` — CarPlay worker and Node USB bridge.
- `plugins/android-auto/` — OpenAuto adapter and Android Auto plugin worker.
- `plugins/obd/` — live BLE ELM327 gauges with radio-first connection management.
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

HLauncher is GPL-3.0, with preservation of the original author attribution under GPLv3 section 7(b). HLauncher and its HondaLink reverse engineering are by **Evan Horsley (evy0311)**. Distributions using that original code must retain the notices in [NOTICE](NOTICE); third-party credits remain separate. This is an independent project, not affiliated with Honda, Apple or Carlinkit. No Honda firmware images, proprietary radio assets, pairing keys or device captures are included.

### Android Auto

The **Android Auto** plugin uses OpenAuto directly with an Android phone connected
to the Pi's USB port; a Carlinkit dongle is not needed. HLauncher continues to own
HondaLink, display, audio and touch. Build the separately fetched engine with
`sudo bash scripts/install_android_auto.sh`; see
[Android Auto setup and current limits](plugins/android-auto/README.md).

Upstream node-CarPlay is now fetched at install time as well. A source checkout
needs `python3 scripts/fetch_dependencies.py` before the CarPlay bridge checks.
The upstream source is not committed here; our fixes are tracked as a small patch.

Launcher tiles share a glass-style finish with centered app glyphs. Choose Blue,
Red, Green, Amber, Purple or Graphite under **Settings → Tile color**; the choice
is saved across restarts. This changes launcher tiles, not the projected phone UI.

Settings, projection waiting screens and gauge chrome share the selected accent.
Tile tint is nearly uniform, with edge highlights instead of broad gradients.
Launcher-owned UI uses static RGB565 dithering to reduce banding; projected phone
video and HDMI calibration patterns are unchanged.

### System diagnostics

Settings groups plugin controls, tile color, the startup app and diagnostics into
separate entries. **Settings → System diagnostics** shows live HondaLink status,
HDMI output, dongle detection and audio sources. Its System view shows Pi model,
temperature, current/historical power warnings, memory, free storage and uptime.
Sampling runs off the UI thread and refreshes every two seconds.

**Save report** writes a JSON snapshot under `/var/lib/hlauncher/diagnostics/`.
Reports include plugin status and audio counters; they do not contain pairing keys
or Bluetooth addresses. This saves locally on the Pi, not automatically to USB.

Launcher and plugin UI share bundled Roboto fonts, including large gauge readouts.
The font license is in `sdk/hlauncher_sdk/assets/fonts/OFL.txt`.

OBD connection setup is under **Settings > OBD Gauges > Scan**.
The plugin uses live data only; unavailable sensors show a dash. See
[OBD Gauges](plugins/obd/README.md) for supported BLE transports, connection
priority and logs. The live connection is working on the project setup; other
adapters and vehicles may expose different BLE services or supported readings.
