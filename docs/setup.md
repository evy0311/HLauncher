# Setup

The reference setup is a Pi 4 running Raspberry Pi OS Lite Bookworm, 64-bit. It uses HDMI and Bluetooth to the radio and a locally connected Carlinkit dongle. No X11, Wayland, browser or desktop is required.

## Install

From the Git checkout:

```bash
sudo bash scripts/install.sh
```

This installs OS dependencies, copies the code to `/opt/hlauncher`, runs `npm ci` using the committed lockfile, and checks the video/USB runtime. It leaves HLauncher services stopped; OS package installation may start package-provided services. Existing `/opt/hlauncher` installations are backed up before copying files. Pairing records and Wi-Fi settings are not copied or changed.

The installed units run as root because the current implementation accesses the framebuffer, console, Bluetooth profiles and USB dongle directly. Splitting those privileges is future work.

If you are migrating from the development setup, stop its launcher and avoid running two BlueALSA daemons or two CarPlay bridges:

```bash
sudo systemctl stop civic-hdmi-pi4-v42.service
sudo systemctl disable --now civic-bt-bench.service civic-bt-connect.service
```

Those commands apply only if those old units exist. Stop any other application that is opening the same dongle or framebuffer. Keep the old files for rollback.

## Bluetooth

The installer adds a BlueZ drop-in which disables AVRCP and restarts Bluetooth after a daemon failure. AVRCP caused daemon failures during this project's bench tests. This workaround can affect other Bluetooth uses of the Pi.

Check for other `bluetooth.service.d` overrides before proceeding. The older `99-civic-watchdog.conf`, if present, already implements the same workaround. Do not run another BlueALSA instance alongside `hlauncher-audio`.

```bash
sudo systemctl disable --now bluealsa.service bluealsa-aplay.service
sudo systemctl restart bluetooth
sudo systemctl start hlauncher-audio
bluetoothctl --agent DisplayYesNo
```

At the Bluetooth prompt:

```text
default-agent
power on
system-alias HLauncher
pairable on
discoverable on
```

Add a phone from the radio's HandsFreeLink settings. Select HLauncher and confirm the matching code on both sides. Approve profile authorization prompts if shown. Then:

```text
devices Paired
trust AA:BB:CC:DD:EE:FF
quit
```

Use the **HandsFreeLink radio's** address, not the Pi controller address. Replace the example address everywhere below. Save it in `/etc/hlauncher.env`:

```bash
sudoedit /etc/hlauncher.env
```

```text
HLAUNCHER_RADIO_ADDRESS=AA:BB:CC:DD:EE:FF
HLAUNCHER_LOG_DIR=/var/log/hlauncher
```

The address must match the paired peer: the listener rejects connections from other devices. The reconnect service trusts and reconnects an already-paired radio; it does not pair automatically.

## HDMI

Use the Pi 4's HDMI0 connector, the micro-HDMI connector nearest USB-C power, and connect it to the radio's HDMI input. The panel is **800x480**, but the radio advertises **720x480 and 640x480 over HDMI**. The working setup uses 720x480. A forced 800x480 signal appeared on the radio and was confirmed at the Pi framebuffer, but later testing showed that its right side was cropped. It was reverted. Accepting a signal does not mean the radio displays its entire active area correctly. Touch coordinates are scaled to the actual framebuffer size.

The renderer requires RGB565, 16 bits per pixel. The launcher unit sets this before starting:

```bash
sudo fbset -depth 16
fbset -s
sudo python3 /opt/hlauncher/scripts/check.py --display
```

Expect `rgba 5/11,6/5,5/0,0/0`. The check inspects the framebuffer without drawing to it. A framebuffer with a different layout is rejected rather than displaying corrupt pixels.

Use the default Bookworm KMS display driver (`dtoverlay=vc4-kms-v3d`). If HDMI isn't detected at boot, first check the cable, HDMI connector and radio input. To force the working 720x480 output on this Civic radio, append this to the existing **single line** in `/boot/firmware/cmdline.txt`:

```text
video=HDMI-A-1:720x480@60D
```

Back up that file first and retain its existing root/PARTUUID and other arguments. Reboot after changing it. HLauncher does not edit boot settings automatically. The `D` forces digital output. Use the advertised mode rather than forcing the panel resolution; the tested 800x480 input cropped the picture. A 60Hz HDMI mode does not guarantee a 60fps CarPlay stream.

The launcher switches tty1 to graphics mode while it is running, hiding the login cursor. It restores the previous console mode on a normal exit.

