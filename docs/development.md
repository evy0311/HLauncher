# Development

The launcher and its plugins live in one repository. Keep changes to the traced HondaLink protocol separate from display or plugin changes so regressions can be narrowed down without reflashing the radio.

`python3 -m hlauncher run --seconds 0` runs the core. `hlauncher.service` is the installed service name. Settings are saved atomically outside the code tree; plugin manifests are discovered at startup. See [plugins](plugins.md) for the process interface and installing external source.

Run `bash scripts/test.sh` for protocol fragmentation, launch routing, settings persistence, manifest validation, real worker frame leases, failure recovery and the Node touch/Home-event self-test. On Bookworm, `python3 scripts/check.py --display` also checks native USB loading, decodes the H.264 fixture and inspects framebuffer geometry read-only. These checks do not register Bluetooth profiles, open the dongle or draw on the radio.

The plugin host uses a bounded control socket and three leased shared frame buffers. It polls workers from the same short GLib timer used by the original launcher. Worker termination and subprocess cleanup happen outside that loop. CarPlay owns its USB bridge and decoder; the core owns display presentation and radio input. Preserve that boundary when adding apps.

The original V42 source is preserved in the first Git import. `docs/baseline.json` records its source hashes. Live migration should retain that installation until the new service is tested. Never run both listeners or two CarPlay bridges at the same time.
