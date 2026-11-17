# OBD Gauges

The Home tile shows **Coming soon**. The gauge renderer and BLE adapter code
remain in the repository for development.

The renderer supports engine RPM, coolant temperature (°F), accelerator pedal position (%),
intake air temperature (°F), barometric pressure (native units), and VTEC ON/OFF.
Missing, unsupported or stale readings show a dash; received zero remains zero.
All six use HondaLink. BLE code is retained for adapter tools but is inactive
on this page. Barometric pressure units still need vehicle verification.

The head-unit subscription follows the visible consumer:
- Gauges: only the six displayed fields, across CAN IDs 0x17C, 0x320, 0x324,
  0x454, 0x12F85050 and 0x12F85150, with signal-specific masks.
  No VIN, location, DTC or freeze-frame presets are requested in gauge mode.
- Vehicle-data diagnostics: original full 168-entry subscription, at one second.
- Other pages: no telemetry subscription; leaving a consumer sends an empty
  receive-settings list to clear the previous subscription.

Gauge mode targets a 100 ms interval (10 Hz). The requested interval does not
establish the radio's achieved rate; received timestamps remain the evidence.
Gauge snapshots are handed off at up to 30 Hz only on this page.
The renderer targets 30 FPS. RPM eases toward received targets with a 25 ms response constant; other
needles use 60 ms; displayed numbers remain the latest actual sample. There is
no extrapolation. Missing/stale readings are cleared immediately.

Coolant and intake temperature are converted from °C to °F. RPM needs no
further conversion. Accelerator pedal position uses native API 167, scaled to percent; this is
pedal position, not throttle-plate angle. Barometric pressure uses the native
SDK scaling with unconfirmed units.
VTEC uses ENG_VTEC_STATUS as a boolean. Intake and VTEC extend the original
168-entry API using its underlying CAN layouts. The renderer receives a small
read-only in-memory snapshot over existing local IPC.

The host handoff expires after one second without a heartbeat. Individual
HondaLink samples expire after five seconds and clear on disconnect/session
close. An older diagnostic snapshot never replaces a normal live gauge value.

## BLE adapter development

The BLE service can scan for nearby adapters and save or forget the selected device.
The saved device reconnects while the OBD service is running and the HondaLink
control session is healthy.
BLE devices requiring a vendor-specific GATT protocol may need an additional
transport profile. Classic-only Bluetooth ELM327 devices are not supported here.

The current transport recognizes FFE0/FFE1 UART, Nordic UART, and FFF0 with FFF2
write / FFF1 notify. Unknown layouts are logged and rejected instead of writing
to arbitrary characteristics. BLE normally does not need a PIN; adapters requiring
interactive authentication are not handled by this screen yet.

## Radio priority

Bluetooth work runs in a separate launcher-owned process, not inside the gauge
renderer or radio event loop. It never changes adapter power, pairing records,
radio profiles or Bluetooth services. A verified HondaLink control session must
be stable for five seconds before any BLE discovery or connection begins.
A lost session or a three-second expired launcher heartbeat cancels OBD work and
releases only the OBD connection. Scans last four seconds; failed connections
retry no more frequently than every 30 seconds. Polling is serialized with idle
gaps. These rules prioritize reconnecting the radio; they cannot reserve hardware
airtime or guarantee that one shared Bluetooth controller never interferes.

Only adapter configuration and Mode 01 data requests are allowed. Supported-PID
bitmaps determine which gauges are polled. No fault clearing, coding or ECU write
operations are exposed. Each value expires after five seconds; the whole status
expires after four seconds without a worker heartbeat. A timed-out ELM response
ends that session so a late response cannot become another PID's reading.

Logs rotate at `/var/log/hlauncher/obd-ble.log` (2 MB plus two backups).
Connection selection and state live under `/var/lib/hlauncher/obd/`.
The renderer consumes the SDK's read-only snapshot; it has no Bluetooth access.

## Display

Six complete circle dials, white Roboto readouts and units inside, labels below,
and a theme-colored marker on black. The title, live-count, source captions and
update footer are hidden to give the dials more space. Tap the top-right expand
button for fullscreen. Fullscreen hides the header and minimize button. Tap the
screen to show or hide the minimize button; press that button to restore the
smaller gauges, header and Back button. There is no timed auto-hide.
 Display ranges are 0–8,000 rpm, 40–260 °F coolant, 0–100% accelerator pedal,
−40–200 °F intake and 0–800 native barometric pressure. These are presentation
ranges, not diagnostic limits; numbers are not clamped to the dial range.
The gauge worker closes when leaving; the launcher-owned connection can remain
available for reopening. Back returns to HLauncher. Radio control and audio
remain owned by the launcher.

## Verification

`python3 -m unittest discover -s tests -p test_obd.py` exercises parsing, freshness,
radio-loss cancellation and a complete simulated BLE/ELM exchange. This does not
replace testing the user's actual dongle and vehicle. `scripts/check_obd.py`
checks isolated rendering and Back/close behavior without any adapter connection.
