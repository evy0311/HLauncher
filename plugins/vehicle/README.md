# Vehicle

Vehicle is installed and enabled by default. Open it from Home. It uses the
active HLauncher theme and reads the legacy HondaLink session while the page is
open.

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

Vehicle uses receive-only HondaLink subscriptions. The new diagnostic and
Maintenance Minder views can be tested with synthetic frames. Forwarding of
particular records and their units still depends on the in-car radio.
