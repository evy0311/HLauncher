# First boot, recovery and production mode

For a downloaded release image, start with [flashing and first boot](install.md).
This guide covers automatic radio enrollment, the resumable setup wizard, local
recovery, Debug mode and storage protection. Image builders must validate each
release on a Pi and radio before distributing it.

## Build a fresh image

Use an ARM64 Linux host or VM, root access, network access and a pristine, uncompressed **Raspberry Pi OS Lite Bookworm 64-bit** image. Do not use a development SD-card backup. Host tools include `parted`, `util-linux`, `udev`, `e2fsprogs`, Python 3 and the normal mount/chroot tools.

```bash
sudo bash scripts/build_image.sh /path/to/base.img /path/to/HLauncher.img US
```

Replace `US` with the installation country's two-letter regulatory code. The builder requires a new output filename, copies the base, adds 3 GiB to root and a 4096 MiB persistent-data partition, installs HLauncher and the Android Auto engine, and writes an image checksum. It requires ARM64 Linux; it does not perform an emulated build on macOS. Allow additional temporary disk space and time for the Android Auto native build and downloads.

The builder strips application state, Bluetooth bonds, Wi-Fi profiles and SSH host keys. Each Pi gets its own hotspot name and setup password. The setup page uses that password. SSH starts off and can be enabled in Wi-Fi on the radio. The builder removes build tools/caches and compacts the filesystems. On first boot, a separate background service expands the final persistent-data partition to use the remaining SD-card capacity. The OS partition stays fixed for read-only protection. Expansion is retried safely if interrupted and does not delay Bluetooth registration. Flash the resulting image as a custom image with Raspberry Pi Imager. The image forces the tested HDMI0 720×480 mode; other radios may need different display settings.

## Pair and complete setup

1. Connect HDMI0, Bluetooth range, power and the necessary USB adapter/phone. Use stable power during initial setup and storage changes.
2. The separate pairing agent starts with Bluetooth. HondaLink profiles register before the full launcher and projection plugins load. The initial pairing window lasts five minutes.
3. On the radio, open **Settings → Phone → Connect a phone → Add Bluetooth device**, then select **HLauncher**. Confirm on the radio. The Pi automatically accepts a qualifying candidate; no SSH or address editing is needed.
4. Park safely, engage the parking brake, and open HLauncher through HondaLink. Read the safety notice and agreement. Scroll to the end if needed, then select **I acknowledge and agree**. HLauncher saves the notice version locally. After an update changes the agreement, acknowledge it again before using the launcher. **Cancel** opens Wi-Fi for recovery. Complete **Welcome → Apps → Startup → Appearance → Network → Finish**. Enable the installed plugins you want, choose Home or an enabled startup app, and pick a preset or Custom theme. Network setup is optional. Choices and the current step save as you go.
5. At Finish, choose whether to enable storage protection. The application only offers it when the persistent-data layout is verified. Configuration and reboot are separate actions.

Setup and on-radio Settings require a recent HondaLink reading that confirms the parking brake is engaged. When speed is unavailable, the parking brake is enough to continue. If the radio last reported movement, it must report zero speed before you can continue on that connection. Review the notice and agreement under **Settings → About → Legal info**.

For help with the parked check, open **Settings → Diagnostics → Parking Status**. From the warning, double-tap **Park safely to continue** to open the read-only page directly. Take a photo of the readings for support, then tap **×** to return.

CarPlay needs a supported USB CarPlay adapter. Android Auto uses an Android phone connected directly by USB and the installed engine. The OBD Gauges tile shows **Coming soon**.

Enrollment recognizes HandsFreeLink/HondaLink names or the radio's audio-service combination. These are compatibility hints, not cryptographic Honda identification. Only one candidate is admitted at a time, for up to 90 seconds within the enrollment window. It becomes the saved radio only after a successful HondaLink handshake. Subsequent connections are restricted to the saved peer, and discovery closes. Failed candidate bonds are removed; unrelated existing bonds are left alone. An expired candidate cannot survive a reboot.

