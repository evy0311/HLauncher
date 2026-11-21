# Radio-style UI

Every built-in launcher page now uses the shared stock-era header, typography,
backgrounds and controls, including System, network setup, storage, plugins,
picture calibration, diagnostics, hardware tests, shutdown and first pairing.
Phone-provided projection keeps its full-screen viewport. The global Picture controls also apply to projection video.

- `hlauncher/ui/home.py` lays out the header, clock, enabled apps and
  Settings, and returns touch regions to the existing input handler.
- `hlauncher/ui/home_art.py` owns fading mirror reflections, gradient surfaces,
  fine bevels and themed background illumination. `home_icons.py` fits the
  approved white phone, gauge, Civic Si sedan and settings artwork. The saved
  coupe variant is retained for future use. It also fits the colored projection
  logos and draws auxiliary glyphs.
  Artwork is cached. Tiles stay still in Home edit mode until dragged.
- `hlauncher/ui/assets/fonts/` bundles Noto Sans JP at Bold (700) for tile labels,
  with its OFL license and source checksum. Barlow Condensed SemiBold remains
  the clock face, and existing Roboto remains the header face. Noto Sans JP is
  a visual approximation of the factory Gothic lettering, not the OEM font.
  Labels use a 26 px nominal size with 84% horizontal scaling, tuned against
  the photographed stock labels and the 720→800 px display stretch. Their
  artwork is supersampled and cached; the OEM's exact point size is unknown.

No radio firmware assets or fonts are used. The approved mockups are visual
references; their generated text and backgrounds are not baked into the UI.

The canonical layout is 720×480, with 196×176 tiles at x=46/262/478 and y=80/276.
The grid has 28 pixels of space above and below it, measured below the header.
Icons use an 80-pixel canvas; reflections fade out before captions. Tiles follow
your finger as you swipe between pages. You can also tap a bar below the tiles
to change pages. The active page bar is brighter.
Touch regions scale with the displayed image on other framebuffer dimensions.
On a fresh layout, CarPlay appears first, then the remaining enabled plugins and
Settings. Each page has six slots. Hold a tile to edit Home. Drag tiles into
empty slots or onto another tile to swap positions. Hold a dragged tile at either
edge to turn the page. Every Home theme supports swiping and adds pages as needed
for enabled apps. Use **+ Page** to keep up to two spare pages for arranging tiles.
On the page you want to remove, choose **Delete page** in edit mode. Its apps move
to open slots on other pages. A page can be deleted when all enabled apps fit
on the remaining pages. On an empty page, tap **Edit Home** to open edit mode.
Use **Done** to leave edit mode. Layout changes are saved as you make them. Settings can move to
any slot. Use a plugin's corner button to disable it or uninstall a plugin you
installed yourself.
Long external-plugin labels shrink and ellipsize rather than overlap.

Settings → Appearance → Background color offers Blue, Red, Green, Amber,
Purple or Graphite. The migrated screens map these names to the shared stock-style accent palette. All tile gradients, edges, tab
color and background illumination derive from that accent. Icon colors stay
consistent when switching themes: CarPlay stays green, Android Auto
stays blue when connected; the disconnected phone, gauge, Vehicle and Settings
icons remain white. The EQ retains its instrument colors. The header has a Wi-Fi icon at the far right, moving left of the optional
clock. One to four lit signal marks show connected signal strength; an × means
disconnected, a slash means the radio is off, and ? means telemetry is unavailable.
Status refreshes about every two seconds without scanning for networks. When enabled under Settings → Appearance → Show clock, the clock follows the
Pi's configured local timezone and updates once per minute. The OBD dashboard
refreshes its own cached header when the minute changes.

To capture the actual active RGB565 HDMI0 scanout on the Pi:

```bash
cd /opt/hlauncher
sudo python3 scripts/capture_display.py /tmp/hlauncher-screen.png
```

The capture tool reads the current DRM buffer without taking display ownership
or stopping HLauncher. It intentionally requires root and does not save images
automatically or expose them over the network.

## Projection connection pages

CarPlay and Android Auto use the same `ui/chrome.py` header as Home, including
its Wi-Fi status and minute-updating clock. The top-left tab shows a back arrow
on child pages; its scaled touch target returns directly to Home.
`ui/projection.py` renders each source's connection/status page using its
original colored icon, fading reflection, themed background and illuminated
status panel. Connection text comes from the plugin's real status messages.

