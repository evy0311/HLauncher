# Development

The launcher and its plugins live in one repository. Keep changes to the traced HondaLink protocol separate from display or plugin changes so regressions can be narrowed down without reflashing the radio.

`python3 -m hlauncher run --seconds 0` runs the core. `hlauncher.service` is the installed service name. Settings are saved atomically outside the code tree; plugin manifests are discovered at startup. See [plugins](plugins.md) for the process interface and installing external source.

Run `bash scripts/test.sh` for protocol fragmentation, launch routing, settings persistence, manifest validation, real worker frame leases, failure recovery and the Node touch/Home-event self-test. On Bookworm, `python3 scripts/check.py --display` also checks native USB loading, decodes the H.264 fixture and inspects framebuffer geometry read-only. These checks do not register Bluetooth profiles, open the dongle or draw on the radio.

The plugin host uses a bounded control socket and three leased shared frame buffers. It polls workers from the same short GLib timer used by the original launcher. Worker termination and subprocess cleanup happen outside that loop. CarPlay owns its USB bridge and decoder; the core owns display presentation and radio input. Preserve that boundary when adding apps.

The original V42 source is preserved in the first Git import. `docs/baseline.json` records its source hashes. Live migration should retain that installation until the new service is tested. Never run both listeners or two CarPlay bridges at the same time.

## Touch and video timing

The owner confirmed Maps pinch-to-zoom and disappearance of horizontal tearing after the two-contact bridge and DRM renderer were deployed. The initial multi-touch implementation still required placing one finger before the other; the next change introduces contacts in order to the dongle.

The launcher now samples plugin availability every 4ms rather than 16ms, while the active CarPlay worker publishes at up to 1ms polling intervals rather than 5ms. Actual HDMI presentation remains paced by vertical blank. These changes reduce software waiting; they do not change the requested 60fps dongle stream or guarantee its arrival rate.

For a stutter report, compare these counters during a continuous swipe test:

- `stream_stats` in the plugin worker log: video packets received from the dongle, time window and maximum packet gap. A static screen may intentionally arrive slowly.
- `plugin_frame_stats` in the core log: decode packet/frame totals, average/max decode time, publication attempts blocked by occupied slots, frames received/copied and pending frames superseded. Backpressure counts are retries, not necessarily lost frames.
- `display_pageflips`: completed synchronized flips and pending frames replaced before presentation.

Compare differences between samples over the same active interval, not cumulative totals from different sessions. Large input gaps can precede the Pi decoder; long decode times identify Pi processing; publication or presentation counters identify later losses. A single idle CPU snapshot cannot establish performance during an animation.
