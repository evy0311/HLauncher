# Measuring startup

`feature/boot-time-investigation` adds small startup milestones to the main
service journal without enabling debug/traffic recording. It also avoids the
full offscreen Home rendering pass on an already-paired boot: the real UI
renders Home next. Initial pairing still prepares Home while waiting for the
radio. Bluetooth profile registration and its systemd readiness notification
remain ahead of graphics initialization.

## Capture a cold boot

After installing this branch, perform a normal, safely shut-down cold boot.
Measure power-on to visible HLauncher and power-on to usable phone projection
separately with a stopwatch/video. Exclude initial image setup/storage expansion.
For comparison, use the same Pi, SD card, radio state and phone for at least
three boots before and after a change. A service restart is not a cold boot.

The journal includes bounded JSON `boot_milestone` records with `phase`, `pid`,
`boot_ms` (monotonic milliseconds after kernel start) and `process_ms` (since
this Python process loaded the timing helper). Relevant phases are:

- `python_entry`, `radio_dependencies_loaded`, `bluetooth_profiles_ready`.
- `display_preparation_started`, `splash_frame_submitted`, `launcher_imports_loaded`.
- `launcher_initialization_started`, `ui_first_frame_submitted`, `launcher_initialized`.

Each phase is logged once per application process. A restart has a new PID;
compare each process separately. `first frame submitted` means a successful KMS
or framebuffer submission, not confirmation that the radio is displaying HDMI.
The radio can gate HDMI until HondaLink connection/authentication succeeds.
Kernel-clock timings exclude firmware, initial power delivery and display wake.

A read-only collector combines those markers with systemd timing/dependency
chains, selected service timestamps, root filesystem type, and selected boot
settings:

```bash
python3 /opt/hlauncher/scripts/boot_report.py
```

Run it with journal access (normally `sudo` when invoked locally). It prints
JSON to stdout and makes no service, bootloader, filesystem or firmware changes.
Pipe/copy that output to the research share with a distinct filename for each
boot. The collector works on the old build too, but that build has no new app
milestones. Missing commands, journal permissions and timeouts are reported as
missing evidence, not zero-duration startup. It does not collect raw Bluetooth
traffic, settings credentials or the complete bootloader configuration.

`systemd-analyze blame` is a lead, not a list of sequential costs. Read
`critical-chain hlauncher.service` alongside the real frame markers: parallel
services can inflate the overall userspace total without delaying our screen.
The notify-ready timestamp measures Bluetooth profiles, not completed graphics.

## Changes requiring separate validation

The application already avoids a `network-online.target` dependency. Determine
whether Wi-Fi/cloud initialization is actually blocking or competing for SD/CPU
before removing it. BlueALSA readiness, updater recovery and persistent mounts
are deliberate dependencies; do not remove them from the production boot chain
without proving pairing/audio, interrupted-update recovery and rollback still
work. CacheDirectory/Mesa advice for a Slint/OpenGL UI does not directly apply
to HLauncher's Pillow/framebuffer rendering.

Keep the initramfs: `hlauncher.storage.verify_overlay()` explicitly requires its
overlayroot hook and kernel overlay module for SD-card protection. Bootloader
HDMI/boot-order changes and base-image service pruning are separate image or
validated-system-migration experiments, not ordinary app-update changes.
No kernel/EEPROM/network/service-order settings are changed by this branch.

The existing updater system contract is unchanged. Live Pi timing and
installation/rollback verification are still required before publishing a
release; this investigation makes no measured power-on speedup claim.

Offline validation on 2026-11-20: 28 focused boot/display/collector tests pass.
The full suite ran 368 tests: 360 passed, three skipped and five errored because
libsoxr is not installed on the Mac. The dongle-free bridge self-test passes.
A source comparison confirms the immutable updater system contract is unchanged.
