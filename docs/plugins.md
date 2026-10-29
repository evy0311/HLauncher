# Plugins

Settings belongs to the launcher. CarPlay, Android Auto and live BLE OBD Gauges ship as plugins under `plugins/`.

## Install a plugin

From the installed application:

```bash
cd /opt/hlauncher
sudo python3 -m hlauncher plugins list
sudo python3 -m hlauncher plugins install /path/to/plugin
# Or a repository, optionally selecting a subfolder:
sudo python3 -m hlauncher plugins install https://github.com/OWNER/REPO.git --subdir plugins/NAME
sudo systemctl restart hlauncher
```

External plugins are copied into `/var/lib/hlauncher/plugins/ID`. Read the author's dependency instructions, then enable the plugin in Settings. The installer copies source; it does not run install hooks or install packages. It rejects symlinks, entrypoints outside the plugin directory, duplicate IDs and attempts to replace bundled plugins. Review code before installing it. Services currently run as root, including plugin workers.

To try the included example:

```bash
sudo python3 -m hlauncher plugins install examples/hello
sudo systemctl restart hlauncher
```

Enable Hello in Settings. It draws a page; touching it returns to the launcher. To remove an external plugin, disable it, stop HLauncher, remove its own directory from `/var/lib/hlauncher/plugins`, then restart. Bundled plugins are maintained through this repository.

## Layout

A plugin is a directory with `plugin.json`, an entrypoint and any private dependencies:

```json
{
  "api_version": 1,
  "id": "hello",
  "name": "Hello",
  "entrypoint": ["python3", "worker.py"],
  "capabilities": ["display", "touch", "session"],
  "color": "#18416e"
}
```

Entrypoints can be Python or Node. `default_enabled` affects bundled plugins only. `keep_alive: true` declares support for background mode. CarPlay and Android Auto always retain their worker while another screen is visible; their background mode is automatic. Other plugins may expose a background toggle in Settings. Without this declaration the host terminates it on exit. CarPlay stays warm so returning home does not disconnect the dongle.

Add a plugin under `plugins/ID` in a pull request to bundle it. Include its dependency instructions, license, tests and a README describing what hardware it needs. Use `examples/hello` as a small starting point. An external repository can use exactly the same directory structure.

## API 1

The core is the only owner of Bluetooth profiles, HondaLink authentication and framing, radio touch decoding, microphone capture and `/dev/fb0`. Plugins receive session state and input rather than handling radio packets themselves.

`HLAUNCHER_CONTROL_FD` is an inherited Unix record socket. Packets beginning with `J` contain UTF-8 JSON; packets beginning with `A` contain raw microphone PCM. Control packets are limited to 16 KiB. The Python SDK handles framing and inherited descriptors. `HLAUNCHER_WIDTH`, `HLAUNCHER_HEIGHT` and `HLAUNCHER_LOG_DIR` describe the viewport and plugin log directory.

Host to plugin:

| Message | Purpose |
| --- | --- |
| `host.hello` | API version, viewport, RGB565LE format, display slots, max contacts and granted capabilities |
| `host.activate`, `host.deactivate` | Foreground lifecycle |
| `radio.session` | Bluetooth control connection and authentication state |
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

Use `Client.present(frame)`, `Client.receive()`, `Client.status(text, video_available=...)` and `Client.home()` from the Python SDK. Continue draining incoming messages even when not displaying, to process slot releases and lifecycle events. A plugin that exits, violates the transport or stops responding for ten seconds is stopped; its foreground screen returns to the launcher. Plugin stdout/stderr are captured separately.

The core passes both decoded touch contacts with stable `id`/`slot` values. Each contact retains `x_raw`/`y_raw` in the 0–32767 range and adds normalized `x`/`y` plus `x_px`/`y_px` for the current viewport. Release coordinates are null in these added fields; plugins should retain the last active position when needed. `host.hello` advertises `max_contacts: 2`.

CarPlay uses node-CarPlay's `SendMultiTouch` for both one- and two-finger input. Adding a second finger does not synthesize a release or restart the first contact. Both fixed slots remain in each packet, including released slots, so lifting the first finger does not renumber the second. A two-contact start is introduced as pointer zero down followed by pointer one down with pointer zero moving, even when both arrive together. Leaving the app releases active contacts.

