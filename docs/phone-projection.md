# Phone Projection

Related issue: [#7](https://github.com/evy0311/HLauncher/issues/7).
Branch: `feature/phone-projection`, based on `develop`.

Target hardware is the owner's newer **Carlinkit CPC200-CCPA**. A read-only live inspection found that this unit advertises Android Auto; an
actual adapter AA session is still untested. Exact reported firmware/hardware
values are retained in the OMV live-adapter report. The older adapter and its 2020 firmware documented in the CarPlay
guide are historical test evidence, not a capability profile for this unit.
Native fallback in this investigation means **Android Auto over a USB cable
directly into the Pi**. Native wireless AA is outside this scope.

## Implemented on this branch

Home, Plugins settings, and setup expose one **Phone Projection** entry. The
landing page shows a phone/display symbol and live waiting/connection status.
A bottom-left settings cog opens combined settings, including Phones, dongle
information and explicit dongle/direct USB connection choices. A reported phone
connection automatically brings its projection session to the foreground when
the landing page is visible; settings remain open until the user leaves them. The waiting/disconnected view
uses that same landing page. The two
existing engine IDs, enable flags, startup IDs, media routing, and exclusive
process-tree lease remain intact for upgrade/rollback compatibility. Existing
startup choices still start their selected engine automatically. Settings retain
independent GPS/headlight preferences for the dongle and direct USB paths.

Passive sysfs discovery recognizes AOA accessory IDs and Android-labelled USB
phones, excluding the Carlinkit vendor. A newly attached candidate can hand off
an idle dongle worker to native AA. It never preempts a reported connected
session. Native negotiation gets 30 seconds; an unsuccessful automatic attempt
returns to dongle standby. An unplug gets an eight-second grace for AOA
re-enumeration. Unrecognized phones can always use the explicit direct USB
button. A phone plugged into an AA-incapable dongle must physically move its
cable to the Pi; the native engine cannot reach through the dongle.

The aasdk integration additionally excludes vendor 1314 from both hotplug and
startup AOA enumeration before opening the USB device. This patch must be built
into the native engine; Python changes alone cannot update an installed binary.

**Phones** distinguishes an identified live peer from paired-only devices and
previously observed phones. DevList and current-session btMacAddr/btName reports
are used; adapter Bluetooth names are never treated as phone names. Local
`projection-phones.json` retains at most 32 records with a hashed peer identity,
name, last protocol/transport and last observed connection time. Live/paired
flags are not restored across reboot. Repeated reports do not rewrite storage.
Phone details are removed from normal health/status logging. The direct USB
engine currently shows a generic session row; it does not expose a durable phone
identity. No remote phone switching or unpairing is claimed.

Dongle info shows live USB/product/hardware, firmware, advertised AA support,
negotiated protocol and reported transport. Unknown facts remain Unknown;
advertised AA is not a successful AA connection test.

### Audio dropout diagnostics

- Bridge reports use a monotonic timestamp and include per-stream PCM gaps of
  at least 100 ms, USB receive silence, Node event-loop delay and PCM backlog.
- Existing one-second packet/video-gap statistics include event-loop/backlog
  fields, surfaced in worker health alongside decode/forward/drop counters.
- HDMI mixer logs input gaps, starvation/resumption, maximum player write time,
  and existing ALSA stderr/underrun/player errors with correlation timestamps.
- Slow launcher draws are sampled during projection. Route selections, automatic
  fallback, and fresh/expired parking-brake changes are logged explicitly.

Pauses, track transitions and voice-stream stops can legitimately create gaps.
These observations locate the interrupted stage; they do not establish a cause
or promise that the previously observed cutouts are fixed. HDMI output routing,
48 kHz stereo target and EQ processing are unchanged by this branch.

### Parking brake and linked project

Reviewed [bean-headunit's CarPlay notes](https://github.com/AliMacky/bean-headunit/blob/main/docs/carplay.md).
Its A15W / YMA0-WN16-0003 adapter and 2026.07.31 firmware family match the owner's
reports. The notes confirm DevList and current-peer fields, retry/heartbeat
requirements, and Bluetooth disconnects during otherwise working sessions.
Its audio implementation is explicitly untested, so it supplies no dropout fix.
It documents no parking-brake host message.

Neither our pinned node-carplay driver nor the inspected CCPA USB protocol
reference provides a verified parking-brake wire format. Therefore the dongle
path logs the car's brake reading with `forwarded=false` and
`reason=usb_protocol_unverified`; it does not invent a command, write an unknown
firmware setting or simulate a permanently parked car. Native direct USB AA
retains its existing fresh speed/brake sensor forwarding. Dongle forwarding
needs a verified command or a capture of a known host sending real brake changes.

## Remaining architecture research

The following design and test matrix describe follow-up work, including real
hardware validation; they are not claims that every adapter/phone combination
has passed.

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
field. This implementation uses validated BoxSettings peer identity reports
from the newer dongle; the older paired-list message is not used to infer an
active phone. Additional firmware-specific peer messages still need validation. Adapter Bluetooth
name/address and Wi-Fi SSID are not phone identity. The paired list alone does
not prove which phone is active, and phone type alone does not prove wireless.

Further history improvements: user aliases, identity confidence, last
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

## Validation and remaining hardware checks

79 focused tests pass, including waiting-screen/cog navigation, automatic
foreground connection, idle USB fallback versus an established session,
negotiation timeout, lease handoff, phone identity/history and PCM gap logging.
The full Mac suite ran 376 tests: 368 passed, three skipped, and five errored
because libsoxr is not installed. The bridge self-test, Python compilation,
shell syntax and whitespace checks pass. The native USB exclusion patch applies
and reverses against the pinned aasdk source. OEM, Touring and Drive previews
were rendered and reviewed at 720×480.

This branch has not been deployed to the Pi. The native USB exclusion requires
rebuilding the external AA engine. Before release, verify:

- Wireless CarPlay reconnect, the named phone list, microphone/voice and exit.
- Dongle Android Auto using a real Android phone; advertised support is not proof.
- Direct USB AA with the dongle attached, AOA re-enumeration, unplug and handoff.
- Audio dropout reproduction while navigating, correlating the new diagnostics.
- Updater installation/rollback from the released image.

No confirmed dropout fix or dongle parking-brake forwarding is claimed. Neither
the unified UI nor phone history changes the HDMI format or radio Bluetooth
ownership.

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
