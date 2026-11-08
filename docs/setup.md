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

Automatic enrollment and the setup wizard are described in [first boot and recovery](onboarding.md). Start the dedicated agent and services after stopping any competing BlueALSA instance:

```bash
sudo systemctl disable --now bluealsa.service bluealsa-aplay.service
sudo systemctl restart bluetooth
sudo systemctl enable --now hlauncher-firstboot hlauncher-pairing hlauncher-recovery hlauncher-audio hlauncher-connect hlauncher
```

Add **HLauncher** from the radio's HandsFreeLink settings during the five-minute pairing window. Confirm on the radio, then open HLauncher through HondaLink to complete setup. The Pi accepts a qualifying first candidate and saves its address only after a successful HondaLink handshake. Subsequent connections are limited to that saved radio. Do not run a competing `bluetoothctl` default agent during enrollment.

A previously paired, valid `HLAUNCHER_RADIO_ADDRESS` in `/etc/hlauncher.env` is adopted once for migration. New installations can leave it all zeroes. Use System → Radio & Wi-Fi to reopen pairing or use the authenticated phone recovery page if automatic identification fails.

## HDMI

Use the Pi 4's HDMI0 connector, the micro-HDMI connector nearest USB-C power, and connect it to the radio's HDMI input. The panel is **800x480**, but the radio advertises **720x480 and 640x480 over HDMI**. The working setup uses 720x480. A forced 800x480 signal appeared on the radio and was confirmed at the Pi framebuffer, but later testing showed that its right side was cropped. It was reverted. Accepting a signal does not mean the radio displays its entire active area correctly. Touch coordinates are scaled to the actual framebuffer size.

The renderer requires RGB565, 16 bits per pixel. The Bluetooth bootstrap sets this before opening the display:

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

Back up that file first and retain its existing root/PARTUUID and other arguments. Reboot after changing it. The source installer does not edit boot settings; the fresh-image builder configures this mode. The `D` forces digital output. Use the advertised mode rather than forcing the panel resolution; the tested 800x480 input cropped the picture. A 60Hz HDMI mode does not guarantee a 60fps CarPlay stream.

The launcher switches tty1 to graphics mode while it is running, hiding the login cursor. It restores the previous console mode on a normal exit.

The default renderer uses DRM/KMS with two RGB565 buffers. It fills the offscreen buffer and flips at vertical blank rather than overwriting the buffer currently being scanned out. Presentation runs on its own thread with a latest-frame slot, so the Bluetooth loop does not wait for the display. This addresses the horizontal split seen during CarPlay swipes with direct `/dev/fb0` writes.

Look for `display_backend` with `backend: drm` and `vsync: true` in the journal. `display_pageflips` records completed flips and dropped pending frames. If DRM initialization or presentation fails, the launcher logs the failure and falls back to the older framebuffer path, which may tear. For diagnosis, add `HLAUNCHER_DISPLAY=fbdev` to `/etc/hlauncher.env` and restart HLauncher to explicitly select that older path. Remove the override to use DRM again. With DRM active, `/dev/fb0` still reports the console framebuffer geometry, but reading its pixels does not capture the application's scanout buffers.

## Start

Plug the Carlinkit dongle into a Pi USB host port. Connect the iPhone to the dongle. USB/IP and VirtualHere are not needed for the Pi 4 setup.

