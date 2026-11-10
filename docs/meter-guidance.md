# HondaLink meter guidance and i-MID investigation

The recovered Connect SDK can construct outgoing navigation guidance for a
vehicle meter. Its message IDs match those in the previously examined factory
CR-V navigation implementation. However, the stock Civic Communication.exe
baseline rejects both its meter-support query and its outgoing CAN-data packet
form. This is an SDK capability, not a working HLauncher/i-MID feature.

No radio commands, CAN transmissions, firmware changes or Pi deployment were
performed for this trace. All findings remain local. There is no public plugin
send API for these operations.

## Three navigation paths to distinguish

1. **Phone navigation on Display Audio:** the smartphone provides navigation
   shown on the main radio display, with guidance audio. Honda's original
   [2013 announcement](https://hondanews.com/en-US/honda-automobiles/releases/release-014089f9dc6e4eb49b22bb81065067cf-honda-evolves-in-car-connectivity-with-new-display-audio-touch-screen-interface-and-next-generation-hondalink-technology)
   describes separate Connect and Navigation apps, touchscreen maps and audio
   guidance. It does not establish that the phone app sends meter guidance.
2. **Destination handoff:** the binary-type-0 request passes coordinates and a
   place name to supported head-unit navigation. It is not a stream of upcoming
   maneuvers. See the [capability reference](hondalink-capabilities.md).
3. **Meter guidance:** the SDK's CAN-data types 4, 5 and 6 construct display
   fields and multipart guidance/location data for forwarding toward the meter.
   This is the path examined here. The B1 navigation capability bit does not
   establish support for this separate feature.

## Native trace

Addresses refer to Connect 1.0.0 ARMv7, SHA-256
`8b957d788de6ff3e8ba975cb7d34d5bfbe1987d56be4d4666869b766da154aae`.

| Operation | Sender | Record constructor | CAN-data type | Record IDs |
| --- | --- | --- | --- | --- |
| Guidance display | `0xD8D70` | `0x10409C` | 4 | `0x12F95955` |
| Guidance information | `0xD9230` | `0x104768` | 5 | `0x12F95B55`, `0x12F95C55` |
| Current-location information | `0xD9610` | `0x1054A8` | 6 | `0x12F95D55`, `0x12F95E55` |

All three senders check the local communicator's enabled-features bit `0x02`
(METER). Connect initializes features to 9 (`0x09`), leaving this bit off.
That is a local SDK configuration bit, not a permission granted by changing a
B1 flag, nor proof of support by the radio.

The send path is:

```text
sendMeter... -> LPACanMessage constructors -> sendCanData:type:date:...
 -> sequence allocation -> LPAPayloadGenerator -> data-sending manager
```

`sendCanData...` is at `0xD7088`. The generator at `0xDED50` writes:

```text
C2 00 02 sequence8 date32be time32be canDataType8 bodySize24be body[bodySize]
```

The translator constructs count/ID/length/data records; the configured CAN
cryptor encrypts that record body before it is appended. This is separate from
C2 subtype 2 telemetry subscription settings. The implementation also needs
receipt/result correlation and timeout/retry state; transport acceptance alone
would not prove that the meter displayed anything.

## Support query and response

`sendMeterLinkAvailabilityQuery` (`0xD78D0`) sends:

```text
C2 00 01 0B 00
```

The native receive dispatch block (`0xD0814`) interprets short-message type
`0x0B` and invokes `communicatorDidReceiveMeterLinkAvailability:` with
`value != 0`. In the corresponding C1 short-message form the response is:

```text
C1 00 01 0B available8
```

This dedicated negotiation is more relevant to meter support than assuming
that navigation, CAN receive access or an HDMI map display implies it.

## Guidance-display record

`GUIDE_DISP_DEMAND`, B-CAN ID `0x12F95955`, length 8. The names and widths come
from the recovered CDL layout and the constructor's actual signal assignments.
Numbering is zero-based; high/low refer to a byte's most/least significant bits.

| Byte | Packing |
| --- | --- |
| 0 | Heading direction: high 4 bits; destination direction: low 4 bits |
| 1 | Angle flag bit 7; street flag bit 6; unverified flag bit 5; double-maneuver flag bit 4; guide type low 4 bits |
| 2 | Double-guide buffer number: high 4 bits; single-guide buffer number: low 4 bits |
| 3 | Message type, 8 bits |
| 4 | Voice flag bit 7; navigation language setting low 7 bits |
| 5 | Distance indicator/percentage, 8 bits |
| 6–7 | Distance display selector high 4 bits; distance number remaining 12 bits |

The SDK inverts its `voiceGuidanceFlag` argument when assigning `C_VOICE_FLAG`:
true becomes 0 and false becomes 1. Do not infer the flag's user-visible behavior
from the argument name alone. Numerical dictionaries for heading, guide type,
message type, language and distance units remain unresolved. A raw nibble must
not be labeled left/right/meters/feet without further evidence.

The constructor was exercised in an isolated ARM emulator with Foundation and
message-object creation stubbed. A mixed-field test produced signal values that
pack to `12 a3 45 06 07 08 9a bc` using the recovered CDL layout; both voice-flag
polarities were checked. These are synthetic serializer checks, not a usable
route instruction or a captured car frame.

## Multipart guidance and location data

The constructors take NSData bytes. They do not accept a road-name string,
perform a text conversion, or supply an application-level text schema.

| Stream | Control ID | Data ID |
| --- | --- | --- |
| Guidance | `0x12F95B55` | `0x12F95C55` |
| Current location | `0x12F95D55` | `0x12F95E55` |

For nonempty input of length N, the constructor emits a four-byte control record:

```text
20 lengthHigh8 lengthLow8 packetCount8
packetCount = ceil(N / 7)
```

It then emits data records with one packet-index byte (starting at 1) and up to
seven input bytes. The CDL layout is eight bytes; unwritten final fields default
to zero in the independent packing check. Final on-radio length/padding behavior
still needs validation. The native entry point rejects empty input and input
above 65,535 bytes, but its packet count/index are only eight bits: input above
255 chunks (1,785 bytes) overflows those fields. That permissive length check is
not evidence of a usable large-payload protocol.

The original ARM constructors were checked for both streams at input lengths
0, 1, 6, 7, 8, 14, 15, 1,785, 1,792 and 65,536. This verifies record selection,
byte order, seven-byte segmentation, numbering and the overflow limitation.

The earlier CR-V factory navigation trace independently found:

- Guide display ID `0x12F95955` at Navi.exe `0x59CF40`.
- Guide-point IDs `0x12F95B55/0x12F95C55` at `0x59E474`, including a text buffer.
- Current-position IDs `0x12F95D55/0x12F95E55` at `0x59EBD4`, also string-bearing.
- A B-CAN controller send path and incoming `0x12F95Axx` reply handling.

Matching IDs establish a shared message family. The donor's controller
multipart representation includes its own framing/checksum behavior; it must
not be confused with the phone SDK's seven-byte chunker. A full text-record
formatter, character encoding, buffer-selection rules, reply state machine and
Civic display behavior are not established by matching the IDs. There is no
confirmed arbitrary-text or framebuffer-drawing command here.

## Concrete limitation in the stock Civic firmware

The inspected stock Civic baseline Communication.exe has SHA-256
`cdda1bcc4d53e08087899faef7be1512baa563098c1603496384612e435b1f43`.
Two separate parser gates differ from the generic phone SDK:

1. `GetCommandType` at `0x165314` accepts only short-command types `0x00`,
   `0x14`, `0x16`, `0x17`, `0x1E`. Its branch block at `0x16535A` rejects meter
   query type `0x0B`; `OnRecvCommand` at `0x12CB8C` has no meter-query branch.
2. `CheckPackDataType` at `0x1626DC` handles C2 prefixes `00 00` (binary data),
   `00 01` (short message), `00 03` (binary fragment), `01` (receipt) and `02`
   (settings). Its C2 branch at `0x1627B2` leaves `00 02` unrecognized. That is
   exactly the prefix produced by the SDK's outgoing meter CAN-data generator.

The short-command branch was checked with all 256 synthetic type bytes. The
C2 classifier branch was checked with six prefix combinations including the
unsupported meter-data form, using a small instruction-level SH interpreter.
This does not run the outer transport or MCU, but corroborates the static
branches rather than merely relying on absent strings.

**Conclusion for this baseline:** implementing the recovered phone sender alone
is insufficient. The stock handler rejects its forms before any demonstrated
meter forwarding. A different firmware/app route could differ; the result is
specific to this recovered baseline. Changing the app feature bit, making CAN
subscriptions broader or increasing a retry rate does not fix these gates.

## What “dashboard reminders” means

`METER_NAVI_RMD` (`0x12F97350`) contains these separate fields:

- Byte 0: `C__MID_INFO`, the unclassified eight-bit API 76 value.
- Byte 1 bit 3: `C_PARK_BRAKE_WRN_RMD` (parking-brake reminder).
- Byte 1 bit 2: `C_SEAT_BELT_WRN_RMD` (driver seat-belt reminder).
- Byte 1 bit 1: `C_AS_SEAT_BELT_WRN_RMD` (front-passenger seat-belt reminder).

Those reminder flags are distinct from the physical parking-brake switch or
belt buckle state. The factory donor consumer publishes them through warning
state. Their proximity does not establish that `MID_INFO` encodes a warning,
active page, navigation preference or text content; its value meanings remain
unknown. These are observed inputs, not commands that create reminders.

## Practical next work

Preserve the offline constructors and add an explicit meter capability status
before building any plugin operation. Resolve the text schema and maneuver
codes from the separate Navigation app or a working factory navigation capture.
For this Civic firmware, investigate a narrowly scoped radio-side bridge to its
existing meter/B-CAN controller interface, including replies and cleanup, or
identify a genuinely supported alternative route. Firmware/controller work is
separate from the Pi-only HondaLink implementation. No runtime transmit stub
should advertise success while these gates remain unresolved.

Local research reproduction artifacts are `trace-meter-guidance.py`,
`meter-guidance-verification.json`, `trace-meter-radio-gates.py` and
`meter-radio-gate-verification.json` in the November 10 app protocol audit.
The first check executes three original ARM constructors (22 checks total);
the second executes the two small SH branch blocks. Private binaries and
Ghidra exports remain outside this repository. Neither check establishes
physical CAN emission, electrical compatibility or an actual i-MID display.
