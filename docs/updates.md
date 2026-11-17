# Application updates and releases

Update-enabled images keep application versions under `/persist/hlauncher`,
separate from `/persist/state`, Bluetooth bonds, network profiles and user plugins.
`/opt/hlauncher` points to `current/app`; `/opt/hlauncher-deps` points to
`current/runtime`. Most application updates work with storage protection on. A release that
changes the app's installed boot units requires writable mode. Changes to the
base OS or the stable updater require a compatible image or a separately
validated system migration.

## User operation

Settings → System → Software updates offers **Check for updates**, installation,
and **Restore version VERSION** when a previous installation exists. Stable
releases from `evy0311/HLauncher` are the default. Check **Include beta builds**
to include GitHub prereleases from `develop` in the next check. If both channels
have an update, the page offers both. Connect Wi-Fi first.

On a beta, **Check for updates** can also offer **Return to stable** if the
latest stable is older than the installed beta and compatible with the image.
Returning to stable keeps saved settings and plugins and retains the beta as
the previous installed version. The checkbox controls discovery of newer
betas. A check is manual and installation requires confirmation.

An older update-enabled image needs one signed update that includes the beta
checkbox. Install the first compatible beta with its local `.hlu` file through
the recovery page, or install a newer stable release that includes the checkbox
through the normal stable update check. The existing on-image updater verifies
the first install and its boot recovery works with either channel.
**Release notes** opens the notes from that GitHub release before installing.
Long notes have Previous/Next pages; Markdown is simplified to display text,
without executing HTML, loading images or opening external content.

The updater downloads signed metadata, checks platform/system compatibility,
checks available storage, and verifies the complete compressed package before
stopping any services. It stages a separate version, records a durable pending
transaction, replaces the current symlink, restarts the relevant services, runs
the dongle-free runtime self-test and Android Auto engine check, and checks a
fresh application heartbeat and registered Bluetooth profiles. A radio/phone is
not required for these startup checks. The UI is allowed to disappear during
restart. A failed activation restores and restarts the old version.

After a successful install, the exact previously installed version is retained.
Restore swaps back to it; the version just left becomes the restore option.
Downloading a new update never removes the current/previous version. After a
successful install, older unused versions are removed. Reserve capacity for the
running, previous and staged versions plus the compressed download and state.

The stable updater runs from `/usr/lib/hlauncher-updater`, outside application
versions. Its boot preflight reverts any incomplete transaction before app
startup. If the updater itself restarts mid-install, it also queues restarts of
the old application's services. File data, metadata and pointer switches are
fsynced, but filesystem corruption or a defective card still needs recovery
from a backup/new image; this is not a filesystem-level atomic OS updater.

Settings are not copied over or restored from old snapshots. v1 accepts only
state schema 1: releases must keep that schema backward-compatible. No downloaded
install/migration scripts execute. Native runtime dependencies under
`/opt/hlauncher-deps` travel with the app bundle; OS libraries remain in the base
image. The image's updater checks the signed system contract against its trusted
configuration. The contract covers the stable updater, its systemd unit,
system drop-ins and provisioning scripts. Application-owned service files are
updated separately with their app version. Older source/development installations
without the versioned layout show that an update-enabled image is required;
this feature does not repartition or convert a live personal Pi.

## Release signing key

Create an Ed25519 key **outside the repository**, on your release build host:

```bash
openssl genpkey -algorithm ED25519 -out /secure/location/hlauncher-release.pem
chmod 600 /secure/location/hlauncher-release.pem
```

Keep and back up this key. Every subsequent release for the same image family
must use it. The public key is pinned into the protected image; a downloaded
public key is never trusted. Public images/bundles include no private key. A lost
or rotated signing key requires a separately provisioned new trust anchor.

## Build a complete release

Use an ARM64 Linux host or VM as root, a clean committed checkout, internet
access, a pristine uncompressed Raspberry Pi OS Lite Bookworm ARM64 image,
and the signing key. Use a three-part numeric version such as `0.2.0`.
There is no emulated macOS or x86 image build in these scripts.

```bash
sudo bash scripts/build_release.sh 0.2.0 /images/bookworm-arm64-lite.img US \
  /secure/location/hlauncher-release.pem /releases/hlauncher-0.2.0 /releases/notes-0.2.0.md
```

The script builds native/Node dependencies once inside the image, then creates
the release assets:

- `HLauncher-0.2.0-pi4.img.xz`: flashable fresh-install image.
- `HLauncher-0.2.0-pi4-arm64.tar.xz`: full application and native runtime bundle.
- `HLauncher-0.2.0-local-update.hlu`: signed container for local network upload.
- `hlauncher-release.json` and `.sig`: signed compatibility/checksum metadata.
- `HLauncher-0.2.0-sources.tar.xz`: project and fetched external sources.
- `release.pub`, `SHA256SUMS` and `SHA256SUMS.sig` for verifying signatures and downloads.

