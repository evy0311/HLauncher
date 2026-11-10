# Release workflow

- Keep release notes short: changes since the previous release and only essential
  installation or compatibility information. Leave test reports and build details
  out of the notes.
- Every future published release must include a fresh-install `.img.xz`, the
  signed updater bundle and metadata, the manual `.hlu` update, corresponding
  source archive, public signing key, checksums and short release notes.
- Validate the complete release with `scripts/validate_release.py` before upload.
  Do not publish an update-only release or an image with developer SSH access.
