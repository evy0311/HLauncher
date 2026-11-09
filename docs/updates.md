# Application updates and releases

Update-enabled images keep application versions under `/persist/hlauncher`,
separate from `/persist/state`, Bluetooth bonds, network profiles and user plugins.
`/opt/hlauncher` points to `current/app`; `/opt/hlauncher-deps` points to
`current/runtime`. Application updates work while OS overlay protection is on.
OS/boot/package/service changes still require a new image or a separately
validated writable-mode migration.

## User operation

Settings → System → Software updates offers **Check for updates**, **Restart and
install VERSION**, and **Restore version VERSION** when a previous installation
exists. Checks use stable releases from `evy0311/HLauncher`. They do not poll
GitHub in the background or install updates automatically. Connect Wi-Fi first.
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
image. A changed system contract (system services, installers or stable updater)
is rejected with a new-image requirement. Older source/development installations
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

Use an ARM64 Linux host/VM as root, a clean committed checkout, internet access,
a pristine uncompressed Raspberry Pi OS Lite Bookworm ARM64 image, and the key.
There is no emulated macOS or x86 image build in these scripts.

```bash
sudo bash scripts/build_release.sh 0.2.0 /images/bookworm-arm64-lite.img US \
  /secure/location/hlauncher-release.pem /releases/hlauncher-0.2.0 /releases/notes-0.2.0.md
```

The script builds native/Node dependencies once inside the image, then creates:

- `HLauncher-0.2.0-pi4.img.xz`: flashable fresh-install image.
- `HLauncher-0.2.0-pi4-arm64.tar.xz`: full application and native runtime bundle.
- `HLauncher-0.2.0-local-update.hlu`: signed container for local network upload.
- `hlauncher-release.json` and `.sig`: signed compatibility/checksum metadata.
- `HLauncher-0.2.0-sources.tar.xz`: project and fetched external sources.
- `release.pub`, `os-packages.txt`, `SHA256SUMS`, and `RELEASE-NOTES.md`.

The image is seeded with the same application files/version/manifest as the
update bundle. The writable partition defaults to 4096 MiB; override
`HLAUNCHER_PERSIST_MIB` only after measuring update capacity (minimum 2048 MiB).
Build output must use a fresh directory and should remain outside the repository.
Unsigned direct `build_image.sh` development builds do not get update trust/layout.
The country argument remains build-time configuration in this version.

Keep release notes short: changes since the previous release, plus essential
installation or compatibility information. Supply that notes file to the build;
it is copied into the release and covered by SHA256SUMS. Leave test reports and
build details out of the release notes.

Every future release must include both a production fresh-install image and all
signed updater files. `scripts/validate_release.py` blocks incomplete releases,
missing checksums, invalid signatures and local-test images before upload.

Push the source commit, test the image, then upload
all artifacts as a GitHub **draft** using authenticated GitHub CLI:

```bash
bash scripts/publish_release.sh 0.2.0 /releases/hlauncher-0.2.0
```

Publish that draft on GitHub after testing. Drafts/prereleases are not offered by
the updater. The release tag, signed manifest version and artifact names must
match. GitHub source archives alone are not installed as updates.

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
Radio and Wi-Fi. Connect your computer to the Pi's network and visit its recovery
page (`http://PI_ADDRESS:8080`, or `http://192.168.4.1:8080` on its hotspot).
Authenticate using the on-screen device setup credentials. Choose a `.hlu` file
under Local update and install it. The file is streamed to disk, checked with the
same pinned signing key, platform and version rules, and installed through the
same transactional installer. No Internet or GitHub release is required.

Local upload requires authentication, same-origin browser requests, bounded file
size, enough storage and an exclusive upload lock. Containers accept exactly
three regular files: manifest, signature and compressed package. Unsigned,
tampered and incompatible files cannot activate. Interrupted uploads can be
retried; an interrupted activation uses normal boot recovery. This endpoint is
not a shell or an unsigned-install bypass.

For a private development image with an additional SSH key, explicitly set
`HLAUNCHER_LOCAL_TEST_SSH_KEY` to an Ed25519 public-key path during the build.
The private SSH key never enters the image. The standard `pi` / `raspberry` login remains available, and the private test
image additionally accepts that development key. The signed manifest marks
it `local_test`, and the publishing script refuses to publish such an image.
This option is for private first-flash diagnostics, not public releases.

After building a local-test release, a version-only update can be made without
building the OS again:

```bash
python3 scripts/build_test_update.py --base /releases/local-0.2.0 \
  --version 0.2.1 --key /secure/local-test-release.pem \
  --output /releases/local-0.2.1
```

Upload its `.hlu`, verify 0.2.1 is installed, then choose Restore version 0.2.0 in
Settings. This helper refuses production release inputs and never publishes.
