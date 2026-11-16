# Legacy HondaLink capabilities and extension roadmap

This reference records the legacy HondaLink Connect app findings that can help
future HLauncher plugins. It distinguishes implemented features, recovered native
serialization, JavaScript bridge contracts, and untested vehicle behavior.
It describes the older HDMI/External Accessory integration, not modern HondaLink
remote services or the separate Aha IRAP protocol.

## Evidence and status

Native addresses below refer to the ARMv7 executable from Connect 1.0.0 (2013),
SHA-256 `8b957d788de6ff3e8ba975cb7d34d5bfbe1987d56be4d4666869b766da154aae`.
The readable SDK resources were compared across 1.0.0, 1.1.0, 1.1.1, 1.2.0 and
1.3.1. Native code was inspected statically; selected CAN serializers and
capability routines were also exercised in an isolated ARM emulator. That is
separate from running the original app or testing each feature on a radio.
Addresses, method names and field descriptions allow a contributor with their
own executable to reproduce the trace. No IPA, decompiled app code, account
material or downloaded customer data is included in this repository.

| Feature | Recovered behavior | HLauncher status / useful next step |
| --- | --- | --- |
| Vehicle telemetry | 168 API entries; 299 CAN layouts containing 1,441 named signals | API mapping/cache and full vehicle-data test page implemented; selected gauge fields implemented. Extra layouts need individual validation. |
| Call request | ASCII phone number in binary data type 1 | Not exposed to plugins; implement request lifecycle and radio acceptance tests before enabling. Does not provide call audio. |
| Navigation handoff | Coordinates, optional phone number and place name in binary data type 0 | Not implemented; capability-gate and test on a navigation-capable head unit. |
| Destination information | `GetDestinationPlace` reads cached head-unit authentication metadata | Not a demonstrated API for reading the active route destination; preserve its distinction from navigation coordinates. |
| Radio clock correction | Local calendar, base UTC offset and DST flag in binary data type 3 | Not implemented; useful for clock synchronization if the radio advertises support. |
| Voice recognition lifecycle | Availability, start/capability and end notices; incoming start callback | Partial radio/HFP/voice observation exists, but this HondaLink lifecycle is not a complete plugin service. |
| Exit phone display | A short control message asks to exit the phone display | Available as a Debug integration probe. The local plugin Home action returns to HLauncher. |
| Meter navigation guidance | Heading, destination direction, guidance flags/types, language and distance become CAN-data type 4 | Not implemented. Constructors recovered, but stock Civic parser rejects the query and packet form; see the meter-guidance trace. |
| VIN, head-unit identity, location, ignition count | Virtual records alongside physical CAN data | Aggregate parsing/diagnostics implemented; no general plugin telemetry subscription API yet. |
| DTC / freeze-frame context | Normal data type 0; B-CAN DTC 1; F-CAN DTC 2; F-CAN freeze-frame 3 | Diagnostics subscribe and retain records; friendly diagnostic decoding/presentation is incomplete. No ECU fault-clearing API is established. |
| Helpnet | CAN-data type 7 has special multipart assembly | No complete assembly/consumer implementation; do not treat each part as a full report. |
| Steering and connection state | Source mode AUDIO/APP/UNKNOWN and head-unit state callbacks | Core input/source-mode handling exists; no complete SDK-equivalent plugin event contract. |
| Driving and parking-brake state | Separate native/JS state APIs | HondaLink brake and speed feed the bundled Android Auto driving policy with independent freshness limits. See [vehicle data](vehicle-data.md). |
| Trip and maintenance history | Native storage includes trips, fuel totals, mileage, tire pressure, warning context and maintenance messages | Storage schemas are evidence of app behavior, not additional radio commands; future logging plugins can derive history from supported readings. |
| CRM messages | Read/listen, mark state and delete app-side messages | Not implemented. Message deletion/state updates are distinct from clearing ECU DTCs or resetting maintenance. |

## Capability negotiation

The B1 authentication-finish body is:

```text
01 success8 seedBase64ASCII[8] capabilityFlags8 destinationASCII[2]
```

The native callback `parserFoundAppAuthFinishResponse:cipherSeed:linkAvailability:destinationPlace:`
(`0xCFBFC`, emulator entry `0xCFBFD`) maps these bits:

| Bit | Meaning |
| --- | --- |
| `0x01` | Navigation link capability |
| `0x02` | Call link capability |
| `0x04` | Time correction |
| `0x08` | CAN data capability |

Other bits remain uninterpreted. Historical Civic captures included `0x1A`
and `0x12`: both contain the call bit, neither contains the navigation or time
correction bits. These are past observations, not permanent model capabilities.
Future plugins should receive the flags for the current authenticated session.
A method existing in the app does not mean a particular radio supports it.

