# HondaLink vehicle data tests

Enable Debug mode, then open Settings → System → Diagnostics → HondaLink →
Vehicle data. Hardware tests → HondaLink vehicle data opens the same page.

- **All signals** lists the 168 legacy HondaLink vehicle API entries. Tap a row
  to inspect it. Drag the list or use its scrollbar and arrow buttons.
- **Selected signal** shows the converted value, freshness, selected CAN source,
  raw bytes and receipt/change counts. Previous/Next moves through the entries.
- **Raw / status** shows subscription progress, raw-record counts and the latest
  authentication/decryption error.
- **GPS** shows the current coordinate pair and its age. An incomplete pair is
  reported as invalid, and a valid fix is marked stale after three seconds.
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
offsets. RPM is already displayed in rpm and coolant temperature in °C;
no user conversion is needed. Outside-temperature API 77 retains its native
10-bit value with unconfirmed physical units; 1023 means unavailable in Connect.
Vehicle speed uses km/h here. Boolean entries show True/False. A value whose unit
has not been established says **unit not confirmed** in its detail view. Some
integer entries are status/enum codes rather than a physical measurement.

**Waiting** means no record for that API entry has arrived. It is distinct from
a received zero or False. **Stale** means the selected source was last received
more than five seconds ago. Alternative-source selection follows the original
SDK: the preferred source wins unless another source is over 30 seconds newer.
Disconnects clear live readings, while recordings retain the previous evidence.
The Vehicle tile retains per-radio last-known readings across disconnects and
restarts, including readings received in Gauges and full diagnostics. Missing
bytes in a partial record stay unknown; they do not become zero oil life or
False service-code flags.

The radio must advertise CAN capability during the application handshake.
Available signals depend on the car, fitted equipment and head-unit forwarding.
The complete list is an inventory to test, not a claim that every entry is
supported by every vehicle. Intake temperature exists in the underlying CAN
layout but is outside the original 168-entry ALL subscription and is not shown
as a live reading by this test. Extra diagnostic field sets,
friendly enum descriptions and Helpnet data assembly remain separate work.

The Vehicle home tile requests every source in the original 168-entry SDK ALL
inventory, plus 21 additional fields recovered from the same app's CAN layouts.
All 54 original message IDs, bus selectors and mask bits are preserved. Five
masks add the extra gauge/maintenance fields and the separate B-CAN cluster
odometer. It uses the original four-setting format and three standard diagnostic
receive presets, without optional CRM context. If rejected, the settings reply is missing, or no sensor values
arrive, one bounded retry restores the exact original SDK ALL masks. Readings
excluded by that compatibility retry say **Not requested** if no saved value
exists. A requested field without a saved reading says **Not received**, which
alone does not establish that the vehicle does not support it.

The oil-life dial prefers the cluster Minder code (API 72), then the engine
code (API 42). Connect applies its code conversion to both inputs: 1–9 mean
100–20%, 10–12 mean 15/10/5%, 13–14 mean 0%, and 0/15 are unavailable.
Readings shows each source's percentage and raw code independently. Invalid
engine codes are not interpreted directly as percentages.

Maintenance always reserves summary tiles for odometer and Minder interval.
Odometer prefers F-CAN API 75, then the separate B-CAN display-odometer field
(1009). Both remain separately available in Readings. The Minder interval (70)
uses the native raw-minus-9999 conversion. Engine oil-life distance (1005) is
also shown when received. Distance, interval type/unit codes and tire pressures
remain raw where their physical units have not been established; the dashboard
does not guess miles, kilometres, days or psi. A short six-byte Minder frame
can contain oil life and service flags without containing the date-unit or
additional applied-item bits. Missing bytes stay unknown.

The original request previously delivered live data on the Civic; that does
not establish delivery or validity of every individual field. Additional mask
bits and B-CAN odometer receipt still require a parked vehicle test. Alternative
sources use the original SDK preference and 30-second fallback rule. VIN-only
traffic does not suppress the single automatic sensor-data retry.

The tile requests its read-only batch on entry and offers
**Refresh data** to reissue it on the authenticated session. The original
Connect app configures a cyclic CAN subscription at startup
(`HLLpaCommunicator.init`, native address `0x63D7C`); its
`GetVehicleInfoArray` bridge reads the resulting native cache. The stock Civic
settings handler (`Communication.exe` `0xC4600`) checks permission on that
same application connection before forwarding the settings. A settings ACK
means the request was accepted; it does not guarantee records will arrive.
The protocol also defines a noncyclic mode. Vehicle refresh keeps the cyclic
mode so periodic readings, including the speed used by the parking gate,
continue after the request.

The OBD Gauges home tile requests RPM, coolant temperature, accelerator pedal
position, intake air temperature, native-scaled barometric pressure and VTEC
status at a target 10 Hz. Intake and VTEC use extra fields from the native CAN
layouts. The gauges use HondaLink. See the [OBD guide](../plugins/obd/README.md)
for conversions, freshness and fullscreen controls.

Projection adds its own read-only requests while a bundled worker is running.
**Follow headlights** uses the HondaLink illumination signal and is on by
default. **Use car built-in GPS** is off by default. With it on, both projection
workers can receive fresh coordinates and CarPlay can include fresh speed in
its NMEA fix. Android Auto receives speed and parking-brake state when
available. Those two readings expire independently after two seconds for
Android Auto's driving policy. A missing or stale reading keeps restrictions
in effect. The brake comes from a HondaLink radio status message with an
in-car test mapping. CarPlay parking-brake forwarding remains unverified.
[CarPlay vehicle data](../plugins/carplay/README.md#vehicle-data) ·
[Android Auto](../plugins/android-auto/README.md)

Outside full diagnostics, HLauncher combines the masks for active consumers
and clears the subscription when none remain. An active gauge or speed
request uses a 100 ms interval. Illumination or GPS alone uses a one-second
interval. These are requested intervals. Use receive timestamps to measure
what the radio actually delivers.
