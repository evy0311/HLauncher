# Development

The launcher and its plugins live in one repository. Keep changes to the traced HondaLink protocol separate from display or plugin changes so regressions can be narrowed down without reflashing the radio.

`python3 -m hlauncher run --seconds 0` runs the core. `hlauncher.service` is the installed service name. Settings are saved atomically outside the code tree; bundled plugins are discovered at startup and the launcher refreshes the installed external plugin index. See [plugins](plugins.md) for the process interface and installing external source.

Run `bash scripts/test.sh` for protocol fragmentation, launch routing, settings persistence, manifest validation, real worker frame leases, failure recovery and the Node touch/Home-event self-test. On Bookworm, `python3 scripts/check.py --display` also checks native USB loading, decodes the H.264 fixture and inspects framebuffer geometry read-only. These checks do not register Bluetooth profiles, open the dongle or draw on the radio.

The plugin host uses a bounded control socket and three leased shared frame buffers. It polls workers from the same short GLib timer used by the original launcher. The host signals workers from the loop and reaps them in the background. CarPlay owns its USB bridge and decoder; the core owns display presentation and radio input. Preserve that boundary when adding apps.

The initial Git import contains the V42-based HLauncher port.
[baseline.json](baseline.json) records the original source hashes. The imported
files differ from those hashes, so use the original sources to verify that manifest. Live migration should retain that installation until the new service is tested. Never run both listeners or two CarPlay bridges at the same time.

## Touch and video timing

The owner confirmed Maps pinch-to-zoom and disappearance of horizontal tearing
after the two-contact bridge and DRM renderer were deployed.

The launcher polls plugin availability every 4 ms. The active CarPlay worker
loops with a 1 ms sleep. HDMI presentation is paced by vertical blank. CarPlay
requests 30 FPS by default and can request 60 FPS through the plugin settings.

For a stutter report, compare these counters during a continuous swipe test:

- `stream_stats` in the plugin worker log: video packets received from the dongle, time window and maximum packet gap. A static screen may intentionally arrive slowly.
- `plugin_frame_stats` in the core log: decode packet/frame totals, average/max decode time, publication attempts blocked by occupied slots, frames received/copied and pending frames superseded. Backpressure counts are retries, not necessarily lost frames.
- `display_pageflips`: completed synchronized flips and pending frames replaced before presentation.

Compare differences between samples over the same active interval, not cumulative totals from different sessions. Large input gaps can precede the Pi decoder; long decode times identify Pi processing; publication or presentation counters identify later losses. A single idle CPU snapshot cannot establish performance during an animation.

The ordered-start experiment did not fix simultaneous-finger behavior. Review found that the legacy-to-multitouch transition emitted a synthetic first-finger release, which could turn a short first contact into a tap. The current bridge uses one continuous `SendMultiTouch` stream for both single-finger and two-finger input; adding the second pointer emits first-pointer Move plus second-pointer Down, without an intervening Up.

The owner confirmed that normal taps, swipes and pinches with both fingers placed together all worked after the continuous-contact change. The lower polling delays also made page swipes feel somewhat smoother. Earlier car-test samples showed roughly 40–56 incoming video packets per second, 50–76ms maximum packet gaps in some windows, and around 10ms mean decode time. All decoded frames reached the core without plugin backpressure or superseded host frames in those samples. These measurements do not establish a hard dongle limit or promise a constant 60fps.
