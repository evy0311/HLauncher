# Home artwork

User-approved generated previews, preserved without changes. The renderer uses
their white ink as opacity so the dark preview background does not cover themed
tiles. It fits each shape inside the same icon box without stretching it.

- `phone-projection.png`: disconnected Phone Projection.
- `obd.png`: OBD Gauges.
- `vehicle-sedan.png`: default Vehicle icon, 2014 Honda Civic Si sedan.
- `settings.png`: Settings.
- `vehicle-coupe.png`: approved 2014 Civic Si coupe variant, used for FG3/FG4.

Appearance → Vehicle Model selects the artwork. HondaLink VIN detection chooses
the matching Civic variant and persists it. A manual override survives reboots
with the same VIN; receiving a different VIN triggers detection again. Both car
profiles render 25% larger than the other icon boxes for balanced visual weight.

Connected projection continues to use the existing CarPlay or Android Auto logo.

Polish direction: unslop by Damir Sokolovsky (@heydamir), CC BY 4.0,
https://heydamir.design/unslop. No Honda firmware artwork is used.