The default renderer uses DRM/KMS with two RGB565 buffers. It fills the offscreen buffer and flips at vertical blank rather than overwriting the buffer currently being scanned out. Presentation runs on its own thread with a latest-frame slot, so the Bluetooth loop does not wait for the display. This addresses the horizontal split seen during CarPlay swipes with direct `/dev/fb0` writes.

Look for `display_backend` with `backend: drm` and `vsync: true` in the journal. `display_pageflips` records completed flips and dropped pending frames. If DRM initialization or presentation fails, the launcher logs the failure and falls back to the older framebuffer path, which may tear. For diagnosis, add `HLAUNCHER_DISPLAY=fbdev` to `/etc/hlauncher.env` and restart HLauncher to explicitly select that older path. Remove the override to use DRM again. With DRM active, `/dev/fb0` still reports the console framebuffer geometry, but reading its pixels does not capture the application's scanout buffers.

## Start

Plug the Carlinkit dongle into a Pi USB host port. Connect the iPhone to the dongle. USB/IP and VirtualHere are not needed for the Pi 4 setup.

```bash
sudo systemctl enable --now hlauncher-audio hlauncher-connect hlauncher
```

Open HondaLink on the radio. Select CarPlay in the Pi launcher. Tapping CarPlay's Honda icon returns to the Pi launcher; it does not exit to the radio's home screen. A Home button is also available on the waiting-for-phone page.

For a manual two-hour run instead of the installed launcher service:

```bash
sudo systemctl stop hlauncher
sudo bash -c 'set -a; . /etc/hlauncher.env; set +a; cd /opt/hlauncher; exec /usr/bin/python3 -m hlauncher run --seconds 7200'
```

Start the installed service again afterward with `sudo systemctl start hlauncher`. Never run both listeners at once.

## Plugins and preferences

Settings is built into the launcher. It lists every installed plugin and lets you enable or disable it. Tap **Start with** to cycle between Launcher and the enabled plugins. Changes are saved in `/var/lib/hlauncher/settings.json`. Disabling the default plugin resets the default to Launcher. Returning with CarPlay's Honda icon always goes to the launcher, even when CarPlay is the default.

CarPlay, Android Auto and OBD Gauges are included and enabled initially. The gauges currently use simulated values and do not connect to an OBD adapter. Android Auto requires the separately built OpenAuto engine: run `sudo bash scripts/install_android_auto.sh`, then connect an Android phone directly to the Pi USB port. It is experimental pending phone testing. See [plugins](plugins.md) for installing an external plugin or writing one.

The core exposes an opt-in microphone capture API. The radio still gates live microphone samples behind its hands-free call state. CarPlay output PCM is routed through HDMI; audible playback inside HondaLink is pending confirmation. No automatic call simulation is added; the earlier microphone experiment remains documented in Git history.

## Logs and recovery

```bash
sudo systemctl status hlauncher hlauncher-audio hlauncher-connect --no-pager
sudo journalctl -u hlauncher -n 100 --no-pager
sudo journalctl -u hlauncher-connect -n 50 --no-pager
lsusb -d 1314:
sudo node /opt/hlauncher/plugins/carplay/runtime/usb/bridge.mjs --check
```

Protocol and bridge logs are written to `/var/log/hlauncher`. They can contain device identifiers and packet contents; review them before sharing. Log rotation is not implemented in this snapshot.

If Bluetooth restarts and HondaLink no longer opens, restart HLauncher so it registers its profiles again:

```bash
sudo systemctl restart hlauncher
```

If the display shows the Linux console, inspect the HLauncher journal and framebuffer format. If the waiting page cannot find the dongle, use `lsusb` and ensure another CarPlay process has not claimed it. Kernel USB stalls may require a Pi reboot; restarting a userspace service cannot always recover them.

To stop the installation:

```bash
sudo systemctl disable --now hlauncher hlauncher-connect hlauncher-audio
```

The BlueZ workaround is `/etc/systemd/system/bluetooth.service.d/90-hlauncher.conf`. Remove that file and restart Bluetooth only if you also want to undo the workaround. Keep your pairing records.


### HDMI audio

CarPlay PCM goes through the plugin API to a core-owned mixer and one `aplay` worker. The mixer converts simultaneous streams
to 48 kHz stereo; `config/alsa-hdmi.conf` selects `vc4hdmi0`
(the HDMI connector nearest the Pi 4 power connector). The mixer uses Python 3.11 audioop to convert each incoming stream;
ALSA performs HDMI IEC958 framing. System-wide audio defaults are
unchanged. Music, prompts and received call audio use this output; microphone
capture remains separate. Audio control/volume messages are logged; automatic
media ducking is not implemented yet.