`audio.status` exposes current support. `audio.capture` is opt-in, only allowed for the foreground plugin, and ends on deactivation. Capture sends `audio.format` followed by signed 16-bit little-endian PCM packets. Queues are bounded; PCM may be dropped if the plugin cannot keep up. The radio can produce digital silence outside hands-free voice mode. Call simulation is not part of this API, and CarPlay does not consume microphone PCM yet. Plugins with `audio.playback` can use `Client.playback(pcm, rate, channels, stream)` for signed 16-bit little-endian output. The core owns PCM mixing/resampling and HDMI playback. Submission is nonblocking and can drop PCM under backpressure. Keep-alive plugins can continue audio on the launcher; stopping the plugin releases playback. Capture still stops on deactivation.

A plugin cannot take down the Python Bluetooth loop through an exception in its own process. This is not isolation from kernel failures, out-of-memory conditions or malicious privileged code.

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
`None` clears a field. A different title clears the previous track's fields before
merging the patch. Every field retains its own update timestamp. Plugins should
use `clear=True` for a track change with the same title. `False` from the SDK means
backpressure: keep the latest patch and try it again without blocking video/audio.

HLauncher stores each plugin's report separately. The selected report is the most
recent publisher, independent of which plugin is visible, allowing background
music reports after returning to the launcher. Plugin shutdown clears its report.
Malformed media messages are rejected without stopping the plugin. File-export
failures are logged and do not interrupt playback.

Read `/run/hlauncher/now-playing.json` or call the host's `media.snapshot()` for the
latest state. This volatile snapshot is written atomically at most five times per
second. It is a local observation interface, not a radio protocol. No media data
is forwarded to the radio, Bluetooth or iMID. A future vehicle-output integration
can consume this contract without adding dongle-specific code to the host.

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
whose background setting is enabled. Microphone capture remains foreground-only.
The SDK/API version remains 1; these changes add a preference to the existing
keep-alive lifecycle. See OBD Gauges for a foreground-only, simulated plugin.

## Projection engines

CarPlay and Android Auto use the same SDK display, two-contact input, audio and
background lifecycle. Engine dependencies are fetched separately at pinned
revisions. Keep upstream trees out of plugin commits; commit the dependency pin,
build instructions, required legal notices, and narrowly scoped patches instead.
Android Auto's native service adapter is in `plugins/android-auto/native`; it
owns USB projection only, and does not own Bluetooth or HDMI.

## Hands-free button events

Add `input.buttons` to a manifest to receive `radio.button` messages through
`Client.receive()`. The launcher passively watches the paired radio's Linux input
device (when exposed) and received BlueALSA HFP debug messages. It never grabs an
input device, opens the RFCOMM AT dispatch socket, changes Bluetooth profiles, or
simulates a call. Journal messages without peer identity are accepted only while
BlueALSA exposes exactly one RFCOMM transport and it belongs to the configured
radio. Debug logging must be available for that fallback; otherwise the UI says
it is waiting for an input source.

```json
{"type":"radio.button","button":"voice_assistant","action":"activate",
 "source":"hfp-command","sequence":12,"monotonic":1234.5}
```

`button` is `answer` (also dial/redial), `hang_up`, or `voice_assistant`.
Linux keys have `down`, `repeat`, and `up` actions. HFP answer/hang-up commands
produce `trigger`; voice activation produces `activate` or `deactivate`.
**HFP commands are not physical button-down/up notifications.** A short received
pulse in diagnostics does not claim the user is still holding the button.
Dialed numbers are not included. Some radio states may consume a button locally
without sending a command; this needs testing on the actual unit.

Exactly one capable plugin receives an event: the foreground plugin, or otherwise
one running background projection plugin. CarPlay and Android Auto currently
receive and log these messages but deliberately do not answer calls or activate
a phone assistant yet. Their worker log uses `radio_button_received`; the host
logs `radio_button` and `radio_button_forwarded` with matching sequence numbers.

Settings → System diagnostics → Hardware tests provides HDMI stereo tones,
color bars plus black/white steps, and two-contact touch / hands-free input tests.
Tones last one second, stop on leaving the page or losing the radio session, and
share the existing PCM mixer. Tests do not change the HDMI range or microphone
call state. Saved system reports include recent sanitized button events.
