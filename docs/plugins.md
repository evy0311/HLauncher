# Plugins

Settings belongs to the launcher. Everything else is an installed plugin. CarPlay ships in `plugins/carplay`; Android Auto and OBD gauges have not been implemented.

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

Entrypoints can be Python or Node. `default_enabled` affects bundled plugins only. `keep_alive: true` retains a worker while another screen is visible; otherwise the host terminates it on exit. CarPlay stays warm so returning home does not disconnect the dongle.

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

`audio.status` exposes current support. `audio.capture` is opt-in, only allowed for the foreground plugin, and ends on deactivation. Capture sends `audio.format` followed by signed 16-bit little-endian PCM packets. Queues are bounded; PCM may be dropped if the plugin cannot keep up. The radio can produce digital silence outside hands-free voice mode. Call simulation and audio playback are not part of this API, and CarPlay does not consume microphone PCM yet.

A plugin cannot take down the Python Bluetooth loop through an exception in its own process. This is not isolation from kernel failures, out-of-memory conditions or malicious privileged code.