`HLLpaCommunicator.getDestinationPlace` (`0x641BC`) returns the connected
head-unit object's cached `destinationPlace`; B1 supplies only two ASCII bytes.
Its exact regional semantics need confirmation. Do not expose this as the
currently selected geographical destination.

## Application payloads beyond CAN subscriptions

These byte layouts include message ID C2. Existing `send_honda(sid, mid, body, ...)`
expects the message ID separately; do not duplicate C2 in its body. Honda/iAP
framing and transport acknowledgments are additional layers.

### Short control notices

`LPAPayloadGenerator.generatePayloadForMessage:type:` (`0xDEB90`) emits:

```text
C2 00 01 messageType8 value8
```

| Message type | Value | Native sender |
| --- | --- | --- |
| `0x00` | 0 | Exit phone display, `0xD77D8` |
| `0x14` | 0/1 availability | Voice availability, `0xD79C8` |
| `0x16` | 0/1 capability | Voice start notice, `0xD7AE8` |
| `0x17` | 0 | Voice end notice, `0xD7C08` |

An incoming voice-start callback exists at `0x6464C`. Its complete triggering
message/value map still needs tracing; the outgoing type numbers above must
not be assumed to be the incoming ones. These notices coordinate voice state;
they do not establish a microphone codec, stream or audio route.

### Binary requests

The single-payload generator (`0xDE554`) emits:

```text
C2 00 00 sequence8 binaryType8 length16be data[length]
```

The generator dispatcher (`0xDE170`) uses this form for fewer than 951 data
bytes, uses a separate fragmented form for 951–65,535 bytes, and rejects larger
bodies. Fragmentation is not documented fully here. Binary type numbers and
CAN-data type numbers are separate namespaces.

The native send path (`0xD6968`) requires an established head-unit session,
allocates a sequence number, and delegates completion to a data-sending manager.
A future implementation needs its timeout/retry, receipt correlation and
operation-result semantics; a Bluetooth transport ACK alone is not proof that
a call was placed or a destination accepted. Incoming binary data is receipted
(`0xD02B0`); the original incoming-fragment callback (`0xD1444`) sends a NAK.
Do not assume symmetric fragment support.

#### Navigation: binary type 0

`sendNavigationRequestWithLatitude:longitude:phoneNumber:name:resultHandler:`
(`0xD7D00`) constructs:

```text
latitude32be longitude32be phoneASCII NUL nameUTF16BE
```

