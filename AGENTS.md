# Release workflow

- Keep `main` on the latest stable release. Use `develop` for integration and
  branch feature work from `develop`.
- Promote a new stable version to `main` through a pull request. Keep a
  `release/v<VERSION>` branch at the exact source commit used for each release.

- Keep release notes short: changes since the previous release and only essential
  installation or compatibility information. Leave test reports and build details
  out of the notes.
- Every future published release must include a fresh-install `.img.xz`, the
  signed updater bundle and metadata, the manual `.hlu` update, corresponding
  source archive, public signing key, and signed checksums. Put release notes
  in the GitHub release description.
- Validate the complete release with `scripts/validate_release.py` before upload.
  Do not publish an update-only release or an image with developer SSH access.

## Updater compatibility

- All future changes must be installable through HLauncher's existing updater
  from the current released version on an update-enabled installation. Users
  must be able to upgrade without reflashing or repartitioning their SD cards.
- Preserve the installed updater's system contract and state compatibility,
  including saved user data and rollback. Verify the upgrade and rollback from
  the current release before publishing a new release.
