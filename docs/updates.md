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

The screen groups installed and previous versions, keeps secondary actions quiet,
and emphasizes the next update action. Busy states use larger status text.
The visual polish follows [unslop by Damir Sokolovsky (@heydamir)](https://heydamir.design/unslop), CC BY 4.0.

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
page (`http://hlauncher.local/`, or `http://192.168.4.1/` on its hotspot).
Choose a `.hlu` file
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

## Development branches (issue #9)

Settings → System → Software updates → **Development builds** enables both
legacy develop betas and signed branch snapshots. Tap **Branch**, choose a
branch, then review **Install branch build**. The confirmation shows its branch
and exact commit; the update page also shows the build date in UTC. The selected
branch is remembered. Installations are manual, not automatic.

In the default signed-build mode, only compatible, signed, published builds appear. The catalogue checks up to
500 recent GitHub releases and chooses the highest installation build number
per branch. A raw Git branch without a published build cannot be installed.
The Pi needs Wi-Fi, not Git, a compiler, SSH access or a GitHub account.

The `feature/usb-device-diagnostics` branch adds **Settings → System → Debug →
Diagnostics → System diagnostics → USB devices** (enable Debug mode first).
It lists all USB devices detected by Linux, including hubs, with their port,
reported name, and hexadecimal vendor/product IDs. The list refreshes every two
seconds independently of the CarPlay plugin, and **Save report** includes the
inventory. A powered dongle that does not enumerate will not appear. On the
latest development build, enable **Unsigned source testing**, select this branch,
and review **Install unsigned source**. This Python-only change reuses the
existing native runtime; no SD card reflash is needed. A signed branch build can
also be installed if one is published.

When no branch snapshots exist, selecting `develop` retains discovery of older
numeric beta releases. Turning Development builds off prevents installation of
queued development offers as well as hiding discovery. Branch choice and opt-in
are checked again after downloading, before activation.

Development snapshots use `dev-VERSION` prerelease tags and signed metadata:
`channel=development`, `branch`, full `commit`, UTC `built_at`, and `build_id`.
The installation version remains three numeric components for compatibility
with the installed updater. Its first component is reserved at 10000 or above;
`development_builds.build_version()` encodes a globally unique build number.
Source application versions are not used to decide between branches. An
explicit branch switch can install an older snapshot, while ordinary stable
updates retain their existing version checks. Return to stable remains offered
even when its version number is below the development build. Restore swaps
back to the exact previously installed package and runtime.

Each downloaded manifest is verified with the image's pinned key and checked
against the platform, system contract and state schema. A changed selection,
invalid signature, changed offer, incompatible build, failed download or full
storage does not switch the installed application. The existing activation,
health checks and durable boot recovery are used for branch builds too.
The immutable updater files and their system contract are unchanged by this
feature. Preferences add only `development_branch`; the existing
`include_beta_updates` flag is retained for compatibility.

### Build and publish

Every published snapshot includes the complete release asset set, including
fresh-install image, signed update package, local `.hlu`, source archive, public
key and signed checksums. The Pi downloads the app/runtime update package.
Snapshots have no developer SSH access. Use the same signing key as existing
update-enabled installations.

On an ARM64 Linux release builder, from a clean committed checkout containing
this updater capability:

```bash
sudo bash scripts/build_release.sh --development feature/your-fix \
  10000.0.1 /images/bookworm-arm64-lite.img US \
  /secure/hlauncher-release.pem /releases/your-fix-10000.0.1 /releases/notes.md
```

Use a new globally unique installation version for every build. The version in
this example is illustrative, not a version to reuse. `publish_release.sh`
creates a draft by default. After validation, the explicit
`--publish-development` mode publishes a development prerelease and never marks
it as latest stable. It rejects stable/beta packages in that mode. Do not
republish a different package under an existing build version/tag.

`.github/workflows/development-builds.yml` provides automated builds on pushes to
`develop`, `feature/**`, `fix/**`, and `bugfix/**`, plus a manual branch input.
It is inactive until the repository variable `DEVELOPMENT_BUILDS_ENABLED=true`
is configured. It uses a dedicated self-hosted ARM64 Linux runner labelled
`hlauncher-release` and the `hlauncher-development` environment. Configure:

- `HLAUNCHER_BUILD_ROOT`: absolute directory for release output on the builder.
- `HLAUNCHER_BASE_IMAGE`: pristine, uncompressed Bookworm ARM64 image path.
- `HLAUNCHER_RELEASE_KEY_PATH`: existing signing key path on the builder.
- `HLAUNCHER_WIFI_COUNTRY`: two-letter country, such as `US`.

The runner needs the existing image-build tools, passwordless sudo, GitHub CLI,
Python/Pillow/NumPy/libsoxr and Node/npm for tests. Node-CarPlay and USB test
dependencies are prepared from the pinned lock files. The job checks out the
exact pushed commit, runs tests, builds and validates all release assets, then
publishes using the job token. It has no pull-request/fork trigger. The signing
key stays on the dedicated builder; it is never added to source or artifacts.
Output/checkouts remain on that builder for its normal retention management.
CI versions encode `GITHUB_RUN_ID * 1000 + GITHUB_RUN_ATTEMPT`; attempts must be
below 1000. No builder, signing key, repository variables or runner registration
has been provisioned by adding this workflow.

Branches must contain this packaging/updater capability. Rebase older feature
branches onto the updated develop before publishing them; installing code that
predates the branch picker would remove the picker with that application.
OS/system-contract changes still need their existing validated migration or
compatible image, and do not become installable merely by choosing a branch.

### Manual Pi validation before merge

1. Build a signed bootstrap snapshot of `feature/development-branch-updates`
   with the existing release key on the ARM64 builder. Building, publishing and
   deployment are explicit maintainer steps; source changes alone do not create
   an installable signed package.
2. Install its `.hlu` through the recovery page's local update upload. The
   existing updater can install its higher numeric version; a reflash is not
   needed on an update-enabled image with the matching contract/key.
3. Publish two compatible signed snapshots (on branches containing this feature).
   Check that an opted-out Pi only offers stable updates. Enable Development
   builds, refresh, and choose each branch; inspect commit/date and install.
4. Switch to the snapshot with the lower build number, restore the previous
   version, and return to stable. Check that radio pairing, Wi-Fi, user plugins
   and their data survive all transitions.
5. Check unavailable branch/network failure and interrupted/failed activation.
   Verify rollback/boot recovery on a disposable test image before release.
6. Merge into develop only after this live validation passes. The automated
   tests use signed fixture bundles and injected health failures; they are not
   a substitute for the real Pi installation/boot test.

Initial implementation validation (2026-11-20): the 12 new signed-branch,
packaging/publication and UI tests pass. The full Mac suite ran 374 tests:
366 passed, three skipped, and five errored because libsoxr is unavailable.
The existing updater contract hash is unchanged. Workflow YAML and embedded
shell blocks parse successfully; the complete ARM64 workflow and live Pi
installation remain to be verified on the release builder/test Pi.

### Unsigned GitHub source testing

Under Development builds → Branch, enable **Unsigned source testing** to list
GitHub branches directly. Select a branch and review **Install unsigned source**;
the confirmation identifies its exact commit and explicitly labels it unsigned.
This opt-in applies only to source testing from `evy0311/HLauncher`. Normal
stable/beta/published development updates still require signed metadata and the
image's existing pinned key.

The Pi downloads the selected commit archive over HTTPS, checks archive paths,
file counts and size limits, and stages a separate installation. It reuses the
installed native runtime only when native inputs, dependency locks, system
contract and existing boot service definitions match. Branches requiring
different native dependencies or boot services need a built update. No branch
installation scripts, package managers or build hooks run during staging.

The staged app retains source-updater controls when a branch predates this
capability. This compatibility overlay is recorded in `build-info.json` and
`release.json`; it means the result is the selected source plus the current
updater controls, rather than a byte-identical checkout. Branches advertising
`SOURCE_UPDATE_API=1` use their own source updater. Preferences/state remain
outside the release. The original durable activation, health check, rollback and
interrupted-update recovery paths are used. Source testing is checked again
after downloading. Switching it or Development builds off blocks queued source
installs. Signed return-to-stable discovery remains available.

Live bootstrap deployment on 2026-11-20 applied only the updater/UI changes to
the Pi's existing app, preserving its boot optimizations and boot files. Exact
originals are backed up under `/persist/hlauncher-source-updater-backup-20261120`
and on the research share. The runtime startup check passed; HLauncher,
reconnect and updater returned active with Bluetooth profiles registered and
zero app restarts. At the user's request, no feature branch was selected or
installed by the agent: the user performed that live test. The Pi confirmed a
successful unsigned installation of `feature/audio-eq` at
`03a7b9c8d05533501e97d4e1baae0285cd5053a3` with source-overlay metadata,
no pending transaction and previous version `0.2.12` retained. Bluetooth profiles
were registered, the app was active and its restart count was zero. Rollback
was not exercised on the live Pi. The compatibility overlay also publishes
UI readiness on older branches so the installed deferred-network policy can
resume networking after their UI; this adjustment was compiled/deployed without
another restart or branch switch. Twelve signed-development
tests and five source tests pass locally; 31 of 32 existing updater tests pass,
with the remaining test blocked by the Mac sandbox's local socket restriction.
Source tests cover raw branch discovery, multiple source installs and rollback,
native-input rejection, unsafe archives, opt-out during download and failed
activation. The stable updater source/installed contract was not changed.
