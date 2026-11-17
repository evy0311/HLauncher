# Layout themes

On the radio, open **Settings → Appearance → Change theme**. When multiple themes
are installed, use **Previous** and **Next** to browse them. Switch between the **Home** and **Settings**
previews. Select **Use theme** to apply the previewed theme. The OEM theme uses
the original layouts and saved background color.

Themes with adjustable colors show a **Color** button in the preview and a color
setting in Appearance. Colors picked in a preview are saved when you select
**Use theme**.

**Touring** has large app tiles, a two-column Settings menu, and a fixed graphite
palette. **Drive** features the enabled app selected in Startup. If Startup is
set to Home, Drive features the first enabled app in the Home arrangement.
Its Home layout has a wide app button and shortcuts below it. Menus place the
title on the left and controls on the right. The bottom bar holds Back and the
optional clock in consistent positions. Drive uses a fixed black and deep-gray palette.

Both themes cover Home, Settings, Appearance, System, Wi-Fi, Startup, Plugins
and individual plugin settings. Other screens use OEM. Your enabled apps and
saved Home arrangement carry over. Swipe Home or use the page controls to see
more apps. Hold a Home item to open the shared editor, or tap **Edit Home** on an
empty page. In the editor, **Delete page** removes the current page and moves its
apps into open slots on the remaining pages.

## Create and use a custom theme

1. On the radio, open **Settings → System → Wi-Fi**. Open the address shown
   there from a phone or computer on the same network. You can also start the
   **Setup hotspot**, join it, and open `http://192.168.4.1:8080`.
   Sign in as `hlauncher` with the setup password.
2. Expand **Layout themes** and select **Download Touring starter** or
   **Download Drive starter**. The downloaded file already has a new ID and
   display name. Open it in any text editor and change the name, layouts,
   or colors. Try changing just one value first, such as `colors.accent`.
3. Choose your JSON file on the setup page and select **Import theme**.
   On the radio, reopen **Settings → Appearance → Change theme**, find your
   theme, preview it, and select **Use theme**.

To update your theme, keep the same `id` and import the file again. To keep
both versions, give the new one a different `id`. Download an installed theme
from the setup page to back it up or share it. Another user can import that file
using the same steps.

## Theme file reference

Use `format: 1`. The `id` must start with a lowercase letter and may contain up
to 32 lowercase letters, digits, and hyphens in total. `oem`, `touring`, and
`drive` belong to the bundled themes. The `name` is the label shown on the
radio and can contain up to 32 characters. Files can be up to 8 KiB.

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

| Screen | JSON key |
| --- | --- |
| Home | `home` |
| Settings | `settings` |
| Appearance | `appearance_settings` |
| System | `system_settings` |
| Wi-Fi | `recovery_settings` |
| Startup | `startup_settings` |
| Plugins | `plugins_settings` |
| Individual plugin settings | `plugin_detail` |

Choose at least one screen to customize. Omitted screens use OEM.
Touring uses `tiles` for Home, `categories` for Settings, and `menu` for
deeper pages. Drive uses `dock` for Home and `console` for menus.
You can also use `grid` for compact cards, `featured` for a large card with
shortcuts beside it, `rail` for rows beside a sidebar, or `list` for full-width rows.

Give all five color fields a six-digit hex value such as `"#213139"`.
`background` is the base surface, `panel` is the control surface, `accent`
highlights selected controls, `text` is the main label color, and `muted`
is for secondary labels. Check both previews for readability.
A theme uses its defined palette by default. Set the optional
`"supports_color_selection": true` field to let the user apply the saved theme
color to its accents. Older `grid`, `list`, and `rail` layouts also tint panels.

From a shell on the Pi, `python3 -m hlauncher.themes --help` shows the same copy
and install operations. Run it from `/opt/hlauncher` with access to the persistent
state folder.

Installed themes live under `/var/lib/hlauncher/themes`, alongside settings.
The app updater leaves this folder in place. If a selected theme is missing
or invalid, the launcher uses OEM.