The themed early HDMI welcome shares the wizard’s pairing instructions and is shown while a saved radio reconnects too. Red is the default theme for new setups; saved colors are preserved. Some radios show HDMI only after pairing. With a saved radio, HLauncher can start the selected app at boot after setup is complete and the safety notice has been accepted. A per-device **HLAUNCHER-SETUP.txt** is also written to the SD card's boot partition on first boot. If necessary, shut down, read that file on another computer, then return the card to the Pi. It lists the setup address and the device’s hotspot and setup credentials.

## Phone recovery and network setup

Open the wizard’s Network step or **Settings → System → Wi-Fi**, then select **Setup hotspot → Start setup hotspot**. Connect to the displayed **HLauncher-XXXX** network and open **http://192.168.4.1:8080**. Sign in as `hlauncher` with the displayed hotspot password. On a trusted LAN, use `http://PI_ADDRESS:8080`. Enable SSH from the radio’s **Wi-Fi → SSH access** page. The initial SSH credentials are `hlauncher` / `ilovevtec1234`. Change the password with `passwd` while storage protection is off so the change survives reboot.

Wi-Fi starts off on a fresh install. Starting the hotspot enables Wi-Fi temporarily. Successfully connecting to personal Wi-Fi saves the network and turns Wi-Fi on. A valid Wi-Fi regulatory country is required for the hotspot. Use Ethernet to reach the setup page if the radio screen is unavailable. Starting the hotspot can replace an active Wi-Fi connection.

The recovery page can reopen pairing/replace the saved radio, admit a specific radio address when automatic recognition fails, configure personal Wi-Fi with a country code, toggle Debug and download a diagnostic summary. WPA/WPA2 personal passwords are supported; open and enterprise Wi-Fi are not implemented. Wi-Fi passwords are written to a root-only NetworkManager keyfile rather than command arguments. The setup hotspot can end if Wi-Fi is turned off, sleeps, or joins another network.

The recovery page and API require the device password. The service sends it over HTTP. Use it
on the setup hotspot or a trusted local network. Requests are
size/time bounded and browser writes enforce same-origin checks. It can install
signed local update files, but does not provide a general shell. With Debug enabled, it can download the latest recorded protocol capture (up to 8 MiB per download); captures may contain private/device data.

## Production and Debug

Fresh installations and completed setup default to Debug off. Settings → System → Debug enables hardware tests, HondaLink protocol tests and detailed recording. Switching it off hides those pages and stops protocol capture. The recovery page can also toggle Debug. Existing valid settings retain their app/theme/default choices and are treated as already set up; System → Setup wizard reruns the wizard without erasing those choices or clearing setup completion. An Exit button on every step returns to System; first-time setup still requires completion.

Normal operation retains bounded error logs and in-memory status. The recovery
worker publishes transient SSH and network status under `/run/hlauncher`. Core errors rotate at 256 KiB with two backups; detailed core logs rotate at 4 MiB with two backups. Plugin output is filtered in normal mode and its worker log rotates at 2 MiB with two backups. Android Auto and OBD logging follow the same Debug policy. Protocol capture has its own bounded retention. Existing old development logs are not deleted automatically.

The fresh image uses RAM-backed `/var/log` and volatile journald. Debug protocol captures and preferences live in persistent application state, so captures survive a reboot and can be inspected after a car test. A sudden loss of power can still lose the last buffered/in-flight events. Enable Debug before a test that needs packet evidence; normal mode cannot reconstruct packets it did not record. Manual Stop Recording remains stopped until Debug is toggled again.

## Storage protection and maintenance

The image mounts a separate writable ext4 `/persist` partition and binds application state, BlueZ bonds and NetworkManager connections onto it. Root overlay protection can therefore discard ordinary root writes while preserving setup choices, pairing, network credentials and recorded captures. The boot partition is protected too when enabling the mode. This reduces exposure to abrupt shutdown; the writable data partition is still subject to power-loss risks.

