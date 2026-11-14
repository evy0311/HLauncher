# HondaLink vehicle data tests

Enable Debug mode, then open Settings → System → Diagnostics → HondaLink →
Vehicle data. Hardware tests → HondaLink vehicle data opens the same page.

- **All signals** lists the 168 legacy HondaLink vehicle API entries. Tap a row
  to inspect it. Drag the list or use its scrollbar and arrow buttons.
- **Selected signal** shows the converted value, freshness, selected CAN source,
  raw bytes and receipt/change counts. Previous/Next moves through the entries.
- **Raw / status** shows subscription progress, raw-record counts and the latest
  authentication/decryption error.
- **Start recording** saves a bounded protocol capture, including raw records
  and decoded API values, under `/var/lib/hlauncher/protocol-captures`. Record a
  short session and stop it after testing. The existing capture storage limit
  still applies. `scripts/protocol_capture.py` summarizes recorded API values.

While this diagnostics page is open, the app requests the original 54 ALL
message IDs plus an experimental raw B-CAN subscription for the i-MID audio
switch (`0x12F95757`, eight bytes), at a one-second interval. **Raw / status**
shows that frame's latest bytes and counts if the radio forwards it.
For a capture, hold wheel VOL− and VOL+ separately for about two seconds,
with idle time between them, then compare with the front-panel buttons.
Short taps can fall between samples. The firmware identifies the frame,
but the button values and live forwarding are still unverified. It also subscribes to the
original diagnostic receive presets. Diagnostic snapshots are logged separately
and never replace normal live readings. This feature sends subscription settings
and diagnostic receipt acknowledgments only. Entries named Reset, Request or
Change describe flags received from the car; selecting them does not perform
that operation.

Values are converted using the native SDK bit layouts, signedness, factors and
offsets. RPM is already displayed in rpm and coolant/outside temperature in °C;
no user conversion is needed. Vehicle speed uses km/h here. Boolean entries show True/False. A value whose unit
has not been established says **unit not confirmed** in its detail view. Some
integer entries are status/enum codes rather than a physical measurement.

**Waiting** means no record for that API entry has arrived. It is distinct from
a received zero or False. **Stale** means the selected source was last received
more than five seconds ago. Alternative-source selection follows the original
SDK: the preferred source wins unless another source is over 30 seconds newer.
Disconnects clear readings, while recordings retain the previous evidence.

The radio must advertise CAN capability during the application handshake.
Available signals depend on the car, fitted equipment and head-unit forwarding.
The complete list is an inventory to test, not a claim that every entry is
supported by every vehicle. Intake temperature exists in the underlying CAN
layout but is outside the original 168-entry ALL subscription and is not shown
as a live reading by this test. Extra diagnostic field sets,
friendly enum descriptions and Helpnet data assembly remain separate work.

The OBD Gauges home tile requests only RPM, coolant temperature, accelerator
pedal position, intake air temperature, native-scaled barometric pressure and VTEC
status at a target 10 Hz. Barometric units remain unverified.
Intake and VTEC use extra fields from the underlying native CAN layouts.
BLE is inactive for gauges. Leaving both pages clears the telemetry subscription.
See the OBD plugin README for conversions, freshness and fullscreen controls.