```bash
sudo systemctl enable --now hlauncher-firstboot hlauncher-pairing hlauncher-recovery hlauncher-audio hlauncher-connect hlauncher
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

CarPlay, Android Auto and OBD Gauges are included; the setup wizard chooses which to enable. OBD Gauges supports compatible BLE ELM327 adapters. Android Auto requires the separately built OpenAuto engine: run `sudo bash scripts/install_android_auto.sh`, then connect an Android phone directly to the Pi USB port. It is experimental pending phone testing. See [plugins](plugins.md) for installing an external plugin or writing one.

The core exposes an opt-in microphone capture API. The radio still gates live microphone samples behind its hands-free call state. CarPlay output PCM is routed through HDMI; normal media playback inside HondaLink DA is confirmed by the owner. Phone-call routing is separate. No automatic call simulation is added; the earlier microphone experiment remains documented in Git history.

## Logs and recovery

```bash
sudo systemctl status hlauncher hlauncher-audio hlauncher-connect --no-pager
sudo journalctl -u hlauncher -n 100 --no-pager
sudo journalctl -u hlauncher-connect -n 50 --no-pager
lsusb -d 1314:
sudo node /opt/hlauncher/plugins/carplay/runtime/usb/bridge.mjs --check
```

Production mode records bounded errors. Enable Debug in System settings before collecting detailed protocol logs; packet captures can contain private/device data. The fresh image keeps general logs in RAM and protocol captures in persistent state. See [logging and recovery](onboarding.md#production-and-debug) for retention and exports.

If Bluetooth restarts and HondaLink no longer opens, restart HLauncher so it registers its profiles again:

```bash
sudo systemctl restart hlauncher
```

If the display shows the Linux console, inspect the HLauncher journal and framebuffer format. If the waiting page cannot find the dongle, use `lsusb` and ensure another CarPlay process has not claimed it. Kernel USB stalls may require a Pi reboot; restarting a userspace service cannot always recover them.

To stop the installation:

```bash
sudo systemctl disable --now hlauncher hlauncher-connect hlauncher-audio hlauncher-pairing hlauncher-recovery hlauncher-firstboot
```

The BlueZ workaround is `/etc/systemd/system/bluetooth.service.d/90-hlauncher.conf`. Remove that file and restart Bluetooth only if you also want to undo the workaround. Keep your pairing records.


### Audio & EQ settings

See [audio output and PipeWire EQ](audio.md) for Settings → Audio & EQ and the
12-band controls and Flat/EDM Bass presets. Main media output is fixed to HDMI; old Bluetooth output
preferences and environment overrides are ignored. The page has no output
selector or test-tone controls. Bluetooth continues carrying HondaLink control
and the existing hands-free profiles.

### HDMI audio

CarPlay PCM goes through the plugin API to a core-owned mixer and one `aplay` worker. The mixer converts simultaneous streams
to 48 kHz stereo; `config/alsa-hdmi.conf` selects `vc4hdmi0`
(the HDMI connector nearest the Pi 4 power connector). The mixer preserves PCM in 32-bit float and uses SoXR VHQ 28-bit linear-phase
conversion for source rates other than 48 kHz. PipeWire EQ and its bridge retain
float PCM; the HDMI endpoint requests S32_LE at 48 kHz. ALSA performs HDMI IEC958
framing. See [audio fidelity](audio.md#audio-fidelity) for receiver validation. System-wide audio defaults are
unchanged. Music, prompts and received call audio use this output; microphone
capture remains separate. Audio control/volume messages are logged; automatic
media ducking is not implemented yet.

`audio_hdmi_open`, `audio_hdmi_progress` and `audio_hdmi_alsa` in the launcher journal
show device selection, PCM writes/drops and ALSA diagnostics. Successful writes
verify software delivery, not that HondaLink selected that physical input.
The main ALSA endpoint is fixed to HDMI; diagnostics report the requested format.
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
message, never invented song data. Track reports remain local. Bluetooth AVRCP
exposes only the selected source title (`Carplay` or `Android Auto`) and artist
`HLauncher`. Returning to Settings or a non-audio plugin retains a background
audio source; stopping that source clears the radio metadata. Display availability
depends on the radio screen and its AVRCP connection.

PipeWire defaults to off on each HLauncher service start. The audio process starts
the private graph only when the setting is enabled, and stops the graph and its
playback clients when disabled. The graph unit is not enabled at boot.


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

### Radio media and phone buttons

See [Radio controls](radio-buttons.md). New installs build the pinned
button-aware BlueALSA before installing hlauncher-audio.service. Existing bench
installs can retain their civic-bt-bench unit and use an ExecStart drop-in pointing
to `/opt/hlauncher-deps/bluealsa-buttons/bin/bluealsa -p a2dp-source -p hfp-ag`.
Keep bluetoothd's `--noplugin=avrcp`: HLauncher registers its own basic target.
Back up application files, the old Android Auto engine and the service drop-in
before upgrading; restore those and restart HLauncher/its audio profile unit to
roll back. Pairing and HDMI settings do not need resetting.

### Record a HondaLink drive test

Open Settings → Diagnostics → HondaLink. Capture starts automatically with the
HLauncher service and continues while using CarPlay, Android Auto or Settings.
Connection, Vehicle data, Calls/mic and Traffic tabs show received activity.
Vehicle messages remain identified by session/message until their sensor fields
are decoded. No simulated sensor values are added to this page.
The Vehicle data tab shows parking brake Engaged/Released using the in-car test
mapping, plus received radio flags and payload-change counts. Disconnecting
clears the displayed brake state. Sensors without received data are omitted.
After the Honda application authentication exchange, HLauncher requests passive
RPM (`0x17C`) and temperature (`0x324`) records once per HondaLink session, with
a cycle field of 500. No vehicle-speed subscription or CAN transmit is enabled.
Coolant and intake-air mappings follow the older Honda K/Civic layout; confirm
them against the car during a cold-start/warm-up test. Newer Hondas reuse `0x324`
with different meanings. Received sensors appear on Vehicle data; readings older
than five seconds show Stale, and a disconnect clears them. Requests, setting
responses, timeouts, invalid/encrypted data and decoded records are captured.
The capture summary includes subscription history and latest received values.
Capture records include app-protocol identity and bounded byte/bit differences
for non-touch packets; other unmapped flags are not labeled as sensors.

Use **Mark test step** before each phase: connection, tracks, Siri, incoming call,
outgoing call, call end, vehicle controls and completion. **Stop recording** saves
the current capture; **Start recording** starts another. Captures are private JSONL
files under `/var/lib/hlauncher/protocol-captures`, rotated within 64 MB. The page
shows dropped events and storage errors. Microphone audio is not saved: only
formats, levels, byte counts, projection/HFP state and routing events are recorded.
Capture headers identify the launcher process and system boot. The background
writer syncs files once per second and when stopping a capture. Microphone
open/stop/close events identify the stage reached during Siri/call teardown.

The Calls/mic tab provides **Test Siri** and a **Voice output** selector. Identified
call/Siri streams default to hands-free (Bluetooth SCO); HDMI remains available
for comparison. Ordinary media stays on HDMI. The CarPlay dongle requests the
radio microphone, converted to 16 kHz mono for USB, only during its voice/call
capture requests. Returning to Settings preserves a background call. A stopped
source, stale USB bridge or expired state lease clears voice routing/state.
The dongle's call-audio events do not provide a caller list or incoming/outgoing
ringing information; these are not fabricated.

After testing, summarize the retained captures over SSH:

```bash
cd /opt/hlauncher
sudo python3 scripts/protocol_capture.py
```

The summary includes test markers, command/message counts, call/Siri transitions,
voice routing, microphone byte counts and errors without printing packet payloads.
