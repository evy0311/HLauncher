# CarPlay

Projects an iPhone through a compatible Carlinkit USB adapter using
[node-CarPlay](https://github.com/rhysmorgan134/node-CarPlay). Video, taps, swipes,
two-finger Maps gestures and HDMI media audio have been confirmed on the project
setup. Compatibility with other adapters/phones is unverified.

## Connect

1. Plug the Carlinkit adapter directly into a **Pi USB host port**. The Pi connects
   to the radio through HDMI0 and Bluetooth; USB/IP and VirtualHere are unnecessary.
2. Enable CarPlay in the setup wizard or **Settings → Plugins → CarPlay**.
3. Connect the iPhone through the adapter's phone-pairing process and open CarPlay.

Release images include the runtime. For a source installation,
`sudo bash scripts/install.sh` fetches pinned node-CarPlay sources, applies the
tracked patch and installs the Node dependencies. No separate CarPlay engine
build is needed. See [source setup](../../docs/setup.md).

The stream requests 60fps; actual delivery depends on the phone, adapter and Pi.
HLauncher scales video and touch to the working 720×480 HDMI mode. A 60Hz display
mode alone does not establish the phone's frame rate.

## Return and background playback

Use the Honda/HLauncher return item inside CarPlay to return to the launcher.
The waiting/error page also has a Home button. Background mode is always enabled:
audio and the USB session continue while you use Settings or OBD Gauges, and
opening the tile returns to the same session. Disabling the plugin stops it.
Hidden video keeps decoding for continuity but skips RGB conversion/presentation.

After setup, enabled CarPlay can start in the background when the adapter is
attached. CarPlay and Android Auto share an exclusive projection lease: switching
waits for the previous session to release USB. Automatic CarPlay startup does not
take over a running Android Auto session.

**Settings → Plugins → CarPlay → Adapter icon** manages the adapter's HLauncher
return icon/label. A USB transfer status is not proof that adapter firmware saved
or displayed the change; a phone reconnection may be needed.

## Audio and microphone

Ordinary media uses HDMI and the launcher's audio mixer. See
[audio and EQ](../../docs/audio.md) for routing and quality controls.

The current bridge requests radio microphone capture during dongle voice/call
requests and forwards 16 kHz mono PCM to the adapter. Identified Siri/call output
defaults to Bluetooth SCO; diagnostics allow HDMI comparison. The radio gates
microphone input behind a hands-free call state. This code path exists, but
end-to-end Siri, incoming/outgoing calls and teardown still need in-car validation.
When the radio queries the active call over Bluetooth HFP, HLauncher supplies
the name and number reported in the adapter's CallStatus packet. If neither
field is available, it sends **CarPlay Call** in the optional name field.

For testing, enable Debug and use the HondaLink Calls/mic diagnostics described
in [recording a drive test](../../docs/setup.md#record-a-hondalink-drive-test).
[Radio controls](../../docs/radio-buttons.md) documents button forwarding.

## Vehicle data

**Use car built-in GPS** on the CarPlay plugin page enables GPS reporting on
the adapter and forwards live HondaLink coordinates as NMEA. The adapter must
support the host GPS capability. When a fresh HondaLink speed sample accompanies
the position, HLauncher includes it in the NMEA speed field. The iPhone decides
how to use those readings.
Changing the switch reconnects an active projection.

**Parking brake.** HLauncher reads the parking brake through HondaLink. Forwarding
to CarPlay is unverified on our test adapter (USB `1314:1520`, firmware
`2020.10.27.1239CAY`). The newer CPC200-CCPA firmware `2025.10.15.1127` has a
documented GPS and speed path, but the published USB captures and firmware analysis
give no message format for a host to send the parking brake. The plan is to add
forwarding for compatible adapter firmware once a bench capture confirms how to
send engaged and released states and how to handle a lost HondaLink feed.
[CPC200-CCPA USB protocol research](https://github.com/lvalen91/CPC200-CCPA_resources/blob/main/documentation/02_Protocol_Reference/usb_protocol.md)

## Frame rate and picture controls

Open **Settings → Plugins → CarPlay → Frame rate** to switch between 30 and 60 FPS.
The setting is saved and an active CarPlay connection briefly reconnects to request
the new frame rate from the dongle. The default is 30 FPS.


Open **Settings → Appearance → Picture** for saturation, contrast and brightness sliders.
Changes apply live to built-in HLauncher screens, CarPlay and Android Auto,
and save automatically. **Reset** restores saturation 110%, contrast 100%, and brightness −10.
**Preview** returns to CarPlay with the new values. HDMI range remains a separate setting.
The former software 16–235 picture inset is no longer applied.

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

These controls share `/var/lib/hlauncher/picture.json`. Existing `carplay-color.json`
values are read until the first save. Writes are atomic and values are validated.
The projection workers check for changes every 100 ms and redraw retained video,
even when the phone is not sending new frames. No plugin restart is needed.
Video tuning stays inside FFmpeg's existing native YUV-to-RGB conversion, with no
additional frame filter, pixel loop or framebuffer copy. Built-in UI previews use
Pillow's native operations only when drawing a screen. Raw frames from other
plugins pass through unchanged. The decoder honors declared H.264 color matrix
and input range metadata. Logs include `display_picture_saved` and
`display_picture_applied`. Neutral controls preserve the original output.

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


HDMI range is separate from these display controls. Use **HDMI test** on the
picture page to preview and save a range; see
[HDMI range calibration](../../docs/setup.md#hdmi-range-calibration).

## Song metadata over SSH


With CarPlay open and music playing:

```bash
cd /opt/hlauncher
python3 scripts/now_playing.py
```

Press Ctrl+C to stop the viewer; playback continues. For one snapshot or streaming
JSON, use `python3 -m hlauncher now-playing` or
`python3 -m hlauncher now-playing --watch --json`. Missing reports show a waiting
message until the phone reports a track. Bluetooth AVRCP sends the active
projection's title, artist and album when available. With no track it shows the
source name. Returning to Settings or a non-audio plugin retains a background
audio source; stopping that source clears its radio metadata. What appears on the
radio depends on the selected radio screen and its AVRCP connection.

## Troubleshooting

Open **Settings → Plugins → CarPlay → Dongle info** for live adapter reports:
USB ID, firmware version, product/hardware identifiers, advertised Android Auto
support, active phone protocol, and reported USB/wireless transport. Scroll for
additional fields. Unreported fields stay **Unknown**; the product name or USB
ID does not prove AA support. **Reported** means the firmware advertises AA,
not that a connection has been tested. Reports clear after adapter loss and are
not saved as facts about a replacement adapter. Enable the plugin and connect
the adapter to collect reports. This page does not interrupt another projection
session or enable a disabled plugin.

```bash
lsusb -d 1314:
sudo node /opt/hlauncher/plugins/carplay/runtime/usb/bridge.mjs --check
sudo journalctl -u hlauncher -n 100 --no-pager
```

Plugin logs are under `/var/log/hlauncher/plugins/carplay/`. Enable Debug before
collecting detailed evidence. The bridge check validates the installed runtime;
it does not prove that an adapter or phone connected. Ensure another process is
not holding the USB device. Kernel USB stalls may require a Pi reboot.
