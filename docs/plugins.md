# Plugins

CarPlay, Android Auto, and OBD Gauges come with HLauncher. User-installed plugins appear in **Settings → Plugins**. Enable a plugin to add its tile to Home. Home fits six tiles per page, including the movable Settings tile. Swipe or tap a page indicator to change pages. Open Audio & EQ from Settings.

## Install on the radio

- **USB.** Copy the `.hlp` file to the root of a FAT32 or exFAT USB drive, or to a folder named `HLauncher` at its root. Connect it to the Pi and open **Settings → Plugins → Add plugin → Scan USB drive**. Select the package and review its source, version, and permissions. Install it, then enable it and choose any camera or TCP endpoint it asks you to configure. The drive can be removed after installation. This works offline.
- **GitHub.** In **Add plugin → Add GitHub repository**, enter `owner/repo`. The repository needs a public stable GitHub Release with one or more `.hlp` assets. Select a package and review it before installing. Use **Check GitHub for update** in the plugin’s settings to check the same repository again. For a private repo, package a local checkout and use USB or SSH.
- **SSH.** On a managed image, enable SSH from the radio first. Copy a package or source directory to the Pi. Installed and enabled plugins appear on the radio without a launcher restart. [SSH setup](onboarding.md#phone-recovery-and-network-setup)

```bash
scp hello.hlp hlauncher@PI_ADDRESS:/tmp/hello.hlp
ssh hlauncher@PI_ADDRESS
cd /opt/hlauncher
sudo python3 -m hlauncher plugins list
sudo python3 -m hlauncher plugins install /tmp/hello.hlp
sudo python3 -m hlauncher plugins enable hello
# An alternative install source is a local source directory or a public release:
# sudo python3 -m hlauncher plugins install /path/to/hello
# sudo python3 -m hlauncher plugins install https://github.com/OWNER/REPO --asset hello.hlp
# A plugin must request each permission that is being granted:
# sudo python3 -m hlauncher plugins enable my-camera --camera /dev/video0
# sudo python3 -m hlauncher plugins enable my-network-app --endpoint 192.168.1.10:8554
```

A normal HLauncher software update or application rollback preserves external packages and data under `/var/lib/hlauncher/plugin-manager`. The update confirmation warns that compatibility can change and lists known API mismatches when an online release declares its plugin API. An installed plugin whose API is unsupported is listed in Settings with the reason. Reflashing the SD card from a fresh image replaces the persistent partition, so back it up first.

Use `plugins update SOURCE` to install a higher plugin version. Use `plugins rollback ID` or **Restore previous version** in the plugin settings to switch versions while retaining data. Use `plugins disable ID` to hide the tile or `plugins remove ID` to uninstall the code and retain its data for a future reinstall. Updates requesting additional device or endpoint settings require the user to configure them before enabling the plugin. Plugin authors are responsible for keeping their data readable across their own updates and rollbacks.

On first launch, existing source installs from `/var/lib/hlauncher/plugins` are archived under `/var/lib/hlauncher/plugin-manager/legacy` so a rollback does not automatically launch them. Files and launcher preferences are preserved. Use `plugins list` to locate a legacy source and reinstall it after review. Old plugin-specific files remain in the archived folder. Reconfigure device or network access when enabling it in the new manager.

Fresh images include FFmpeg. If a camera plugin uses FFmpeg on an older image, install `ffmpeg` with SD card protection off.

## Author and package a plugin

Start with [examples/hello](../examples/hello), a Python plugin that draws a
message and returns to Home when tapped. From the root of an HLauncher checkout,
copy its two files into a new folder.

```bash
mkdir my-plugin
cp examples/hello/plugin.json examples/hello/worker.py my-plugin/
```

Edit `my-plugin/plugin.json` with your own ID and tile name.

```json
{
  "api_version": 1,
  "version": "1.0.0",
  "id": "my-plugin",
  "name": "My Plugin",
  "entrypoint": ["python3", "worker.py"],
  "capabilities": ["display", "touch"],
  "permissions": [],
  "color": "#18416e"
}
```

Keep the ID for later versions and increase the three-part version number for
each update. Edit `worker.py` to draw your first screen using the viewport
dimensions from `Client`. Keep the sample's host event loop and heartbeat as
you add input handling. Store settings and other persistent files in
`HLAUNCHER_DATA_DIR`.

Use Python with the [HLauncher SDK](../sdk/hlauncher_sdk) or Node with the
[API 1 wire protocol](#api-1). Ship any bundled dependencies as regular files
inside the package. Use dependencies that work on the target Pi. Installation
runs no build scripts or dependency installers. External workers run only while
their app is open.

From the HLauncher checkout with Python 3 and Pillow, validate the source,
preview its first frame, and build and validate the package.

```bash
python3 -m hlauncher plugins validate my-plugin
python3 -m hlauncher plugins preview my-plugin /tmp/my-plugin.png
python3 -m hlauncher plugins pack my-plugin /tmp/my-plugin.hlp
python3 -m hlauncher plugins validate /tmp/my-plugin.hlp
```

Open `/tmp/my-plugin.png` and inspect the first frame. Preview executes the
worker as your local user, so review the source first. For a plugin without a
display, skip the preview and check its behavior on the Pi.

[Install and enable the package](#install-on-the-radio) on your Pi. While
parked, open its Home tile, exercise its controls, return to Home, and reopen
it. Check any camera, network, audio, or Pi-specific dependencies you use. To
share the plugin, attach the validated `.hlp` to a stable release in your
public GitHub repository, or share the file directly for USB installation.

A `.hlp` is a ZIP containing regular files at its root, including `plugin.json`. The installer limits packages to 64 MiB and 4,096 files, rejects links and paths outside the package, and reserves the bundled IDs. The package digest identifies the exact installed revision. To supply tile art, set `"icon": "icon.png"` in the manifest and include a static PNG up to 256 × 256 and 64 KiB.

External plugins can request `display`, `touch`, `session`, `audio.playback`, `media.publish`, and `vehicle.parking`. Each worker has its own `HLAUNCHER_DATA_DIR`. The manifest’s `camera` option enables a USB capture picker and provides the chosen device through `HLAUNCHER_CAMERA_DEVICE`. Camera workers receive the viewport below the standard launcher header and Back button. The `network` option configures the endpoint used by Python SDK `Client.connect()`. Plugins can also use the system’s ordinary network and device APIs directly.

For an app that should run only when parked, add `"vehicle.parking"` to its manifest’s capabilities and set `"requires_parked": true`. HLauncher uses the same parking gate as Settings: missing initial data assumes parked; reported speed above zero or a released parking brake blocks access. These blockers survive telemetry expiry and reconnects until corrected by a new zero-speed or engaged-brake report. If the gate becomes blocked, HLauncher closes the worker and shows the parking warning when it was visible.

A plugin that only needs the readings can declare `vehicle.parking` by itself. Read the `vehicle.parking` message with the SDK’s `Client.receive()`. HLauncher sends it on activation and when the state changes. It includes `connected`, `safely_parked`, `speed_kph`, and `parking_brake`. Missing or stale speed and brake readings arrive as `null`; `safely_parked` reflects the retained parking gate and can be true with missing readings. Use `safely_parked` to gate individual actions and treat it as false until the first message arrives.

## Build a plugin with an AI agent

Open an HLauncher checkout in your coding agent and replace the bracketed text
with the behavior you want. State what should appear on screen, what a tap or
other input should do, and any hardware or data source the app needs.

> Create a third-party HLauncher plugin called **[tile name]** in `my-plugin/`.
> It should **[describe the screen, controls, and any device or data source]**.
> Read `docs/plugins.md`, `examples/hello`, and `sdk/hlauncher_sdk/__init__.py`.
> Target plugin API 1 and use only the external capabilities the app needs.
> Keep the implementation in `my-plugin/`. Show me the source and dependencies
> for review before executing the worker. Then validate the source, capture a
> preview if the app draws a screen, pack it as `/tmp/my-plugin.hlp`, and validate
> the archive using the commands in the guide. Report the files, checks you ran,
> and anything I need to test on my Pi.

Before running generated code, review its file access, network requests,
subprocesses, and dependencies. External workers run as root on the Pi.
Keep device credentials out of the prompt and package. Use the preview to
inspect layout, then follow the Pi test steps above to check input and hardware.

## API 1

The core is the only owner of Bluetooth profiles, HondaLink authentication and framing, radio touch decoding, microphone capture and `/dev/fb0`. Plugins receive session state and input rather than handling radio packets themselves.

`HLAUNCHER_CONTROL_FD` is an inherited Unix record socket. Packets beginning with `J` contain UTF-8 JSON; packets beginning with `A` contain raw microphone PCM. Control packets are limited to 16 KiB. The Python SDK handles framing and inherited descriptors. `HLAUNCHER_WIDTH`, `HLAUNCHER_HEIGHT` and `HLAUNCHER_LOG_DIR` describe the viewport and plugin log directory.

Host to plugin:

| Message | Purpose |
| --- | --- |
| `host.hello` | API version, viewport, RGB565LE format, display slots, max contacts and granted capabilities |
| `host.activate`, `host.deactivate` | Foreground lifecycle |
| `host.start` | Start a backend in the background, without presenting video |
| `radio.session` | Bluetooth control connection and authentication state |
| `vehicle.parking` | Read-only parked status, speed and parking brake for plugins that declare the capability |
| `touch` | Both stable contact IDs, raw/normalized/viewport coordinates and elapsed time |
| `touch.cancel` | Release active contacts when leaving the app |
| `frame.release` | A display slot can be written again |
| `audio.status`, `audio.format`, `audio.capture.started/stopped`, `audio.error` | Audio responses |

Plugin to host:

| Message | Purpose |
| --- | --- |
| `plugin.ready` | Declare `api_version: 1` |
| `plugin.status` | Waiting/error text; `video_available` controls stale-frame replacement |
| `frame.ready` | Slot number, increasing sequence and exact byte count |
| `launcher.home` | Return to launcher without applying the default-app preference again |
| `health` | Keepalive; send at least every two seconds while idle |
| `audio.status`, `audio.capture.start/stop` | Request core-owned radio audio access |

Display data does not travel through JSON. `HLAUNCHER_FRAME_FD` maps three full RGB565LE frames. The plugin writes a free slot, then sends `frame.ready`. It must not modify that slot until `frame.release`. The host copies the newest pending frame, releases the slot and presents it. The SDK drops an incoming frame if all slots are busy; there is no unbounded video queue. Only the foreground plugin can display or receive touch. The core presents complete frames through DRM/KMS offscreen buffers and synchronized page flips; plugins must not write the scanout buffer directly.

Use `Client.present(frame)`, `Client.receive()`, `Client.status(text, video_available=...)` and `Client.home()` from the Python SDK. Continue draining incoming messages even when not displaying, to process slot releases and lifecycle events. A plugin that exits, violates the transport or stops responding for ten seconds is stopped; its foreground screen returns to the launcher. The host merges plugin stdout and stderr into a rotating worker log.

The core passes both decoded touch contacts with stable `id`/`slot` values. Each contact retains `x_raw`/`y_raw` in the 0–32767 range and adds normalized `x`/`y` plus `x_px`/`y_px` for the current viewport. Release coordinates are null in these added fields; plugins should retain the last active position when needed. `host.hello` advertises `max_contacts: 2`.

CarPlay uses node-CarPlay's `SendMultiTouch` for both one- and two-finger input. Adding a second finger does not synthesize a release or restart the first contact. Both fixed slots remain in each packet, including released slots, so lifting the first finger does not renumber the second. A two-contact start is introduced as pointer zero down followed by pointer one down with pointer zero moving, even when both arrive together. Leaving the app releases active contacts.

Plugins with `audio.playback` can call `Client.playback(pcm, rate, channels, stream)`
to submit signed 16-bit little-endian PCM over the dedicated
`HLAUNCHER_PLAYBACK_FD` socket. Raw clients send a `P` byte, a big-endian
32-bit sample rate, one byte each for channel count and stream ID, and then
PCM. The core handles mixing, resampling and HDMI playback. Submission is
nonblocking and can drop PCM under backpressure. See
[Projection voice and microphone](#projection-voice-and-microphone) for the
bundled plugins' radio capture and voice output.

External plugins run as root on the Pi, with full access to the system and its data. The project plans to isolate external plugins in a later version. Install and run only code you trust. Manifest options configure launcher features and do not enforce system access restrictions.

## Now-playing reports

A plugin can declare `media.publish` and publish song metadata to the launcher:

```python
client.now_playing(title='Track', artist='Artist', album='Album', app='Player',
                   position_ms=12500, duration_ms=180000)
client.now_playing(position_ms=13500)  # partial update
client.now_playing(clear=True)        # phone disconnected / source ended
```

Fields are `title`, `artist`, `album`, `app`, `position_ms`, `duration_ms` and
`playback_state` (`unknown`, `playing`, `paused`, `stopped`). Times are milliseconds;
`None` clears a field. A different title clears the previous track's fields
except for app and playback state, then applies the patch. Every field retains its own update timestamp. Plugins should
use `clear=True` for a track change with the same title. `False` from the SDK means
backpressure: keep the latest patch and try it again without blocking video/audio.

HLauncher stores each plugin's report separately. The selected report is the most
recent publisher, independent of which plugin is visible, allowing background
music reports after returning to the launcher. Plugin shutdown clears its report.
Malformed media messages are rejected without stopping the plugin. File-export
failures are logged and do not interrupt playback.

Read `/run/hlauncher/now-playing.json` or call the host's `media.snapshot()` for the
latest state. This volatile snapshot is written atomically at most five times per
second. The Bluetooth AVRCP target serves track details from the selected
projection audio source when available. It falls back to the source name and
`HLauncher` as artist when there is no valid current title. Whether the radio
uses those fields on the i-MID Apps page remains unverified.
[i-MID Apps audio investigation](imid-audio.md)

CarPlay forwards `MediaData` subtype 1 (title/artist/album/player/duration/position).
Album artwork is not forwarded through this text interface. Unknown play-state
codes are not guessed. The viewer displays the last reported position and its
age; it does not advance a made-up timer while paused or disconnected. The
millisecond interpretation follows the adapter protocol reference and must be
verified against the actual dongle's playback reports.


Metadata troubleshooting: startup sends `DashboardInfo: 1` in BoxSettings to
request media/dashboard reporting, following the separate CPC200-CCPA firmware
reference. Support on a particular dongle must be checked live; the presence of a
parser does not guarantee firmware emits the packets. Bridge `stream_stats`
includes `usb_message_types` and `media_subtypes`, counted before parsing. This
distinguishes a silent adapter from a parser or forwarding failure. Reconnect the
phone after changing identification capabilities. No adapter firmware is flashed.


Tested older adapter: USB `1314:1520`, reported firmware
`2020.10.27.1239CAY`. With music playing and `DashboardInfo: 1`, the raw pre-parser
counters saw 561 audio packets and zero `MediaData (0x2A)` packets. Metadata support
on this firmware has not been established; a working video/audio session does not
prove it can emit media reports. No adapter firmware update has been performed.
The newer CPC200-CCPA documentation must not be assumed to apply to this model.


Foreground/background lifecycle: `host.activate` enables rendering and input.
`host.deactivate` includes `background: true` for a retained worker. It must stop
producing display frames and release touch contacts while continuing only its
background work. HLauncher accepts PCM output from the active plugin or a worker
whose background lifecycle is enabled. CarPlay and Android Auto retain their
sessions in the background. External workers and OBD Gauges run in the
foreground only. OBD Gauges shows live data when the vehicle supplies it.

## Projection engines

CarPlay and Android Auto use the same SDK display, two-contact input, audio and
background lifecycle. Engine dependencies are fetched separately at pinned
revisions. Keep upstream trees out of plugin commits; commit the dependency pin,
build instructions, required legal notices, and narrowly scoped patches instead.
Android Auto's native service adapter is in `plugins/android-auto/native`; it
owns USB projection only, and does not own Bluetooth or HDMI.

## Radio button events

Plugins with `input.buttons` explicitly request controls with
`client.subscribe_buttons(['next', 'previous', 'voice_assistant'])`, or the
equivalent `input.buttons.subscribe` message with a `buttons` array. An empty
array unsubscribes; a new valid list replaces the previous one. Subscriptions
belong to a worker instance and disappear when it stops. The capability alone
does not subscribe a plugin. The bundled CarPlay and Android Auto workers both subscribe.

Subscribed plugins receive `radio.button` with `button`, `action`,
`source`, `sequence` and monotonic time. Buttons include `next`, `previous`,
`play_pause`, `play`, `pause`, `stop`, `answer`, `hang_up` and `voice_assistant`.
Actions are down/up/repeat or trigger/activate/deactivate. All edges are delivered;
plugins must not retrigger commands on release or repeat. Exactly one ready
subscriber is selected: foreground first, then a running background subscriber.
A held press and its release retain the same destination across foreground changes.
Bluetooth events include `input_epoch`; transport changes advance it so a lost
release during disconnection cannot leave a control held after reconnection.
Call commands are never broadcast to two
phones. Plugins return `radio.button.result` with button, sequence and a result;
the host accepts it only from the selected destination with matching button and
sequence. Set `final: false` for an intermediate queue acknowledgement, then send
a final result after USB submission. Outstanding results time out after three
seconds; a late result cannot replace a newer command's status. Release feedback
is logged without overwriting the press's displayed result. Queue-full errors
never fall through to another phone. Commands are not replayed on reconnection.

CarPlay subscribes to all nine supported names above. Its `stop` is a pause;
voice activate/down/trigger sends one `siri` command. Voice deactivate only clears
held state: the pinned dongle API has no outgoing Siri release command. Dial and
redial can be observed by diagnostics but CarPlay does not subscribe to them.
USB success means the adapter accepted the transfer, not that the phone acted.

See [Radio controls](radio-buttons.md) for transport details, installation and
hardware checks. Hardware tests provides audio, color and live button pages.

### Projection voice and microphone

`projection.voice` permits `projection.voice` messages with a `fields` object
containing the boolean fields `call_audio`, `siri` and `recording`. These represent
actual projection transport events; refresh at least every two seconds while
running. Only the selected audio source reaches the HFP controller. A five-second
producer lease and six-second exported-state lease prevent stale call state.
During call audio, `fields` can include a `call` object with optional `name`,
`number` and boolean `incoming` values reported by the projection engine.
Caller details follow the same lease and are omitted from protocol logs.
The radio can query the active call through Bluetooth HFP.

A plugin with `audio.capture` can request `audio.capture.start` with
`sample_rate: 16000` for mono S16LE microphone PCM, delivered through `audio.format`
and `audio.pcm`. Capture follows audio-source ownership and may continue for an
enabled background plugin. `audio.capture.stop` releases capture only.

Use `client.playback(pcm, rate, channels, stream, voice=True)` for a stream identified
by the projection engine as call/Siri output. This uses a separate bounded PCM
path and voice route. On the wire, voice uses the same PCM header with a `C`
prefix. Ordinary playback continues to use HDMI. Send `audio.voice.stop`
when the voice stream ends. CarPlay maps its audio control stream IDs and
microphone commands to this contract. Android Auto requests capture when the
phone starts its microphone channel. The radio can return silence outside
hands-free voice mode.

## HondaLink extensions

The [HondaLink capability reference](hondalink-capabilities.md) records recovered
radio operations and proposed host-owned plugin contracts. Navigation, call,
clock and voice-notice operations in that document are not yet SDK APIs. Plugins
must not send the old app's WebView bridge JSON directly over Bluetooth.
