# First boot, recovery and production mode

The application now includes automatic radio enrollment, a resumable on-screen setup wizard, production/debug modes, a phone recovery page and guarded filesystem protection. The image scripts assemble these into a fresh installation. The scripts have not yet been used to build and boot a release image; Pi/radio validation is required before distributing one.

## Build a fresh image

Use an ARM64 Linux host or VM, root access, network access and a pristine, uncompressed **Raspberry Pi OS Lite Bookworm 64-bit** image. Do not use a development SD-card backup. Host tools include `parted`, `util-linux`, `udev`, `e2fsprogs`, Python 3 and the normal mount/chroot tools.

```bash
sudo bash scripts/build_image.sh /path/to/base.img /path/to/HLauncher.img US
```

Replace `US` with the installation country's two-letter regulatory code. The builder requires a new output filename, copies the base, adds 3 GiB to root and a 512 MiB persistent-data partition, installs HLauncher and the Android Auto engine, and writes an image checksum. It requires ARM64 Linux; it does not perform an emulated build on macOS. Allow additional temporary disk space and time for the Android Auto native build and downloads.

The builder strips application state, Bluetooth bonds, Wi-Fi profiles and SSH host keys. Each Pi generates its own recovery credentials. SSH is disabled, and no shared login account or password is supplied. Root does not automatically expand into the remaining space of a larger SD card because the persistent-data partition follows it. Flash the resulting image as a custom image with Raspberry Pi Imager. The image forces the tested HDMI0 720×480 mode; other radios may need different display settings.

## Pair and complete setup

1. Connect HDMI0, Bluetooth range, power and the necessary USB adapter/phone. Use stable power during initial setup and storage changes.
2. The separate pairing agent starts with Bluetooth. HondaLink profiles register before the full launcher and projection plugins load. The initial pairing window lasts five minutes.
3. In the radio's HandsFreeLink settings, add a phone/device and select **HLauncher**. Confirm on the radio. The Pi automatically accepts a qualifying candidate; no SSH or address editing is needed.
4. Open HLauncher through HondaLink on the radio. Complete **Welcome → Apps → Startup → Appearance → Network → Finish**. Enable the installed plugins you want, choose Home or an enabled startup app, and pick a theme. Network setup is optional. Choices and the current step save as you go.
5. At Finish, choose whether to enable storage protection. The application only offers it when the persistent-data layout is verified. Configuration and reboot are separate actions.

CarPlay needs a supported USB CarPlay adapter; Android Auto uses an Android phone connected directly by USB and the installed engine. OBD Gauges needs a compatible BLE ELM327 adapter. Selecting a plugin does not pair its phone or adapter automatically.

Enrollment recognizes HandsFreeLink/HondaLink names or the radio's audio-service combination. These are compatibility hints, not cryptographic Honda identification. Only one candidate is admitted at a time, for up to 90 seconds within the enrollment window. It becomes the saved radio only after a successful HondaLink handshake. Subsequent connections are restricted to the saved peer, and discovery closes. Failed candidate bonds are removed; unrelated existing bonds are left alone. An expired candidate cannot survive a reboot.

The early HDMI pairing card is best-effort: some radios will not show HDMI before pairing. A per-device **HLAUNCHER-SETUP.txt** is also written to the SD card's boot partition on first boot. If necessary, shut down, read that file on another computer, then return the card to the Pi. Do not publish it; it contains the recovery password.

## Phone recovery and network setup

Settings → System → Radio & Wi-Fi displays the recovery credentials. Connect to the displayed **HLauncher-XXXX** network and open **http://192.168.4.1:8080**. Log in as `hlauncher` with the displayed setup password. On a normal LAN, use `http://PI_ADDRESS:8080` with the same credentials.

The hotspot starts automatically for an unpaired Pi only when Wi-Fi is not already connected. Settings can explicitly request it later. A valid Wi-Fi regulatory country is required. If that is unavailable, use the normal LAN/Ethernet recovery address or correct the country configuration. Starting the hotspot uses the Pi's Wi-Fi interface, so it can replace an active Wi-Fi connection when explicitly requested.