Settings → System → Storage protection checks the actual mounts before allowing changes. Enable protection, wait for the operation to finish, then use Restart. To undo it, choose writable mode and restart; first-boot maintenance completes the boot-partition transition after that restart. Do not interrupt configuration. Images include `overlayroot` and a rebuilt, verified Pi 4 initramfs. Enabling uses `overlayroot=tmpfs:recurse=0` so only the root filesystem is overlaid; `/persist` remains writable. The toggle verifies the actual firmware-loaded initramfs before changing boot configuration, and boot maintenance reports failed activation instead of silently leaving a pending transition.

Existing installations without this dedicated partition cannot enable protection through HLauncher. The application deliberately does not repartition a live SD card. Back up and migrate to a freshly built image instead. Signed release images support application updates and restores under storage
protection when the app's installed boot units stay the same. Turn off protection
and restart before an update or restore that changes those units.
[Application updates and release builds](updates.md) Direct development builds without that layout require writable maintenance mode for code installation. OS changes still require writable mode. System also includes an explicit, confirmed clean shutdown action.

## Existing checkout installation

`sudo bash scripts/install.sh` installs the application and new units but does not start them or repartition the card. After reviewing any older competing Bluetooth/application services, enable:

```bash
sudo systemctl enable --now hlauncher-grow hlauncher-firstboot hlauncher-pairing hlauncher-recovery hlauncher-audio hlauncher-connect hlauncher
```

A valid, already-paired `HLAUNCHER_RADIO_ADDRESS` is adopted once for migration. The persisted verified radio subsequently takes precedence. Forgetting a radio blocks automatic re-adoption of the old environment value. New installations may leave that value all zeroes. Recovery configuration on a general-purpose existing Pi uses its current NetworkManager and regulatory configuration.

## Required Pi/radio acceptance checks

Before releasing an image, build it on ARM64 Linux and verify: clean boot with no preloaded identity; radio pairing and successful HondaLink launch; pairing timeout/rejection/replacement; Bluetooth restart recovery; every wizard step and resume after reboot; enabled/default plugin behavior; HDMI, audio and microphone operation; local recovery access and Wi-Fi; and Debug capture before/after a power cycle. Confirm profiles are advertised before the full UI starts.

Then test storage protection on a disposable SD card: enable/reboot, verify overlay root and read-only boot, change preferences and verify bonds/network survive, disable/reboot, and verify root/boot are writable again. Repeat a normal shutdown and an abrupt vehicle-power loss. None of these hardware/image acceptance checks can be replaced by the local unit tests.


## Compact release images

The image builder archives the native sources before removing development
packages, package caches, unused foreign npm prebuilds, non-English message
catalogs and the unused Pi 5 kernel. Runtime shared-library owners are retained
explicitly and checked again after package cleanup. Copyright/license files,
Pi 4 kernel/firmware, networking, audio, projection and recovery remain.

`compact_image.py` works only on an unattached regular image file. It checks and
shrinks both ext4 filesystems, leaves OS maintenance headroom, seeds a small data
partition with update headroom, zeros freed ext4 blocks, then relocates that final
partition. It preserves the disk identifier, partition numbers and filesystem
UUIDs. The FAT boot partition is retained. `hlauncher-grow.service` grows only
the dedicated final HLauncher data partition and runs independently of pairing.
It records success only after resize2fs succeeds. Moving an image to a larger
card triggers expansion again; repeated boots on the same geometry do no work.

This changes the immutable system contract. Existing images require a reflash
to adopt the compact layout/runtime; subsequent compatible app updates retain
the normal signed update and rollback mechanism.

Bluetooth audio owns `org.bluealsa` exclusively; the stock `bluealsa.service` is masked. HLauncher reports systemd readiness after HondaLink profiles register. Radio reconnects react to BlueZ events, with bounded retry backoff. Display preparation runs independently after profile registration. First-boot SSH/network/storage maintenance follows readiness rather than blocking pairing.
