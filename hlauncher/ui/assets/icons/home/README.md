# Home artwork

User-approved generated previews, preserved without changes. The renderer uses
their white ink as opacity so the dark preview background does not cover themed
tiles. It fits each shape inside the same icon box without stretching it.

- `phone-projection.png`: disconnected Phone Projection.
- `obd.png`: OBD Gauges.
- `vehicle-sedan.png`: default Vehicle icon, 2014 Honda Civic Si sedan.
- `settings.png`: Settings.
- `vehicle-coupe.png`: approved 2014 Civic Si coupe variant, used for FG3/FG4.
- `vehicle-crv.png`: 2014 CR-V, used for RM3/RM4 (FWD/AWD).
- `vehicle-hrv.png`: RU-generation HR-V, used for RU5/RU6 (FWD/AWD).
- `vehicle-fit-ge8.png`: 2013 Fit, used for GE8.
- `vehicle-fit-gk5.png`: 2015 Fit, used for GK5.

Appearance → Vehicle Model selects the artwork. HondaLink VIN detection chooses
the matching model and persists it. A manual override survives reboots
with the same VIN; receiving a different VIN triggers detection again. Vehicle
profiles render 25% larger than the other icon boxes for balanced visual weight.

The SUV manufacturer prefixes are documented in Honda's NHTSA Part 565 filing:
https://vpic.nhtsa.dot.gov/mid/home/displayfile/69a24a5d-780c-4562-b28c-5eaf08531280.
The HR-V artwork follows the requested RU5/RU6 generation; its North American
introduction used the 2016 model year. Fit year labels identify the reference
generation, rather than limiting VIN detection to a single model year.

Connected projection continues to use the existing CarPlay or Android Auto logo.

Polish direction: unslop by Damir Sokolovsky (@heydamir), CC BY 4.0,
https://heydamir.design/unslop. No Honda firmware artwork is used.
