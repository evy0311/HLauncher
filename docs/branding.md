# UI artwork

Projection tiles use the CarPlay and Android Auto artwork requested for the UI.
The source URLs, authors and SHA-256 hashes are recorded in
`hlauncher/ui/assets/icons/sources.json`; notices are in
`THIRD_PARTY_NOTICES.md`. The artwork identifies the corresponding integrations.

The HLauncher OEM icon uses the approved full-name artwork: a red tachometer
and white HLauncher wordmark on a graphite tile, generated in the icon-design
chat. The unchanged master is `hlauncher/ui/assets/branding/hlauncher-source.png`.
`scripts/build_brand_icon.py` sizes that master into 120, 180, 256 and 512 pixel
PNGs while preserving its transparency. It is included under the repository
license. No radio firmware assets are used.

## CarPlay adapter icon

`plugins/carplay/runtime/usb/branding.mjs` uploads the packaged PNGs to the
adapter's existing OEM/120/180/256 icon paths, then sends the HLauncher box name
and OEM label. This runs before the adapter opens a phone session, and can also
be requested in Settings → Plugins → CarPlay → Adapter icon.

Uploads use node-CarPlay's existing SendFile and SendIconConfig messages, not a
firmware replacement. Settings and pairing on HLauncher are unchanged. Failed
transfers are logged and may be retried; they do not prevent normal CarPlay
startup. The transfer result means USB delivery, not confirmation that adapter
firmware persisted the files or the iPhone refreshed its cached icon. Reconnect
the phone to refresh the icon. Firmware without OEM icon support may ignore it.
Selecting the OEM icon uses the existing adapter home command to return to
HLauncher.