The image is seeded with the same application files/version/manifest as the
update bundle. The writable partition defaults to 4096 MiB; override
`HLAUNCHER_PERSIST_MIB` only after measuring update capacity (minimum 2048 MiB).
Build output must use a fresh directory and should remain outside the repository.
Unsigned direct `build_image.sh` development builds do not get update trust/layout.
The country argument remains build-time configuration in this version.

Keep release notes short: changes since the previous release, plus essential
installation or compatibility information. Supply the notes file to the build.
The publisher uses the build directory’s copy as the GitHub release description.
Leave test reports and build details out of the release notes.

Every future release must include both a production fresh-install image and all
signed updater files. `scripts/validate_release.py` blocks incomplete releases,
missing checksums, invalid signatures and local-test images before upload.
`SHA256SUMS.sig` authenticates the checksum list with the release key. The
validator checks that the flash image decompresses and has a partition table
signature. It also compares the manual update's manifest, signature and
payload with the matching release assets.

Push the source commit, test the image, then upload
all artifacts as a GitHub **draft** using authenticated GitHub CLI:

```bash
bash scripts/publish_release.sh 0.2.0 /releases/hlauncher-0.2.0
```

Publish that draft on GitHub after testing. Use the same build and upload
process for a beta, with `--beta` before the version when running
`scripts/build_release.sh`. Build from a commit on `develop` and use a unique
numeric version newer than the latest stable. The beta channel is part of the
signed manifest. The publisher marks the draft as a GitHub prerelease and
checks that its source commit is on the pushed `develop` branch. Beta assets
include the same image, source, manual update and signatures as stable assets.
Choose a new numeric version for each release, including stable releases.

The updater checks the signed channel against GitHub's prerelease flag and
offers published releases only. The release tag, signed manifest version
and artifact names must match. GitHub source archives alone are not installed
as updates.

## Validation before distribution

Unit/integration tests exercise real signatures, tampering/traversal rejection,
settings preservation, failed activation, explicit restore and interrupted
transactions with temporary directories and simulated services. Before shipping,
boot the generated image on a spare card; install a second signed release; test
both restore directions, with/without a radio, and with SD protection enabled.
Interrupt power during download/staging/activation and verify boot recovery.
Test genuine low-storage and offline failures. Full ARM64 image builds and
power-loss hardware acceptance are required in addition to the local tests.


## Local update testing without GitHub

Open Settings → System → Software updates → Install local update file, or open
Settings → System → Wi-Fi. Connect your computer to the Pi's network and visit its recovery
page (`http://PI_ADDRESS:8080`, or `http://192.168.4.1:8080` on its hotspot).
Sign in as `hlauncher` with the device’s setup password on the setup hotspot or a trusted local network. Choose a `.hlu` file
under Local update and install it. The file is streamed to disk, checked with the
same pinned signing key, platform and version rules, and installed through the
same transactional installer. No Internet or GitHub release is required.

Local upload enforces same-origin browser requests, bounded file size, enough
storage, a ten-minute deadline and an exclusive upload lock. Containers accept exactly
three regular files: manifest, signature and compressed package. Unsigned,
tampered and incompatible files cannot activate. Interrupted uploads can be
retried; an interrupted activation uses normal boot recovery. This endpoint is
not a shell or an unsigned-install bypass.

For a private, update-enabled development image, run `build_image.sh` with
a separate test signing key, a fresh output directory and an Ed25519 public key
for SSH. The production release wrapper rejects the development SSH option.

```bash
sudo env \
  HLAUNCHER_LOCAL_TEST_SSH_KEY=/secure/local-test-ssh.pub \
  HLAUNCHER_RELEASE_VERSION=0.2.0 \
  HLAUNCHER_RELEASE_KEY=/secure/local-test-release.pem \
  HLAUNCHER_RELEASE_OUTPUT=/releases/local-0.2.0 \
  HLAUNCHER_RELEASE_COMMIT="$(git rev-parse HEAD)" \
  bash scripts/build_image.sh /images/bookworm-arm64-lite.img \
  /releases/hlauncher-local-0.2.0.img US
```

This builds an uncompressed test image and signed application assets. SSH for
`hlauncher` uses the configured public key. The signed manifest marks the build
`local_test`, which the publication validator rejects.

After building a local-test release, a version-only update can be made without
building the OS again:

```bash
python3 scripts/build_test_update.py --base /releases/local-0.2.0 \
  --version 0.2.1 --key /secure/local-test-release.pem \
  --output /releases/local-0.2.1
```

Upload its `.hlu`, verify 0.2.1 is installed, then choose Restore version 0.2.0 in
Settings. This helper refuses production release inputs and never publishes.

Activation, rollback and interrupted-update recovery install the matching
application service files and reload systemd. Turn off storage protection and
reboot before switching to a version that changes those files. The stable
updater runs outside the application release. To move to an incompatible
system contract, use a new image or a separately provisioned compatible system.