The recovery page can reopen pairing/replace the saved radio, admit a specific radio address when automatic recognition fails, configure personal Wi-Fi with a country code, toggle Debug and download a diagnostic summary. WPA/WPA2 personal passwords are supported; open and enterprise Wi-Fi are not implemented. Wi-Fi passwords are written to a root-only NetworkManager keyfile rather than command arguments. The hotspot stops after radio enrollment and wizard completion, or after successfully joining Wi-Fi.

Every recovery endpoint requires authentication. The service is intended for a local network; it uses HTTP, not TLS, and should not be exposed to the internet. Requests are size/time bounded and browser writes enforce same-origin checks. It is not a general shell or remote updater. With Debug enabled, it can download the latest recorded protocol capture (up to 8 MiB per download); captures may contain private/device data.

## Production and Debug

Fresh installations and completed setup default to Debug off. Settings → System → Debug enables hardware tests, HondaLink protocol tests and detailed recording. Switching it off hides those pages and stops protocol capture. The recovery page can also toggle Debug. Existing valid settings retain their app/theme/default choices and are treated as already set up; System → Setup wizard reruns the wizard without erasing those choices.

Normal operation retains bounded error logs and in-memory status, rather than recording packets and every UI/audio event. Core errors rotate at 256 KiB with two backups; detailed core logs rotate at 4 MiB with two backups. Plugin output is filtered in normal mode and its worker log rotates at 2 MiB with two backups. Android Auto and OBD logging follow the same Debug policy. Protocol capture has its own bounded retention. Existing old development logs are not deleted automatically.

The fresh image uses RAM-backed `/var/log` and volatile journald. Debug protocol captures and preferences live in persistent application state, so captures survive a reboot and can be inspected after a car test. A sudden loss of power can still lose the last buffered/in-flight events. Enable Debug before a test that needs packet evidence; normal mode cannot reconstruct packets it did not record. Manual Stop Recording remains stopped until Debug is toggled again.

## Storage protection and maintenance

The image mounts a separate writable ext4 `/persist` partition and binds application state, BlueZ bonds and NetworkManager connections onto it. Root overlay protection can therefore discard ordinary root writes while preserving setup choices, pairing, network credentials and recorded captures. The boot partition is protected too when enabling the mode. This reduces exposure to abrupt shutdown; the writable data partition is still subject to power-loss risks.

Settings → System → Storage protection checks the actual mounts before allowing changes. Enable protection, wait for the operation to finish, then use Restart. To undo it, choose writable mode and restart; first-boot maintenance completes the boot-partition transition after that restart. Do not interrupt configuration. The implementation invokes Raspberry Pi's `raspi-config` overlay support and verifies its reported configuration; actual boot behavior still requires Pi validation.

Existing installations without this dedicated partition cannot enable protection through HLauncher. The application deliberately does not repartition a live SD card. Back up and migrate to a freshly built image instead. There is no automatic application updater in this change; switch to writable maintenance mode before installing code or OS updates, then restore protection. System also includes an explicit, confirmed clean shutdown action.

## Existing checkout installation

`sudo bash scripts/install.sh` installs the application and new units but does not start them or repartition the card. After reviewing any older competing Bluetooth/application services, enable:

```bash
sudo systemctl enable --now hlauncher-firstboot hlauncher-pairing hlauncher-recovery hlauncher-audio hlauncher-connect hlauncher
```

A valid, already-paired `HLAUNCHER_RADIO_ADDRESS` is adopted once for migration. The persisted verified radio subsequently takes precedence. Forgetting a radio blocks automatic re-adoption of the old environment value. New installations may leave that value all zeroes. Recovery configuration on a general-purpose existing Pi uses its current NetworkManager and regulatory configuration.

## Required Pi/radio acceptance checks

Before releasing an image, build it on ARM64 Linux and verify: clean boot with no preloaded identity; radio pairing and successful HondaLink launch; pairing timeout/rejection/replacement; Bluetooth restart recovery; every wizard step and resume after reboot; enabled/default plugin behavior; HDMI, audio and microphone operation; phone recovery authentication and Wi-Fi; and Debug capture before/after a power cycle. Confirm profiles are advertised before the full UI starts.

Then test storage protection on a disposable SD card: enable/reboot, verify overlay root and read-only boot, change preferences and verify bonds/network survive, disable/reboot, and verify root/boot are writable again. Repeat a normal shutdown and an abrupt vehicle-power loss. None of these hardware/image acceptance checks can be replaced by the local unit tests.
