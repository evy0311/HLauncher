# Setup

The reference setup is a Pi 4 running Raspberry Pi OS Lite Bookworm, 64-bit. It uses HDMI and Bluetooth to the radio and a locally connected Carlinkit dongle. No X11, Wayland, browser or desktop is required.

## Install

From the Git checkout:

```bash
sudo bash scripts/install.sh
```

This installs OS dependencies, copies the code to `/opt/hlauncher`, runs `npm ci` using the committed lockfile, and checks the video/USB runtime. It leaves HLauncher services stopped; OS package installation may start package-provided services. Existing `/opt/hlauncher` installations are backed up before copying files. Pairing records and Wi-Fi settings are not copied or changed.

The installed units run as root because the current implementation accesses the framebuffer, console, Bluetooth profiles and USB dongle directly. Splitting those privileges is future work.

If you are migrating from the development setup, stop its launcher and avoid running two BlueALSA daemons or two CarPlay bridges:

```bash
sudo systemctl stop civic-hdmi-pi4-v42.service
sudo systemctl disable --now civic-bt-bench.service civic-bt-connect.service
```

Those commands apply only if those old units exist. Stop any other application that is opening the same dongle or framebuffer. Keep the old files for rollback.

## Bluetooth

The installer adds a BlueZ drop-in which disables AVRCP and restarts Bluetooth after a daemon failure. AVRCP caused daemon failures during this project's bench tests. This workaround can affect other Bluetooth uses of the Pi.

Check for other `bluetooth.service.d` overrides before proceeding. The older `99-civic-watchdog.conf`, if present, already implements the same workaround. Do not run another BlueALSA instance alongside `hlauncher-audio`.

```bash
sudo systemctl disable --now bluealsa.service bluealsa-aplay.service
sudo systemctl restart bluetooth
sudo systemctl start hlauncher-audio
bluetoothctl --agent DisplayYesNo
```

At the Bluetooth prompt:

```text
default-agent
power on
system-alias HLauncher
pairable on
discoverable on
```

Add a phone from the radio's HandsFreeLink settings. Select HLauncher and confirm the matching code on both sides. Approve profile authorization prompts if shown. Then:

```text
devices Paired
trust AA:BB:CC:DD:EE:FF
quit
```

Use the **HandsFreeLink radio's** address, not the Pi controller address. Replace the example address everywhere below. Save it in `/etc/hlauncher.env`:

```bash
sudoedit /etc/hlauncher.env
```

```text
HLAUNCHER_RADIO_ADDRESS=AA:BB:CC:DD:EE:FF
HLAUNCHER_LOG_DIR=/var/log/hlauncher
```

The address must match the paired peer: the listener rejects connections from other devices. The reconnect service trusts and reconnects an already-paired radio; it does not pair automatically.

## HDMI

Use the Pi 4's HDMI0 connector, the micro-HDMI connector nearest USB-C power, and connect it to the radio's HDMI input. The panel is **800x480**. The radio advertises 720x480 and 640x480 over HDMI, so automatic mode selection originally produced 720x480. Forcing **800x480 at approximately 60Hz** was verified on the development Pi: DRM and the RGB565 framebuffer both reported 800x480, and the owner confirmed the radio displayed the picture correctly. Touch coordinates are scaled to the actual framebuffer size.

The renderer requires RGB565, 16 bits per pixel. The launcher unit sets this before starting:

```bash
sudo fbset -depth 16
fbset -s
sudo python3 /opt/hlauncher/scripts/check.py --display
```

Expect `rgba 5/11,6/5,5/0,0/0`. The check inspects the framebuffer without drawing to it. A framebuffer with a different layout is rejected rather than displaying corrupt pixels.

Use the default Bookworm KMS display driver (`dtoverlay=vc4-kms-v3d`). If HDMI isn't detected at boot, first check the cable, HDMI connector and radio input. To use the verified 800x480 output on this Civic radio, append this to the existing **single line** in `/boot/firmware/cmdline.txt`:

```text
video=HDMI-A-1:800x480M@60D
```

Back up that file first and retain its existing root/PARTUUID and other arguments. Reboot after changing it. HLauncher does not edit boot settings automatically. The `M` requests generated CVT timings and `D` forces digital output, since this resolution is absent from the radio's advertised modes. Other radios may not accept it; restore your backup if the picture disappears. A 60Hz HDMI mode does not guarantee a 60fps CarPlay stream.

The launcher switches tty1 to graphics mode while it is running, hiding the login cursor. It restores the previous console mode on a normal exit.

## Start

Plug the Carlinkit dongle into a Pi USB host port. Connect the iPhone to the dongle. USB/IP and VirtualHere are not needed for the Pi 4 setup.

```bash
sudo systemctl enable --now hlauncher-audio hlauncher-connect hlauncher
```

Open HondaLink on the radio. Select CarPlay in the Pi launcher. Tapping CarPlay's Honda icon returns to the Pi launcher; it does not exit to the radio's home screen. A Home button is also available on the waiting-for-phone page.

For a manual two-hour run instead of the installed launcher service:

```bash
sudo systemctl stop hlauncher
sudo bash -c 'set -a; . /etc/hlauncher.env; set +a; cd /opt/hlauncher; exec /usr/bin/python3 -m hlauncher run --seconds 7200'
```

Start the installed service again afterward with `sudo systemctl start hlauncher`. Never run both listeners at once.

## Plugins and preferences

Settings is built into the launcher. It lists every installed plugin and lets you enable or disable it. Tap **Start with** to cycle between Launcher and the enabled plugins. Changes are saved in `/var/lib/hlauncher/settings.json`. Disabling the default plugin resets the default to Launcher. Returning with CarPlay's Honda icon always goes to the launcher, even when CarPlay is the default.

CarPlay is bundled and enabled initially. Android Auto and OBD gauges are planned integrations, not installed apps. See [plugins](plugins.md) for installing an external plugin or writing one.

The core exposes an opt-in microphone capture API. The radio still gates live microphone samples behind its hands-free call state. This refactor does not add CarPlay audio or automatic call simulation; the earlier microphone experiment remains documented in Git history.

## Logs and recovery

```bash
sudo systemctl status hlauncher hlauncher-audio hlauncher-connect --no-pager
sudo journalctl -u hlauncher -n 100 --no-pager
sudo journalctl -u hlauncher-connect -n 50 --no-pager
lsusb -d 1314:
sudo node /opt/hlauncher/plugins/carplay/runtime/usb/bridge.mjs --check
```

Protocol and bridge logs are written to `/var/log/hlauncher`. They can contain device identifiers and packet contents; review them before sharing. Log rotation is not implemented in this snapshot.

If Bluetooth restarts and HondaLink no longer opens, restart HLauncher so it registers its profiles again:

```bash
sudo systemctl restart hlauncher
```

If the display shows the Linux console, inspect the HLauncher journal and framebuffer format. If the waiting page cannot find the dongle, use `lsusb` and ensure another CarPlay process has not claimed it. Kernel USB stalls may require a Pi reboot; restarting a userspace service cannot always recover them.

To stop the installation:

```bash
sudo systemctl disable --now hlauncher hlauncher-connect hlauncher-audio
```

The BlueZ workaround is `/etc/systemd/system/bluetooth.service.d/90-hlauncher.conf`. Remove that file and restart Bluetooth only if you also want to undo the workaround. Keep your pairing records.
