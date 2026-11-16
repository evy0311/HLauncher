# Layout themes

On the radio, open **Settings**, then press and hold **Appearance**. Select a
theme to preview it, then select **Use theme**. A normal tap still opens
Appearance. The OEM theme uses the original layouts and saved background color.

**Rail** places the title, Back button and clock in a left column. **Stack**
uses full-width rows. The new layouts cover Home, Settings, Appearance, System
and Wi-Fi. Other pages use the original renderer. Your enabled apps and Home
arrangement carry over. Hold a Home item to edit the arrangement in the shared
grid. In another layout, hold first and then drag from the grid.

## Make a theme

Open **Layout themes** on the Pi's local setup page. Download Rail or Stack as
a template, edit the JSON, then use **Import theme**. Reopen Themes on the radio
to preview and apply it. Give your theme its own lowercase ID and display name.
Importing a file with the same custom ID replaces that theme. You can download
your installed custom themes again from the setup page.

```json
{
  "format": 1,
  "id": "my-garage",
  "name": "My garage",
  "layouts": {
    "home": "grid",
    "settings": "rail",
    "appearance_settings": "list"
  },
  "colors": {
    "background": "#11191E",
    "panel": "#213139",
    "accent": "#82D4C4",
    "text": "#F4F8F6",
    "muted": "#A7BEC5"
  }
}
```

Use `grid`, `list`, or `rail` for any of the five supported screen keys.
The other keys are `system_settings` and `recovery_settings` (Wi-Fi).
Omitted screens use OEM. Theme files contain data only. Choose colors that
keep labels and focus outlines readable against their backgrounds.

From a shell on the Pi, `python3 -m hlauncher.themes --help` shows the same copy
and install operations. Run it from `/opt/hlauncher` with access to the persistent
state folder.

Installed themes live under `/var/lib/hlauncher/themes`, alongside settings.
The app updater leaves this folder in place. If a selected theme is missing
or invalid, the launcher uses OEM.
