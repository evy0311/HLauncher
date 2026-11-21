# Vehicle

Vehicle is installed and enabled by default. Open it from Home. It uses the
active HLauncher theme and requests vehicle data from the legacy HondaLink
session when opened. Vehicle requires both the parking brake and a fresh
zero-speed reading. If either is lost, the worker closes and the shared parking
screen offers Home or reopens Vehicle once both are confirmed.

- **Maintenance** shows cluster oil life and instrument cluster service codes.
  Both cluster and engine oil-life inputs are codes, converted using the original
  HondaLink Connect mapping. The dial prefers the cluster source and falls back
  to the engine source. Both are independently visible in Readings.
  Tap a code for its service description or open the full guide. Definitions
  come from the [2014 Honda Civic Sedan Owner’s Manual, p. 359](https://techinfo.honda.com/rjanisis/pubs/OM/R0144D/R0144DOM.pdf)
  for models with i-MID. Refer to the manual for your model if it reports a
  code that this guide does not cover.
- **Health** shows reported warning indicators and tire data. Available
  readings vary by model, equipment and head unit.
- **Diagnostics** shows fault code reports for body and powertrain networks,
  plus freeze frames. The page decodes known code fields and makes the
  received records available for inspection.
- **Readings** includes all 168 legacy vehicle API fields and additional
  recovered readings, including raw interval and cluster codes. Raw values
  are shown where a unit or code mapping is still unknown.

The four overview tabs use short headings and show connection status only when
needed, without a last-refreshed timestamp. Maintenance
summary reserves tiles for odometer and Minder interval, showing **Not received**
until readings arrive. Odometer uses the F-CAN source or its separate B-CAN
cluster alternative. Minder interval, engine oil-life distance and both
odometers retain native values labelled raw until their units are verified.
Legitimate zeroes remain visible.
Service descriptions, indicator details and raw report records remain available
on tap. Partial warning telemetry stays labelled incomplete.

UI polish used [unslop by Damir Sokolovsky (@heydamir)](https://heydamir.design/unslop),
CC BY 4.0, while retaining HLauncher's radio theme and navigation.

Open **Settings → Plugins → Vehicle** to choose the groups and individual fields
shown in the plugin. Hide **Tires and TPMS** to remove the section while keeping
your individual choices saved. Visibility settings affect the display only.

Vehicle keeps the latest value received for each signal and the latest reports
per module in `/var/lib/hlauncher/vehicle-last-known.json`. Gauges, radio status
and full diagnostics also populate this cache, which can be viewed after a
disconnect or reboot. It writes on the first reading, every
30 seconds during use, and when closing the session normally. The cache retains
the most recent sample time even though the dashboard does not display it.

**Refresh data** asks the head unit to reapply the subscription. The request uses
the same one-second cyclic receive mode and standard diagnostic presets as
HondaLink Connect. Every original source and mask bit is included, with extra
bits from the native layouts for the additional fields shown on the page.
If rejected, the settings reply is missing, or no sensor values arrive, one retry uses the exact
original SDK ALL masks. Extra fields excluded by that retry say **Not requested**
when no saved value exists. A requested field with no saved value says
**Not received**. This does not prove a field is unsupported by the radio.
VIN-only traffic does not count as a sensor reading. Refresh preserves saved
values; zero and Off require actual received field bytes.

The request controls what the radio forwards; it cannot make a module produce
unavailable data or prove a missing warning is off. Forwarding depends on the
radio, vehicle equipment and operating conditions.
