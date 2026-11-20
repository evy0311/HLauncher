# Phone Projection investigation

Related issue: [#7](https://github.com/evy0311/HLauncher/issues/7).
Branch: `feature/phone-projection`, based on `develop`.

Target hardware is the owner's newer **Carlinkit CPC200-CCPA**. A read-only live inspection found that this unit advertises Android Auto; an
actual adapter AA session is still untested. Exact reported firmware/hardware
values are retained in the OMV live-adapter report. The older adapter and its 2020 firmware documented in the CarPlay
guide are historical test evidence, not a capability profile for this unit.
Native fallback in this investigation means **Android Auto over a USB cable
directly into the Pi**. Native wireless AA is outside this scope.

## Current implementation and findings

The launcher exposes separate CarPlay and Android Auto entries, but already has
shared media, voice, picture controls, background playback, and an exclusive
projection lease. The existing adapter driver recognizes both CarPlay (phone
type 3) and AA (type 5). Its startup settings include AA display dimensions.
This makes a shared adapter backend plausible; it does not establish that the
new dongle accepts AA or that its AA audio, buttons, microphone and exit action
work through HLauncher.

The bridge currently discards the Plugged transport field and logs BoxSettings
without delivering adapter capabilities to the core. The adapter landing page
calls every connection an iPhone. Native AA uses a distinct OpenAuto/aasdk
process with its own USB discovery. A worker being ready means the process is
running, not that a phone has completed projection negotiation.

This branch adds **Settings → Plugins → CarPlay → Dongle info** as a diagnostic
foundation. It exposes bounded live firmware, USB/product/hardware identifiers,
advertised AA support, phone protocol and reported transport through worker
health. Missing information remains Unknown. USB loss clears adapter facts;
phone disconnect clears session protocol/transport. No phone history is recorded
yet, and the two plugins have not yet been combined.

## Proposed architecture

Present one **Phone Projection** entry and settings page, backed by a core route
controller and two retained engines:

- Adapter engine: CarPlay or AA, based on the actual negotiated protocol.
- Native AA engine: direct USB Android Auto.

Keep the worker lease and existing process isolation. A logical presentation
entry should resolve to an engine; it must not be passed to generic worker
startup as if a third executable plugin had already been installed. Keep
backend identity separate from protocol and transport in state, media labels,
diagnostics, radio controls, voice handling, GPS and appearance settings.

Use explicit states: disabled, idle, adapter-waiting, native-USB-negotiating,
connected, switching, and recoverable-error. Include a session generation in
reports so delayed video, PCM, identity, and metadata cannot attach to a new
phone after handoff. Home navigation changes visibility, not ownership.

### Connection policy

An established session remains selected until disconnect or an explicit switch.
When idle, a directly attached AA candidate gets a bounded native negotiation
attempt; otherwise the adapter waits for a phone. Device presence is a candidate,
not proof of AA support. Never infer unsupported AA from a pairing timeout.

| Situation | Desired behavior |
| --- | --- |
| No dongle, no phone | One waiting page explaining both connection options |
| No dongle, Android attached to Pi | Start native wired AA |
| Dongle and iPhone | Start adapter CarPlay; identify actual transport if reported |
| Dongle and Android, AA supported | Use adapter AA after protocol type 5 is observed |
| Dongle lacks AA, Android attached to Pi | Release idle adapter engine, then start native wired AA |
| Dongle AA capability unknown, Android attached to Pi | Still permit native AA; no capability proof is required for a direct cable |
| Android connected only to an AA-incapable dongle | Explain that the cable must move to the Pi; native AA cannot reach through that dongle |
| Dongle idle, direct phone appears | Attempt native handoff without waiting indefinitely for the dongle |
| Active wireless CarPlay and direct Android appears | Keep CarPlay; offer an explicit switch |
| Active native AA and dongle appears or reconnects | Keep native AA; do not preempt it |
| Several candidates arrive while idle | Prefer a selected direct USB candidate; expose other candidates without alternating engines |
| Phone disconnects with dongle still attached | Clear media/voice/session identity; return to waiting |
| Dongle disappears during its session | Tear down adapter session; allow direct AA if a candidate is attached |
| Dongle disappears during native AA | Leave native AA running |
| Native AA engine is missing or disabled | Explain the unavailable route; preserve usable adapter projection |
| USB is busy or handshake fails | Bounded retry and useful error; restore adapter standby if safe; no retry storm |
| Unsupported/unknown phone type | Preserve raw diagnostics; do not classify it as CarPlay or AA |
| Reboot or abrupt power loss | Load preferences/history, but start with no live phone connected |

Direct AA and adapter USB ownership need a deliberate handoff. Today the adapter
worker holds the global lease even while waiting, so a second native worker
cannot simply be started alongside it. Keep passive USB discovery outside that
lease, then stop/reap the adapter process tree and acquire the lease before
native negotiation. Until per-device ownership is implemented and tested,
wireless adapter standby will be suspended while the native engine owns the
lease. Do not claim simultaneous independent sessions.

The pinned aasdk USBHub registers for all device arrivals and opens devices
before its accessory query; ConnectedAccessoriesEnumerator also walks the device
list. Both paths need an explicit adapter exclusion and selected-phone targeting
before automatic fallback. Track physical USB topology across AOA
re-enumeration rather than treating its expected detach/attach as another phone.
Do not repeatedly send AOA negotiation to unrelated USB equipment.

### Capabilities and phone history

Represent adapter AA capability as unknown, reported, or observed-working, with
the source and firmware fingerprint. An advertised list omitting AA is useful
evidence, not a universal hardware verdict. VID/PID, model name, presence and
silence do not independently prove support. Reset cached evidence when the
adapter or firmware changes.

For recent phones, distinguish **paired devices** from **observed connected
sessions**. The pinned driver parses the paired-list message and a transport
field; HLauncher currently does not surface them. Newer CCPA research describes
additional peer-address and BoxSettings identity data. Validate the exact
messages on this dongle before attributing a name to a session. Adapter Bluetooth
name/address and Wi-Fi SSID are not phone identity. The paired list alone does
not prove which phone is active, and phone type alone does not prove wireless.

Proposed local history: display name or user alias, identity confidence, last
connection time, protocol, transport evidence, and adapter association. Use an
adapter-scoped keyed identity where a peer identifier is actually observed.
When identity or transport is unavailable, retain Unknown rather than merging
phones by name or counting all paired devices as connected. Bound history and
provide Forget. Forgetting a launcher history entry is distinct from unpairing
the adapter. Do not store pairing PINs, keys, raw session tokens, or entire
BoxSettings dumps. Reconnect-to-a-specific-phone controls need separate protocol
verification; history does not imply that remote switching is supported.

## Migration and compatibility

Keep existing `carplay` and `android-auto` IDs valid internally and on disk for
the first implementation. Resolve existing home tiles and startup selections
to the unified presentation without discarding their route preference. Deduplicate
the visual tile while preserving a rollback-readable configuration. Preserve
explicit disabled-backend choices, per-protocol GPS/headlight preferences, adapter
branding, and CarPlay frame rate. Do not silently enable previously disabled AA.

Use a separate bounded, atomically written state document for route preferences
and phone history. Existing releases must still read their original settings
after rollback. Verify updater installation and rollback from the current release
before publishing this as a release.

## Implementation order and validation

1. Collect Dongle Info and session reports from this CPC200-CCPA, including its
   firmware. Wireless CarPlay and the presence of session name/peer-identifier
   fields have now been observed on the target adapter. Obtain an adapter AA
   capture with an Android phone before claiming that route works.
2. Add validated structured session/capability reports end to end; correct the
   adapter worker's protocol-specific labels and controls.
3. Add selected-device discovery/exclusions and test native AA with an idle dongle
   attached. Preserve the process-tree lease during handoff.
4. Implement the route controller against the cases above using fake devices,
   stale-report injection, re-enumeration, delayed USB release and failure tests.
5. Add the unified tile/settings and backward-compatible preference resolution.
6. Add observed-phone history using verified identity fields.
7. Bench and in-car test startup, background audio, reconnect, explicit switching,
   calls/mic/guidance, media clearing, radio controls, GPS/night mode, and updates.

Keep HDMI media at 48 kHz stereo PCM with the existing S32_LE endpoint. Neither
the unified UI nor phone history requires changing the audio format or the
radio's Bluetooth ownership.

## Sources and evidence

Local code: `hlauncher/projection.py`, `hlauncher/plugin_host.py`,
`plugins/carplay/backend.py`, `plugins/carplay/runtime/usb/bridge.mjs`,
`plugins/android-auto/native/bridge.cpp`, `hlauncher/config.py`, and the tracked
third-party patches.

- [Pinned adapter messages](https://github.com/rhysmorgan134/node-CarPlay/blob/670f19eda2a0b0047a5a538b9602b263f442433a/src/modules/messages/readable.ts)
- [Pinned adapter driver](https://github.com/rhysmorgan134/node-CarPlay/blob/670f19eda2a0b0047a5a538b9602b263f442433a/src/modules/DongleDriver.ts)
- [Pinned aasdk USB discovery](https://github.com/opencardev/aasdk/blob/9bf6adf933665dee26532201719fac14a047ccf1/src/USB/USBHub.cpp)
- [CCPA protocol research](https://github.com/lvalen91/CPC200-CCPA_resources/blob/main/documentation/02_Protocol_Reference/usb_protocol.md)
- [CCPA identification research](https://github.com/lvalen91/CPC200-CCPA_resources/blob/main/documentation/02_Protocol_Reference/device_identification.md)

External protocol notes contain conflicting paired-list IDs and transport-field
interpretations. The pinned parser uses paired-list type 0x12, whereas one
identification table says 0x0F. Keep raw values for bench investigation and prefer
verified captures over adopting either statement blindly. Research about another
firmware version is a lead, not a successful test on the owner's adapter.

Downloaded references and their URL/hash manifest are retained outside Git on
OMV under `Honda Radio Research/radio-research/phone-projection-2026-11-20`.
