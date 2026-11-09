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
Do not infer working microphone audio from a USB send count alone. Dongle events
do not supply a complete caller list or ringing state.

For testing, enable Debug and use the HondaLink Calls/mic diagnostics described
in [recording a drive test](../../docs/setup.md#record-a-hondalink-drive-test).
[Radio controls](../../docs/radio-buttons.md) documents button forwarding.

## Picture controls


Open **Settings → Plugins → CarPlay → CarPlay picture** for saturation, contrast and brightness sliders.
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


HDMI range is separate from these video controls. Use **HDMI test** on the
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
message, never invented song data. Track reports remain local. Bluetooth AVRCP
exposes only the selected source title (`Carplay` or `Android Auto`) and artist
`HLauncher`. Returning to Settings or a non-audio plugin retains a background
audio source; stopping that source clears the radio metadata. Display availability
depends on the radio screen and its AVRCP connection.

## Troubleshooting

```bash
lsusb -d 1314:
sudo node /opt/hlauncher/plugins/carplay/runtime/usb/bridge.mjs --check
sudo journalctl -u hlauncher -n 100 --no-pager
```

Plugin logs are under `/var/log/hlauncher/plugins/carplay/`. Enable Debug before
collecting detailed evidence. The bridge check validates the installed runtime;
it does not prove that an adapter or phone connected. Ensure another process is
not holding the USB device. Kernel USB stalls may require a Pi reboot.
