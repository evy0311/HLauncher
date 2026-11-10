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

Entrypoints can be Python or Node. `default_enabled` affects bundled plugins only. `keep_alive: true` declares support for background mode. CarPlay and Android Auto retain their worker while menus are visible, but share one exclusive projection lease. Selecting either stops the other and waits for its USB process tree to exit. CarPlay can start in the background when its adapter appears, without opening its tile. Other plugins may expose a background toggle in Settings. Without this declaration the host terminates it on exit. CarPlay stays warm so returning home does not disconnect the dongle.

Add a plugin under `plugins/ID` in a pull request to bundle it. Include its dependency instructions, license, tests and a README describing what hardware it needs. Use `examples/hello` as a small starting point. An external repository can use exactly the same directory structure.

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

## Radio button events

Plugins with `input.buttons` explicitly request controls with
`client.subscribe_buttons(['next', 'previous', 'voice_assistant'])`, or the
equivalent `input.buttons.subscribe` message with a `buttons` array. An empty
array unsubscribes; a new valid list replaces the previous one. Subscriptions
belong to a worker instance and disappear when it stops. The capability alone
does not subscribe a plugin. CarPlay is the initial subscriber; Android Auto
button forwarding is not enabled by this contract yet.

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
Caller identity, call direction and ringing are not inferred from audio events.

A plugin with `audio.capture` can request `audio.capture.start` with
`sample_rate: 16000` for mono S16LE microphone PCM, delivered through `audio.format`
and `audio.pcm`. Capture follows audio-source ownership and may continue for an
enabled background plugin. `audio.capture.stop` releases capture only.

Use `client.playback(pcm, rate, channels, stream, voice=True)` for a stream identified
by the projection engine as call/Siri output. This uses a separate bounded PCM
path and voice route; ordinary playback continues to use HDMI. Send
`audio.voice.stop` when the voice stream ends. CarPlay maps its explicit audio
control stream IDs and microphone start/stop commands to this contract.