`audio_hdmi_open`, `audio_hdmi_progress` and `audio_hdmi_alsa` in the launcher journal
show device selection, PCM writes/drops and ALSA diagnostics. Successful writes
verify software delivery, not that HondaLink selected that physical input.
Use `HLAUNCHER_AUDIO_DEVICE` to override the ALSA endpoint for diagnosis.
Playback failures retry after five seconds and do not stop video or HondaLink.

### CarPlay picture controls

Open **Settings → CarPlay color** for saturation, contrast and brightness sliders.
The changes affect only decoded CarPlay video; launcher colors and HDMI mode/range
remain unchanged. **Reset** restores saturation 100%, contrast 100%, brightness 0.
**Preview CarPlay** returns to the plugin with the new values.

For adjustment while CarPlay remains visible, SSH to the Pi and run:

```bash
cd /opt/hlauncher
sudo python3 -m hlauncher colors --interactive
```

Up/Down selects a slider, Left/Right adjusts it, R resets, Q exits. A one-shot edit:

```bash
sudo python3 -m hlauncher colors --saturation 85
sudo python3 -m hlauncher colors --contrast 95 --brightness 0
sudo python3 -m hlauncher colors --reset
```

These controls share `/var/lib/hlauncher/carplay-color.json`. Writes are atomic,
values are validated, and the video worker checks for changes every 100 ms.
A retained decoder frame allows adjustments to redraw even when the phone is not
sending new pictures. No plugin restart or radio firmware change is needed.
Changes are applied by libswscale during its existing YUV-to-RGB conversion;
there is no extra full-frame Python pixel filter. The decoder honors declared H.264 color matrix and input range metadata.
When metadata is unspecified, the original conversion defaults are retained.
HDMI output range and launcher colors are unchanged. Logs include `carplay_picture_applied`.

`carplay_color_conversion` records the declared codec color space/range and the
selected conversion. Matrix code 1 is BT.709; source-range 1 is full and 0 limited.
Unspecified codec metadata is logged and does not trigger a guessed conversion.

Picture-control regression check (no radio or dongle access):

```bash
python3 scripts/check_picture.py
```

This exercises successive legacy full-range YUVJ frames. Their converter context
can be rebuilt at the same address, so pointer identity alone cannot establish
that color controls remain configured. The decoder normalizes the equivalent
YUV layout, retains full-range semantics, and reasserts controls after every
context acquisition. This also avoids repeated full-range context allocations.


### HDMI color range

HLauncher sets HDMI Broadcast RGB to **Limited (16–235)** whenever its DRM display
opens. On the tested Civic receiver, Automatic/Full lost distinctions between
pale map colors; Limited restored them with neutral CarPlay picture controls.
This is an HDMI output setting, separate from the decoder and CarPlay sliders.
Failures are logged and do not prevent the launcher from opening.

Settings → CarPlay color → HDMI test pattern compares Auto, Full and Limited.
Leaving the test restores the range that was active when it opened, normally
Limited. For other displays, `HLAUNCHER_HDMI_RGB=auto` or `full` overrides the
default through the service environment. No radio firmware change is involved.

### Watch song metadata over SSH

With CarPlay open and music playing:

```bash
cd /opt/hlauncher
python3 scripts/now_playing.py
```

Press Ctrl+C to stop the viewer; playback continues. For one snapshot or streaming
JSON, use `python3 -m hlauncher now-playing` or
`python3 -m hlauncher now-playing --watch --json`. Missing reports show a waiting
message, never invented song data. This does not forward anything to the radio.


### Background audio and gauges

Start CarPlay and play music, then tap its Honda-logo return item (labelled
HLauncher) to return to the launcher. Open OBD Gauges; CarPlay audio continues.
The four Civic Si-style gauges show simulated coolant/oil temperature (°F), RPM
and battery voltage. The demo label is hidden by request; these are still simulated values, not live vehicle data.

Settings → CarPlay → Background On/Off controls whether it survives leaving the
screen. Background On is the default. Turning it off closes a background CarPlay
worker immediately, or closes it when leaving if it is currently foreground.
Video RGB conversion and presentation pause in the background; compressed video
is still decoded to preserve reference frames and resume a current picture.
USB traffic, PCM audio, keepalives and media messages continue. No second CarPlay
process is started when returning. OBD Gauges has no background mode and closes
on Back or when another plugin replaces it. Disabling CarPlay stops its audio.

The return-item label is sent through the adapter's standard icon configuration
before Open; the existing OEM icon PNG is not replaced. A phone reconnection may
be needed for the label change to appear.
