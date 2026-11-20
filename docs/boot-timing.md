# Measuring startup

`feature/boot-time-investigation` adds small startup milestones to the main
service journal without enabling debug/traffic recording. It also avoids the
full offscreen Home rendering pass on an already-paired boot: the real UI
renders Home next. Initial pairing still prepares Home while waiting for the
radio. Bluetooth profile registration and its systemd readiness notification
remain ahead of graphics initialization.

## Boot-time goal

Target a usable HLauncher screen within 5–10 seconds of power-on on the supported
Pi 4 hardware, with under 5 seconds as the stretch goal. Measure the actual radio
display and input readiness, not just systemd startup completion or a splash.
Track phone-projection readiness separately because dongle startup and phone
reconnection can add time beyond launcher startup. These are goals, not measured
results. The first live software timing run is recorded below; physical
power-on/display timing remains unmeasured.

## Priority: Bluetooth and an early HDMI signal

Optimize for the radio being able to start HondaLink as early as possible, not
just for a fast finished Home screen. Bluetooth connectivity and a valid HDMI
signal are the first functional priorities; neither should wait for plugin
discovery, projection startup, network availability or decorative UI work.

The intended sequence is:

1. Establish HDMI output as early as the platform permits. Fresh images already
   force `video=HDMI-A-1:720x480@60D` in the kernel command line. Preserve this
   mode and verify that the radio detects a stable signal during cold boot;
   writing the setting does not prove when the physical signal becomes usable.
2. Start BlueZ and BlueALSA, enroll/restore the radio and register the HondaLink
   Bluetooth profiles. Keep required persistent mounts and updater recovery
   ahead of application startup so saved pairing and safe rollback remain valid.
3. As soon as profiles register, notify systemd readiness so the reconnect
   worker can run. Prepare the basic HDMI splash on a background thread at the
   same time; Bluetooth event handling and HondaLink authentication must remain
   responsive while graphics initialize. Do not wait for the full Home screen
   before attempting the radio connection.
4. Load the full launcher and plugins after the splash. Keep nonessential
   maintenance and network-dependent work outside this critical path.

The existing `radio.py` readiness path and `BootstrapLauncher.prepare()` already
implement profile registration before asynchronous splash/full-UI preparation.
`hlauncher-connect.service` follows that readiness notification, not completion
of graphics. This investigation preserves that ordering. Kernel HDMI output
precedes the application splash; a basic valid signal is useful even before
there is polished content to display.

When physical timing testing resumes, record power-on to HDMI detection, Bluetooth
profile readiness, radio connection, HondaLink handshake/display enable, splash
and usable Home separately. Correlate the physical observations with the journal
milestones. The radio may gate its visible display until authentication, so a
black screen alone does not prove the Pi has no HDMI signal. If the first frame
is late, investigate kernel/firmware HDMI setup and minimal splash initialization
before spending time on visual polish. Do not change bootloader settings or
bypass recovery solely to improve a systemd timing figure.

## Service-disable candidates

These began as candidates; the live service-trimming results below record which
have now been disabled on the test Pi. Confirm presence, enabled state and contribution to the critical
path or CPU/SD contention on our actual image. Compare cold boots before and after
each change; a large `systemd-analyze blame` duration alone is insufficient.

| Candidate | Proposed treatment and conditions |
| --- | --- |
| `NetworkManager-wait-online.service` | Disable the network-readiness wait if no required service needs it. HLauncher does not depend on `network-online.target`. Keep NetworkManager itself for Wi-Fi, recovery and updates. |
| `cloud-init` | Disable if installed and no longer needed after provisioning. Audit any image provisioning dependency first; retain HLauncher's own first-boot setup and storage expansion. |
| `rpi-eeprom-update.service` | Consider removing automatic boot-time firmware maintenance from the normal startup path. Retain a deliberate, supported bootloader firmware update procedure. |
| `e2scrub_reap.service` | Consider disabling on our standard non-LVM SD-card layout. This cleans stale LVM scrub snapshots; retain normal filesystem checks and persistent-storage integrity checks. |

