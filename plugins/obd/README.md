# OBD Gauges

Live coolant temperature (°F), oil temperature (°F), bank 1 long-term fuel trim
(%) and mass airflow (g/s). There is no simulated data in the running plugin.
Missing, unsupported or stale readings show a dash. When disconnected, the dials
are disabled and direct the user to Launcher Settings > OBD Gauges.

## Connect

Open **Settings > OBD Gauges > Scan**. The short BLE scan shows all
nearby BLE devices (apart from the radio); select your ELM327-compatible device.
The page shows discovery, connection, vehicle initialization and failure status.
Disconnect forgets the selected device. The saved device reconnects automatically
while the OBD service is running and the HondaLink control session is healthy.
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

Four complete circle dials, white Roboto readouts and units inside, labels below,
and a theme-colored marker on black. Display ranges are 100–260 °F coolant,
140–300 °F oil, −20 to +20% fuel trim and 0–100 g/s MAF. These are presentation
ranges, not diagnostic limits; the number is not clamped to the dial range.
The gauge worker closes when leaving; the launcher-owned connection can remain
available for reopening. Back returns to HLauncher. Radio control and audio
remain owned by the launcher.

## Verification

`python3 -m unittest discover -s tests -p test_obd.py` exercises parsing, freshness,
radio-loss cancellation and a complete simulated BLE/ELM exchange. This does not
replace testing the user's actual dongle and vehicle. `scripts/check_obd.py`
checks isolated rendering and Back/close behavior without any adapter connection.
