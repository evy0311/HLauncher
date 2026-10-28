# Android Auto

A wired Android Auto plugin using OpenAuto and aasdk. Connect the Android phone
directly to a USB host port on the Pi; no Carlinkit dongle is involved. The Pi's
HDMI output and HondaLink Bluetooth control connection remain the same as for
CarPlay. This first integration is experimental until tested with a real phone.

## Install the engine

From the HLauncher checkout on Raspberry Pi OS Bookworm (64-bit):

```bash
sudo bash scripts/install_android_auto.sh
```

This fetches pinned OpenAuto/aasdk source into `/opt/hlauncher-deps/src`, applies
the tracked HLauncher patch, and builds outside this repository. The first build
can take a while. It does not install Crankshaft, replace the OS, change the radio
firmware, restart Bluetooth, or take over HDMI. Reopen the plugin after building.
The main HLauncher installer prepares CarPlay; this additional build is optional
for people who want Android Auto.

## Integration

The isolated native process handles USB accessory negotiation, Android Auto
transport, H.264, stereo music, mono guidance/system audio, and two-contact input.
The Python plugin feeds HLauncher's shared decoder, audio broker and frame slots.
Android Auto advertises 800×480 at 60fps; negotiated frame rate still depends on
the phone. HLauncher scales the video to the Pi's working HDMI mode.

Return to the launcher using Android Auto's native/exit-to-car display action.
HLauncher's Back button remains available on the waiting/error screen. Background
mode keeps the session and audio running while avoiding RGB conversion when
hidden. Background mode is always enabled for CarPlay and Android Auto; there is no user toggle. Selection as
the startup/default plugin also uses the existing launcher settings.

This version does not implement wireless pairing, microphone capture, phone-call
routing or live vehicle sensor data. Its microphone transport is advertised and
can open, but capture requests explicitly fail as unavailable. The session sensor
endpoint currently reports a fixed parked bench policy and a default day display
appearance. It does not synthesize parking, GPS or
speed information.
Those require separate integration and testing. CarPlay and Android Auto should
not both be playing media simultaneously; the launcher currently mixes the
submitted audio streams rather than coordinating exclusive phone audio focus.

## Logs and checks

```bash
/opt/hlauncher-deps/bin/hlauncher-android-auto --check
sudo tail -f /var/log/hlauncher/plugins/android-auto/engine.log
sudo journalctl -u hlauncher -f
```

The native engine logs USB discovery, handshake and media-channel activity. The
plugin health records count video packets, rendered frames and dropped audio.
`--check` confirms the binary can load and reports its configured capabilities;
it does not prove a phone has connected. Engine failure stays inside the plugin.

OpenAuto/aasdk retain their GPL notices. See `THIRD_PARTY_NOTICES.md` and the
fetch/build script for exact source revisions and corresponding build changes.

## Older-phone discovery compatibility

The adapter supplies the legacy top-level identity fields (protobuf tags 2–11)
as well as the newer HeadUnitInfo block. This fixes an omitted legacy identity
in the initial integration. The correction was prompted by an Android 11 phone
reporting Communication error 2 after completing TLS and receiving service
discovery; the phone must be retested to confirm acceptance. The full outbound
service description is logged so subsequent rejection can be traced instead of
inferred from a generic phone error. Microphone and vehicle sensor integration
remain separate work; this correction does not fabricate either data source.

`/opt/hlauncher-deps/bin/hlauncher-android-auto --check-discovery` checks that
legacy identity fields are explicitly populated. It is an offline descriptor
check, not proof of phone compatibility.

A second Android 11 test confirmed that adding legacy identity did not resolve
error 2. The response still contained only five endpoints. The next correction
adds OpenAuto's microphone source and a small session sensor service (seven
unique channels total). It does not start an HFP call or reconfigure Bluetooth.
`--check-services` constructs the actual service factory without USB/Bluetooth,
and verifies unique IDs, microphone format, sensor types, video/audio and touch
geometry. Actual phone acceptance remains a hardware test.

## Bench parking state

This bench build hard-codes Android Auto driving status to `0` (unrestricted)
in `SessionSensors::drivingPolicy()`, at the owner's request. It has no timer,
configuration flag or setup command and persists across restarts and reboots.
This is a fixed bench value, not a measurement of the vehicle's parking state.
The sensor log identifies it as `hard-coded parked bench mode`.

`/opt/hlauncher-deps/bin/hlauncher-android-auto --check-driving-policy` reports
the compiled-in value. Actual vehicle-state integration is future work.