Each coordinate is degrees multiplied by `60 * 60 * 1000`, truncated toward
zero and stored in the low 32 bits (signed coordinates use two's complement).
Constants read from `0xD8220` and `0xD8218` are 60.0 and 1000.0. A missing
phone number still produces the NUL separator. The name is appended without an
explicit terminator in this routine. Input limits, character handling and
negative-coordinate acceptance need fixtures and head-unit tests.

The JS bridge's `HeadUnitCooperation/RequestNavigation` accepts latitude,
longitude, phone number and place name. Versions from 1.1.0 also accept an
optional address argument; samples use either `{addr: ...}` or separate state,
city, street and houseNumber fields. The optional address's native wire
encoding has not been recovered from the 1.0.0 routine. Do not serialize that
JS object directly to Bluetooth.

This is a handoff to supported radio navigation, not a navigation engine
running on the Pi and not a demonstrated route injection into CarPlay Maps.

#### Phone call: binary type 1

`sendCallRequestWithPhoneNumber:resultHandler:` (`0xD831C`) converts the number
to Foundation ASCII encoding and sends the resulting bytes as type 1. This
routine appends no NUL terminator. Number normalization, allowed characters,
length limits, radio confirmation UI and the selected telephone's behavior
need tests. No cellular modem or HFP audio stream is created by this request.

#### Clock correction: binary type 3

`sendTimeCorrectionInformationWithResultHandler:` (`0xD8560`) builds:

```text
baseUtcOffsetMinutes16be dst8 year8 month8 day8 hour8 minute8 second8
```

The base offset excludes the current DST adjustment; the divisor at `0xD8AF0`
is 60.0 seconds. Negative offsets use magnitude with bit 15 set, rather than
two's complement. DST is a boolean. The year byte is equivalent to year minus
2000 modulo 256, and the date/time come from the current local calendar.
Calendar edge cases and radio interpretation remain untested.

### Meter guidance is a separate transmit feature

The [meter-guidance trace](meter-guidance.md) now covers all three native
constructors: display fields (CAN-data type 4), multipart guidance data (5),
and multipart current-location data (6). Their record IDs match the factory
navigation family. A dedicated meter-support query uses short-message type
`0x0B`; all three senders require local enabled-features bit `0x02`, which
Connect's default features `0x09` leave off.

The inspected stock Civic firmware rejects both that query type and the
`C2 00 02` packet form used by these senders. Phone-side implementation alone
is therefore insufficient for this baseline. Text schema, maneuver codes,
radio forwarding and display behavior still need separate work. This path
is not part of the read-only gauge subscription.

## Vehicle receive protocol recovered from native code

See [vehicle-data testing](vehicle-data.md) for the UI and
[`vehicle_signals.json`](../hlauncher/protocol/vehicle_signals.json) for all 168
API mappings. Semantic API IDs are translated on the Pi; the radio subscription
contains message IDs and bit masks, not a list of those semantic IDs.

```text
C2 02 mode8 intervalTicks16be category8 settingsCount8 [settings...]
explicit setting: dataType8 count8 [id32be canType8 length8 mask[length]]...
preset setting:   dataType8 00 subcategory24be
```

Mode 0 is cyclic; ticks are tenths of a second. The original default is one
second. Physical selectors are B-CAN 0, F-CAN 1, OTHER 2; diagnostic settings
add 3. Original ALL plus feature metadata requests 54 distinct message IDs,
and the four settings are split over two payloads. HLauncher adds an experimental
i-MID audio-switch record to that full diagnostic request. Outside diagnostics,
it combines masks for active gauges and projection workers, including
headlights, speed and optional GPS. Full diagnostics keeps its one-second
interval. Receive timestamps establish actual cadence.

The encrypted normal receive body follows `C1 00 02 sequence8 date32be time32be
dataType8 bodySize24be`. Decrypt the body before reading its record count:
`count16be [id32be length8 data[length]]...`. Virtual records may exceed eight
bytes and use IDs above the physical 29-bit CAN range. Normal cyclic data has
no application-level receipt; other supported categories use
`C2 01 sequence8 success8`. Settings response is `C1 02 status8 info8`, with
status zero indicating success. The crypto, parser and cache live in
`hlauncher/protocol/vehicle_can.py`, `aes.py` and `vehicle_signals.py`.

## Plugin integration roadmap

These are proposed contracts, not callable SDK functions or live stubs:

| Proposed host operation/event | Required behavior before exposing it |
| --- | --- |
| `radio.capabilities` | Current connection generation, known flag bits, raw unknown bits, supported versus implemented state. |
| `vehicle.subscribe(ids, interval)` / unsubscribe | Host merges active consumers' masks, keeps per-field timestamps/source/raw values, bounds the requested rate, clears subscriptions when unused. Existing `vehicle.gauges` IPC is bundled-gauges-only. |
| `radio.request_call(number)` | Explicit user action, current call capability, host-owned sequence/receipt/result/timeout handling; no automatic calls on activation. |
| `radio.request_navigation(destination)` | Current navigation capability, validated coordinates/text, versioned address support, explicit result reporting. |
| `radio.voice_state` / voice notices | Coordinate mute, foreground/background, cancellation and timeout with existing audio ownership; no automatic audio-route changes. |
| `radio.correct_time` | Current time-correction capability and tested timezone/calendar conversion. |
| `radio.exit_phone_display` | Explicit user intent, supported session and clear distinction from plugin Home. |
| Meter guidance / Helpnet | Separate experimental implementation after record/assembly verification; not an enabled generic transmit endpoint. |

Keep transport, request queues and audio ownership in the host. Plugins should
receive typed events and bounded requests, not raw Bluetooth access. Unimplemented
operations should return an explicit unsupported result without sending bytes.
The first implementation can be a capability/status view and offline serializers
with fixtures, followed by one controlled feature test at a time. No dormant
command stubs were added to the running launcher by this documentation change.

## Local protocol versus Honda services

Native telemetry subscription, session-key derivation and decoding are local;
the recovered navigation/call/clock send routines contain no server request.
The original app's broader startup also uses Honda accounts, VIN/user checks,
VIN-selected template downloads, diagnostic uploads and online dealer/POI/weather
services. Those services are separate work, not prerequisites established for
the local wire operations above. Contact access, phone GPS, dialogs and iOS
JavaScript Audio are phone/UI features, not automatically radio commands.

The native CRM message API and voice/TTS sample providers also need separate
analysis of dependencies. A stored database field, JavaScript listener number
or sample fixture alone is not proof of a new Bluetooth operation. In particular,
JS event IDs 101–702 belong to native-to-WebView dispatch, not the wire protocol.
