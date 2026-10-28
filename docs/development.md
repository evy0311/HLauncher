# Development

This first import preserves the Pi 4 V42 runtime. Keep protocol changes separate from UI or packaging changes so regressions can be narrowed down without reflashing the radio.

Run `bash scripts/test.sh` for protocol fragmentation, app-launch routing, UI navigation, microphone-worker failure handling, and the Node touch/Home-event self-test. On Bookworm, `python3 scripts/check.py` also checks native USB loading and decodes the included H.264 fixture. Tests do not register Bluetooth profiles, open a dongle or draw on the radio.

The next refactor should separate the HondaLink connection, launcher/display ownership and app workers. CarPlay is the first worker to extract. Keep the Bluetooth event loop independent of app rendering, and use a bounded latest-frame buffer rather than serializing video through JSON. The existing microphone subprocess is useful precedent for isolating failures.

Plugin discovery, a default-app preference, Android Auto integration and OBD gauges are not implemented yet.