The header applies only to launcher-owned connection pages. Phone-provided
CarPlay/Android Auto video remains full-screen, with its original viewport and
touch coordinates. No clock redraw can cover live projection. The shared header never overlays phone-provided video.

## Main Settings menu

`ui/settings.py` renders the root Settings menu with the same shared header and
Home-return button. Six 44 px bars use the tile gradients and beveled outlines;
labels stay on the left, descriptions/current values on the right. Existing
plugin, OBD, theme, default-app, audio and System callbacks remain core-owned.
The clock updates while this page is open. All child settings and diagnostics screens use the same shared UI controls.


## Audio and OBD pages

The Audio settings page provides the equalizer and saved presets. The bundled OBD dashboard shares
the UI artwork and typography and uses vehicle data from HondaLink. Missing or disconnected readings
remain unavailable, and the dashboard caches its header until the minute or
pressed state changes.


## Setup wizard

All six onboarding steps use the common theme, typography, 52 px header and clock.
The Welcome page has the Home-style grid tab; subsequent steps use the header's
return button to go to the previous step. App choices, startup selection, theme
previews and navigation use the shared tile surfaces. The wizard keeps its
resumable preference writes and guarded storage-protection behavior. Repeated
helper text and save-status footers are omitted; adapter requirements and
network credentials remain visible where needed. Screenshots
use temporary preferences and demonstration Wi-Fi credentials.


## Secondary settings and diagnostics

`ui/pages.py` owns the System menu, network and hotspot pages, storage confirmation,
picture and HDMI controls, shutdown and the generic app waiting screen.
`ui/plugins.py` handles external plugin installation and management.
`ui/color_picker.py` renders the custom theme picker. `ui/diagnostics.py`
renders system diagnostics and delegates the Vehicle data and Integration tabs. Raw calibration patches retain exact
RGB values while their header uses the normal shared rendering.

The completed setup wizard can be reopened without clearing setup completion.
It has Exit on every step when opened from Settings. Choices remain saved and
Exit returns to System. First-time setup still requires completion. Network
setup is a separate child flow and Back returns to the wizard's Network step.

The Wi-Fi menu shows the Pi's current LAN setup address and opens Wi-Fi power,
setup hotspot and SSH access. The hotspot
page shows the Wi-Fi password and recovery address. The web page opens without a login.
The radio has a separate SSH access page. NetworkManager sampling happens
in the recovery worker, not in the UI/audio loop. The recovery
website shares the theme and separates Wi-Fi, local update, pairing and support.
Storage restart is offered only after the protection job has completed.


## Settings categories and early welcome

Settings uses two columns of rectangular category bars: Plugins / About,
Audio / Startup, and Appearance / System. Diagnostics lives under System → Debug
(enable Debug mode in System to show the menu). About shows the project logo, version, creator,
GitHub address and the Legal info button. Child lists use the shared horizontal
color wash with inset values or Off/On controls. Appearance contains background
color, clock visibility and global Picture controls; individual plugin pages contain their enable switch and plugin options
(such as the CarPlay adapter icon); Startup contains the default app selector.

The early HDMI welcome and wizard Welcome share their content and theme. The
screen remains available while a saved radio reconnects; Bluetooth profiles
still register before the display is loaded. Fresh preferences default to Red;
saved theme choices are retained.


## Custom theme

For complete layout changes, see [Layout themes](themes.md).

The six preset colors remain fixed. Settings → Appearance → Background color
and the wizard’s Appearance step also offer Custom color. The native touch
picker previews the shared chrome and tile while editing: hue/saturation wheel,
brightness, RGB sliders and a six-digit hex keypad. Save color writes the chosen
hex code and retained custom swatch through the normal atomic preferences store;
Cancel leaves settings untouched. Picking a preset later retains the last custom
color. The saved hex color is used by launcher pages, boot welcome, projection
shell, OBD dashboard and recovery website. Icon and text colors are unchanged.
First-run setup never shows Exit, including after returning from the picker;
Exit is available only when completed setup is reopened from Settings.


The active theme also colors launcher controls and dialogs, the parked screen,
Vehicle and the bundled projection connection pages. Once CarPlay or Android
Auto is connected, the phone draws its own interface. The projection
day/night settings still apply there.