References: [NetworkManager wait-online](https://www.networkmanager.dev/docs/api/1.38.6/NetworkManager-wait-online.service.html),
[disabling cloud-init](https://docs.cloud-init.io/en/latest/howto/disable_cloud_init.html),
[Raspberry Pi EEPROM updates](https://github.com/raspberrypi/rpi-eeprom),
[e2scrub_reap service](https://github.com/tytso/e2fsprogs/blob/v1.47.0/scrub/e2scrub_reap.service.in)
and [e2scrub manual](https://manpages.debian.org/bookworm/e2fsprogs/e2scrub.8.en.html).

Any eventual service-policy changes must also work through the existing updater
and rollback path; changing only the fresh-install image would leave existing
installations behind. No service is disabled by this documentation change.

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
The application patch changes no kernel/EEPROM/network/service-order settings.
The separate live base-system service experiment is recorded below.

The existing updater system contract is unchanged. Live Pi timing and
installation/rollback verification are still required before publishing a
release; this investigation makes no measured power-on speedup claim.

Offline validation on 2026-11-20: 28 focused boot/display/collector tests pass.
The full suite ran 368 tests: 360 passed, three skipped and five errored because
libsoxr is not installed on the Mac. The dongle-free bridge self-test passes.
A source comparison confirms the immutable updater system contract is unchanged.

## First live software timing run: 2026-11-20

Installed a boot-only patch onto the Pi's existing 0.2.12 application, preserving
its older application code outside these changes. Backed up the exact original
files on the Pi and research share. Storage protection remained enabled; no boot
units, firmware settings or candidate services were changed. The app activated
successfully before reboot and returned after reboot with zero service restarts.

| Measurement | Existing boot | Instrumented reboot |
| --- | --- | --- |
| Kernel plus userspace startup completion (`systemd-analyze time`) | 14.183 s | 13.996 s |
| Bluetooth profiles ready (kernel clock) | 7.481 s (systemd readiness) | 7.342 s |
| Splash submitted (kernel clock) | Not instrumented | 8.965 s |
| First full UI frame submitted (kernel clock) | Not instrumented | 9.410 s |

This is one existing boot and one reboot, not a repeated cold-boot comparison.
The 0.187 s total difference does not establish an improvement. Firmware/power-on
time and the radio's physical HDMI detection/display were not measured; do not
claim the power-on goal is met from these numbers. The user requested raw Pi
boot timings for this pass, without an in-car visual timing check.

`NetworkManager-wait-online` finished at 13.943 s and took 6.299 s on the reboot,
after HLauncher had already started. It is a strong candidate for reducing the
overall system startup figure, without assuming the same gain for Bluetooth or
the UI. `e2scrub_reap` took 1.499 s and `rpi-eeprom-update` 1.014 s; these overlap
other work. The launcher dependency chain includes about 1.508 s of updater
startup/recovery, which must remain safe. Reports and the exact live patch are
under `radio-research/boot-time-2026-11-20` on the research share.

## Live service-trimming experiment: 2026-11-20

At the user's request, disabled the installed boot enables for
`NetworkManager-wait-online.service`, `rpi-eeprom-update.service` and
`e2scrub_reap.service`. `cloud-init` units are absent on this Pi. NetworkManager
itself remains enabled. The SD card uses three ordinary partitions, with no LVM
volumes or mounted network filesystems. The only observed consumer of
`network-online.target` was NFS restart notification, not HLauncher.

Used the installed `overlayroot-chroot` maintenance utility to persist the unit
enable changes. Its cleanup could not remount the underlying root read-only, so
synced and rebooted immediately. Both subsequent boots confirmed the underlying
root was read-only again and `/` remained an overlay. All three disabled units
had zero execution timestamps, and systemd reported no failed units.

| Measurement from kernel startup | Before service changes | Trimmed reboot 1 | Trimmed reboot 2 |
| --- | --- | --- | --- |
| Kernel/initramfs phase | 2.229 s | 3.610 s | 2.212 s |
| Userspace startup completion | 11.766 s | 5.697 s | 5.694 s |
| Kernel plus userspace total | 13.996 s | 9.308 s | 7.907 s |
| Bluetooth profiles ready | 7.342 s | 8.592 s | 7.244 s |
| Splash frame submitted | 8.965 s | 10.161 s | 8.786 s |
| Full UI frame submitted | 9.410 s | 10.606 s | 9.243 s |

Userspace startup completion improved by about 6.07 s on both trimmed boots.
The large gain is in the overall system startup figure; Bluetooth and UI gains
are much smaller. The first trimmed boot's slower kernel/initramfs phase affected
all later markers. These are warm reboots, not power-on or physical HDMI-display
measurements. Systemd completion precedes the first full UI frame because the
app deliberately announces Bluetooth readiness before graphics are finished.

Original enabled states and unit definitions are backed up under
`/persist/hlauncher-boot-test-20261120/service-policy` and in
`live-service-analysis.tar.gz` on the research share. Restoration consists of
re-enabling those three units in writable maintenance mode and rebooting.
EEPROM firmware can still be maintained deliberately with its installed tool.
This is a base-system experiment; the application bundle does not yet apply or
roll back these service-policy changes. A validated migration for existing
installations is required before shipping that policy through HLauncher updates.

## Further trimming candidates: initial assessment

Durations below are from the second trimmed boot. They overlap and must not be
added together as projected savings. This assessment guided the combined second
batch below; consult its results for the current test-Pi configuration.

| Candidate | Evidence and next investigation |
| --- | --- |
| `udisks2.service` | 1.111 s. HLauncher's USB plugin source code uses `lsblk` and direct read-only `mount`/`umount`, rather than UDisks. Investigate removing its boot enable while retaining USB installation and any needed on-demand activation. |
| `ModemManager.service` | 0.704 s. No HLauncher source dependency found. Consider excluding cellular-modem management from the appliance profile after checking NetworkManager/USB behavior; ordinary disabling may still permit D-Bus activation. |
| `hlauncher-grow.service` | 1.155 s. Even the already-expanded path probes partition geometry with several subprocesses. Investigate deferring routine checks until after the first UI frame. Preserve first-boot growth, replacement-card detection and interrupted-growth retries. |
| `dphys-swapfile.service` | 0.467 s, but `swapon --show` reported no active swap. Verify overlayroot behavior and whether this service does useful work before disabling it. Retain an appropriate memory policy for projection workloads. |
| NFS client target/notification | No network filesystem mounts were present. NFS notification is what pulled in `network-online.target`; investigate removing the unused client boot path if remote filesystems are not a supported feature. |
| Basic splash preparation | About 1.54 s between display preparation and first splash submission on the repeat boot. A separate warm import profile attributes about 0.308 s to `hlauncher.display`, including about 0.183 s to NumPy. Profile cold imports, framebuffer setup and rendering separately, then consider a minimal/cached splash and deferred image-processing imports. Warm import numbers do not explain the entire cold-boot interval. |
| Updater startup/recovery | 1.347 s on the app dependency chain. Profile the no-pending-update path for avoidable work; preserve transaction recovery, rollback and safe persistent mounts before starting the app. |

Keep BlueZ, Bluetooth UART setup, BlueALSA, HondaLink pairing/reconnect, required
filesystem checks, overlayroot/initramfs and recovery functionality. Do not prune
security or OS-update maintenance merely because it appears in the enabled-unit
list; schedule nonessential work after startup where appropriate.

## Combined second batch: 2026-11-20

The user requested testing the remaining candidates together. Applied these as
one experiment, keeping the first batch disabled:

- Disabled and masked `ModemManager.service` and `udisks2.service`, including
  their D-Bus activation paths.
- Disabled `dphys-swapfile.service` and `nfs-client.target`. No swap or network
  filesystem was active before this change.
- Removed `hlauncher-grow.service` from immediate boot startup and enabled an
  experimental `hlauncher-grow.timer` with `OnBootSec=30s`, `AccuracySec=1s`.
  Verified the saved expansion geometry matched before changing its schedule.
  The normal expansion code still runs each boot, retaining its retry and
  card-change checks. It succeeded at 30.70 s and 30.91 s on the two test boots.
- Added a minimal paired-boot splash, avoiding themed controls, artwork and
  setup-state reads before submitting that frame. Fresh pairing retains the
  existing welcome screen. The new renderer loads neither themed UI nor NumPy;
  the framebuffer layer still loads NumPy, so that import is not yet deferred.

| Measurement from kernel startup | First batch, reboot 2 | Combined batch, reboot 1 | Combined batch, reboot 2 |
| --- | --- | --- | --- |
| Kernel/initramfs phase | 2.212 s | 3.610 s | 2.258 s |
| Userspace startup completion | 5.694 s | 4.945 s | 4.863 s |
| Kernel plus userspace total | 7.907 s | 8.556 s | 7.121 s |
| Bluetooth profiles ready | 7.244 s | 7.880 s | 6.386 s |
| Splash frame submitted | 8.786 s | 9.263 s | 7.780 s |
| Full UI frame submitted | 9.243 s | 9.829 s | 8.343 s |

Both combined runs reduced userspace startup by 0.75–0.83 s. Comparing the two
runs with similar kernel durations, total startup improved by 0.786 s,
Bluetooth readiness by 0.858 s and the full UI frame by 0.901 s. Across all
passes, raw system startup fell from about 14 s to 7.12 s in the latest run.
These are reboot/software measurements and do not include firmware/power-on or
physical radio observation. The combined experiment does not isolate each
change's contribution. Both runs had no failed systemd units, no app restarts
and a read-only lower root with overlay protection active. Bluetooth/HDMI boot
configuration and updater recovery ordering were preserved.

Fourteen local startup/splash/collector tests passed; the three collector tests
also passed after expanding the report to include every experimental unit and
its load/enabled state. Runtime USB installation, cellular networking and a full
phone-projection session were not exercised in this boot-only pass.

Backups are under `/persist/hlauncher-boot-test-20261120/batch2` on the Pi and
`live-batch2-backup.tar.gz` on the share, alongside `live-batch2-installer.py`,
`live-batch2.json` and `live-batch2-repeat.json`. To reverse this batch in writable
maintenance mode: disable/remove the new growth timer, unmask ModemManager and
UDisks, re-enable the five original boot units, restore the backed-up bootstrap
and remove the added boot-splash module, then reboot. The original first-batch
settings can be restored separately.

The minimal splash and expanded collector are on this feature branch. Base-OS
service settings and the growth timer are live test-Pi changes, documented here;
they are not automatically deployed by an application update. Production image
policy and a reversible migration for existing installations remain required
before shipping those settings. Do not apply a fresh-image-only shortcut that
leaves current installations or rollback behind.

## UI-first network startup experiment: 2026-11-20

At the user's request, defer Pi IP networking and boot maintenance until the
launcher has submitted its full first UI frame and completed initialization.
Bluetooth remains on the early path. The gate uses a fresh `/run` marker each
boot, so restarting the application later does not interrupt networking.

- `BootstrapLauncher` publishes `/run/hlauncher-ui-ready` after the factory
  finishes and `launcher_initialized` is logged. A systemd path unit then starts
  the release service, which creates `/run/hlauncher-network-ready` and starts
  `hlauncher-network.target` asynchronously.
- The live experiment installs `ConditionPathExists` gates on NetworkManager
  and its dispatcher, supplicant services/templates, networkd/service socket,
  Avahi/service socket, time synchronization, SSH/service socket, SSH-switch
  handling, recovery, first-boot maintenance, cron and maintenance services/timers.
  They cannot start via ordinary boot dependencies or D-Bus/socket activation
  before the release marker. The target starts the previously used network and
  maintenance services after release. SSH is started by first-boot maintenance
  according to the existing saved owner opt-in, not unconditionally.
- An early Wi-Fi-only rfkill hold prevents radio activity; recovery retains the
  existing Wi-Fi On/Off/Auto policy when it resumes. Bluetooth is not blocked.
- The updater's original interrupted-update preflight remains before the app.
  Its long-running, network-capable daemon waits for the network-release marker
  through a separate wrapper. Persisted bytecode avoids recompiling the stable
  updater source on each overlay boot; source hashes were verified unchanged.
  This does not claim a new or bypassed recovery algorithm.
- A separate 60-second timer releases networking if UI initialization fails or
  an older app does not publish readiness. This is an intentional recovery
  exception to the normal UI-first rule. The normal path was observed twice;
  a deliberately broken-UI boot was not tested.
- Raised startup CPU weight to 500 for BlueZ, BlueALSA, HLauncher and reconnect.
  Deferred NumPy until RGB565 encoding is actually needed and submitted the
  paired-boot KMS splash directly in BGRX. The framebuffer fallback and the
  normal UI/picture-processing path remain available.

| Measurement from kernel startup | Previous combined batch, reboot 2 | Network gate, reboot 1 | Network gate, reboot 2 |
| --- | --- | --- | --- |
| Kernel/initramfs phase | 2.258 s | 3.636 s | 2.239 s |
| Userspace startup completion | 4.863 s | 3.875 s | 4.160 s |
| Kernel plus userspace total | 7.121 s | 7.511 s | 6.400 s |
| Bluetooth profiles ready | 6.386 s | 7.451 s | 6.338 s |
| Splash frame submitted | 7.780 s | 8.022 s | 6.911 s |
| Full UI frame submitted | 8.343 s | 9.095 s | 7.986 s |
| Launcher initialization complete | 8.344 s | 9.096 s | 7.987 s |
| Network release service starts | Not gated | 9.134 s | 8.026 s |
| NetworkManager starts | Before full UI | 9.617 s | 8.497 s |
| Supplicant starts | Before full UI | 9.293 s | 8.166 s |
| Avahi starts | Before full UI | 9.256 s | 8.129 s |
| Time synchronization starts | Before full UI | 9.287 s | 8.160 s |
| SSH starts | Before full UI | 9.969 s | 8.856 s |

All recorded network/recovery/cron starts followed UI completion on both boots.
The expanded final report also confirms first-boot maintenance starts after UI
completion and that unused SSH/networkd sockets remain inactive. Both boots had
no failed units, zero app restarts, successful deferred storage checking and an
overlay root with the lower root read-only. The 21 focused startup, collector,
network-signal and display tests passed; collector checks were repeated after
expanding its unit inventory.

The systemd startup figure excludes work intentionally deferred beyond normal
target completion. On the two comparable shorter-kernel reboots, the new policy
reduced that figure by 0.721 s, the splash time by 0.869 s and full UI time by
0.357 s. Bluetooth readiness changed little. These are software reboot timings,
not power-on/firmware or physical headunit-display measurements, and combined
changes do not establish an individual contribution for each optimization.

Backups are under `/persist/hlauncher-boot-test-20261120/network-gate` and
`live-network-gate-backup.tar.gz` on the share. The exact experimental installer,
root-file manifest/policy, both timing reports and expanded final validation are
saved beside them. To restore the preceding experiment in writable maintenance
mode: disable the three newly enabled gate units, remove only the root files
listed in the backup manifest, restore backed-up app files and remove the two
new app files, reload systemd and reboot. Do not remove shared drop-in directories
or other administrators' files. Cached bytecode may remain; sources are unchanged.

Source templates, UI signaling, display optimization and daemon wrapper are on
the feature branch. The condition drop-ins, startup weights and root wrapper
installation are experimental base-system policy, not an automatically deployed
application update. Existing-updater migration and upgrade/rollback testing are
still required before release; the source installer/updater contract files were
not modified to bypass compatibility checks.

## Black startup display: 2026-11-20

The user requested a black screen until HLauncher is ready. The paired-boot
renderer now submits a completely black frame without text or font loading;
the first-time pairing welcome remains available. The existing
`splash_frame_submitted` milestone now denotes that black frame on paired boots.
Framebuffer/KMS initialization is still reused by the full UI, and the early
forced HDMI mode remains unchanged for HondaLink.

Applied `disable_splash=1` in a global firmware-config section and quiet kernel
console settings: `quiet loglevel=3 logo.nologo systemd.show_status=false
rd.systemd.show_status=false vt.global_cursor_default=0`. Removed the HDMI VT
console argument while retaining the existing serial console. Masked
`getty@tty1.service` so a login prompt cannot paint over the display. Plymouth is
not installed on this Pi. Kernel/journal logging, overlayroot, initramfs,
persistent mounts and `video=HDMI-A-1:720x480@60D` are preserved. Quiet display
defaults were proposed for the offline image builder, but withdrawn after the
failed test; the unverified candidate is saved on the research share instead.

The renderer test confirms all pixels are black without heavy UI or NumPy
imports. Configuration checks confirm HDMI/storage/serial preservation and
idempotent command-line/config transforms. Original firmware config, command
line, renderer and getty state are backed up under
`/persist/hlauncher-boot-test-20261120/black-boot` and in
`live-black-boot-backup.tar.gz` on the research share. These boot-partition and
getty changes remain part of the manual base-system experiment; they need the
same validated existing-installation migration before release.

The reboot failed validation: SSH and Bluetooth did not return. The user reports
a steady red power LED, brief green activity on a subsequent physical power
cycle, then a black display and no further observed activity. This does not
identify the boot stage or establish hardware failure. Stop boot tuning and
restore the prior boot-partition configuration before investigating further.
Exact original `config.txt` and `cmdline.txt` are also extracted under
`black-boot-recovery` on the research share for SD-reader recovery. Do not ship
the quiet-boot image defaults until the cause is understood and boot is verified.

SD-reader recovery: identified the 31 GB Pi card and matched both modified boot
files against the known silent-boot transforms. Saved their current contents,
restored original `config.txt` (1247 bytes) and `cmdline.txt` (158 bytes) in place,
verified exact bytes/SHA-256 against the pre-change backup, synced and safely
ejected the card. Recovery metadata is under `sd-reader-recovery` on the share.
No partitions or other card files were modified.

The user subsequently reported a successful boot. SSH verification confirms all
prior service reductions, delayed growth timer and UI-first network gate remain
active. The black waiting-frame renderer and getty mask also remain installed;
only the two boot-partition text files were restored. Systemd reports no failed
units, zero app restarts and a read-only lower root. Current measured timings:
2.624 s kernel/initramfs + 4.211 s userspace = 6.835 s system startup; Bluetooth
profiles ready at 6.769 s, black frame submitted at 7.256 s and full UI frame at
8.418 s (initialization complete at 8.419 s). Network services were verified to
start after UI completion. Report: `live-recovered-boot.json` on the share.

The cause of the silent-boot failure is not isolated. Keep the working boot
files and retain the verified app/service optimizations; do not reapply the
combined firmware/console settings or ship the proposed image defaults based
on speculation. The candidate is preserved as `unverified-quiet-image-candidate.py`
on the share for later investigation.
