# Vehicle

Vehicle is installed and enabled by default. Open it from Home. It uses the
active HLauncher theme and requests vehicle data from the legacy HondaLink
session when opened. Vehicle requires both the parking brake and a fresh
zero-speed reading. If either is lost, the worker closes and the shared parking
screen offers Home or reopens Vehicle once both are confirmed.

- **Maintenance** shows engine oil life and instrument cluster service codes.
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

The four overview tabs use short headings and one status line. Maintenance
summary tiles appear only for received values, including legitimate zeroes.
Service descriptions, indicator details and raw report records remain available
on tap. Partial warning telemetry stays labelled incomplete.

UI polish used [unslop by Damir Sokolovsky (@heydamir)](https://heydamir.design/unslop),
CC BY 4.0, while retaining HLauncher's radio theme and navigation.

Open **Settings → Plugins → Vehicle** to choose the groups and individual fields
shown in the plugin. Hide **Tires and TPMS** to remove the section while keeping
your individual choices saved. Visibility settings affect the display only.

Vehicle keeps the latest value received for each signal and the latest reports
per module in `/var/lib/hlauncher/vehicle-last-known.json`. The cache can be
viewed after a disconnect or reboot. It writes on the first reading, every
30 seconds during use, and when closing the session normally. Last updated
refers to the most recent sample in the cache. When the Pi has a synchronized
clock, it shows the sample date and time. Without a synchronized clock, it
shows elapsed time within this boot, or an unavailable date after reboot.

**Refresh data** asks the head unit to reapply the subscription. The request uses
the same one-second cyclic receive mode as HondaLink Connect. If the request
with optional diagnostic context fails to start the normal stream, Vehicle
retries once with the standard diagnostic presets and the same live signal mask.
Refresh does not clear the last received values. A dash means there is no value
in the cache for that field; zero and Off are actual reported values.

The request controls what the radio forwards; it cannot make a module produce
unavailable data or prove a missing warning is off. Forwarding depends on the
radio, vehicle equipment and operating conditions.
