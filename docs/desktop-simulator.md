# Desktop simulator

The simulator runs HLauncher's actual `Launcher`, page renderers, touch handling,
parking gate and `PluginHost` on macOS. It replaces the radio display and hardware
peers, rather than maintaining a second implementation of the UI.

## Open the Mac app

From a checkout, run:

```sh
./scripts/run_desktop_simulator.sh
```

This creates `.venv-simulator` when needed, installs its Python dependencies,
builds `build/HLauncher Simulator.app` and opens it. Building the native wrapper
requires Apple's command-line developer tools (`swiftc`). The generated app is
not committed; its Swift source and build script are in the repository.

For a Python environment that already has Pillow, NumPy and cryptography:

```sh
HLAUNCHER_SIMULATOR_PYTHON="$(command -v python3)" ./scripts/run_desktop_simulator.sh
```

The native wrapper uses the live checkout and the selected Python interpreter.
After saving Python changes, press **Command-R** or choose **Reload Python UI**
from the app menu. This restarts only the simulator backend. Rebuild the app
when changing its Swift wrapper or moving the checkout/interpreter.

## Test a flow

- Click the radio screen; click and drag to swipe pages or scroll lists. Hold a
  Home tile to enter the real layout editor. The shortcuts below the screen are
  optional; normal launcher navigation remains available.
- Change **Parking brake** and **Speed** to exercise the real Settings/plugin
  parking gate. Unknown brake telemetry follows the application's current
  behavior. Radio disconnection also uses the real session transition.
- Select a dual-protocol dongle, a CarPlay-only dongle, or no dongle. Choose
  wireless CarPlay, Android Auto through the dongle, or direct USB Android Auto.
  The real Phone Projection tile, waiting page, settings, phone history and
  favorite/phone-selection controls use simulated peer reports.
- A CarPlay-only adapter does not report a connected dongle AA session. Direct
  USB AA remains a separate selectable source. Disable **Show phone display**
  to exercise a connected phone whose display has not arrived yet.
- The Vehicle plugin uses its real Python `Dashboard` in-process. It receives
  the same host messages as the Pi worker, with simulated speed/brake telemetry;
  other signals remain unknown until a scenario supplies them.
- Choose update states to inspect idle, available, beta, busy and failure views.
  Checks, installation and restore actions update simulated status only.
- Use the steering buttons to test production input/host routing. The simulated
  peer acknowledges them in the event log. **Save screenshot** exports the
  current 720 × 480 radio frame.

The phone screen is explicitly labelled as simulated. This does not implement
Apple/Google projection video, USB dongle protocols, Bluetooth transport, audio
DSP/timing, HDMI negotiation, boot performance or actual installs/restarts.
Those still need hardware testing. Shutdown/restart controls record a simulated
request and leave the Mac running.

## State and isolation

Simulator preferences, EQ presets, phone history, captures and scenario controls
are stored separately under:

```text
~/Library/Application Support/HLauncher Simulator
```

Preferences and scenarios survive backend reloads. Use a separate directory for
an independent test profile:

```sh
python3 -m tools.desktop_simulator --state-dir /tmp/hlauncher-test-profile
```

Start the module from the checkout root. It prints a loopback-only URL that can
also be opened in a browser, without the native wrapper. Each server run uses a
random token; requests without it are rejected. HTTP mutations and UI ticks run
on one thread so input and drawing remain ordered.

Hardware substitutes are installed only in this dedicated developer process.
They block external process execution and outbound connection attempts, disable
hardware observers, and use an in-process worker peer. Pi startup never imports
these modules, and the installed updater's system contract is unchanged.

## Checks

```sh
python3 -m tools.desktop_simulator --self-test
PYTHONPATH=tests python3 -m unittest test_desktop_simulator
```

The first command needs no window or listening socket and uses temporary state.
It checks real navigation, parking transitions, projection routing, steering
acknowledgements, the Vehicle dashboard, HDMI test rendering and the process
launch guard. The second also checks the loopback API, token rejection, real UI
frames and input-driven state changes.
