# Flash an HLauncher image

Use this path for a fresh installation. It replaces the card's contents. To keep
an existing update-enabled installation, use [application updates](updates.md).

## Download and verify

Download `HLauncher-VERSION-pi4.img.xz` and `SHA256SUMS` from the same
[GitHub release](https://github.com/evy0311/HLauncher/releases). Replace VERSION
below with that release's version. If a release has no image, choose one that
does, or [build a complete release](updates.md#build-a-complete-release).

Compute the checksum of the **compressed download**, then compare it with its
filename's entry in `SHA256SUMS`. They must match exactly.

For a release that supplies `SHA256SUMS.sig`, you can authenticate the
checksum list with OpenSSL 3. In this example, `release.pub` is your trusted
copy of the HLauncher public key.

```bash
openssl pkeyutl -verify -pubin -inkey release.pub -rawin -in SHA256SUMS -sigfile SHA256SUMS.sig
```

macOS:

```bash
shasum -a 256 HLauncher-VERSION-pi4.img.xz
```

Linux:

```bash
sha256sum HLauncher-VERSION-pi4.img.xz
```

Windows PowerShell:

```powershell
Get-FileHash .\HLauncher-VERSION-pi4.img.xz -Algorithm SHA256
```

The `.hlu` file is for local application updates; the `pi4-arm64.tar.xz` bundle
and source archives are not disk images.

## Write the card

Choose either tool on your computer:

- [Raspberry Pi Imager](https://www.raspberrypi.com/software/): select
  **Raspberry Pi 4**, choose **Use Custom** for the OS, select the `.img.xz` file
  and your microSD card, then skip OS customisation and write.
- [balenaEtcher](https://etcher.balena.io/): choose **Flash from file**, select
  the `.img.xz` file, select your microSD card, then flash.

If your writer requires an uncompressed image, extract it to `.img` first.
Double-check the target: flashing erases the card. Let verification finish before
ejecting it.

Use a card large enough for the uncompressed image and free space for application
updates; 16 GB or larger is a practical starting point. The final data partition
expands automatically to use the remaining card capacity after boot. Do not
manually expand the OS partition into that space.

## First boot

1. With power disconnected, insert the card and connect Pi HDMI0 (nearest USB-C
   power) to the radio. Attach the plugin's phone/USB adapter as described in its
   guide, then power the Pi.
2. On the radio, open **Settings → Phone → Connect a phone → Add Bluetooth
   device**. Select **HLauncher** and confirm within the five-minute pairing
   window. No SSH commands or Bluetooth address edits are required.
3. Park safely and engage the parking brake. Open **HondaLink**, read and
   acknowledge the safety agreement, then complete
   **Welcome → Apps → Startup → Appearance → Network → Finish**. For phone
   connection setup, see [CarPlay](../plugins/carplay/README.md) or
   [Android Auto](../plugins/android-auto/README.md).
4. Network setup is optional. Storage protection is offered only when the
   persistent-data layout passes its checks; wait for configuration to finish
   and use Restart when prompted.

The image already includes both projection engines, the services and the tested
720×480 HDMI0 mode. Do not run the source installer over a release image.

## If pairing or the display does not work

The initial HDMI welcome may be invisible until the radio is paired. Wi-Fi starts
off on a fresh install. Use Ethernet if you need the setup page before you can
reach the wizard. From the wizard's Network step or **Settings → System → Wi-Fi**,
open **Setup hotspot** and select **Start setup hotspot**. Join the hotspot with
`ilovevtec1234`. If the setup page does not open automatically, visit
[http://192.168.4.1/](http://192.168.4.1/). On Ethernet or personal Wi-Fi, open
[http://hlauncher.local/](http://hlauncher.local/) or the Pi's IP address.
The recovery page opens without a login and can reopen pairing or select a
radio manually.

After first boot, `HLAUNCHER-SETUP.txt` on the card's boot partition lists this
Pi's connection details. Shut down before removing the card to read it on another
computer. On a managed image, SSH starts off. Enable it on the radio under
**Settings → System → Wi-Fi → SSH access**. The initial SSH login is
**`hlauncher`** / **`ilovevtec1234`**. Change the password with `passwd` while
storage protection is off so the change survives reboot.

See [first boot, Wi-Fi and storage protection](onboarding.md) and
[HDMI troubleshooting](setup.md#hdmi) for more detail.
