# Android Auto

A wired Android Auto plugin using OpenAuto and aasdk. Connect the Android phone
directly to a USB host port on the Pi; no Carlinkit dongle is involved. The Pi's
HDMI output and HondaLink Bluetooth control connection remain the same as for
CarPlay. Android Auto is confirmed working on the project setup.

## Install the engine

Release images already include the engine. This build is only needed for source
installations. Enable the plugin under **Settings → Plugins → Android Auto**.

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

Honda radio buttons, music, guidance, call audio and microphone audio use the
same HLauncher paths as CarPlay. The phone supplies track metadata, which the
shared Bluetooth AVRCP target can show on the radio. The wired phone still owns
the call and navigation; the Pi bridges the audio and controls.

Auto day/night mode uses HLauncher's HondaLink illumination signal. Android Auto
also gets speed and the parking brake state when the radio reports them. Driving
restrictions stay on unless the brake is set and fresh speed reads zero.
Enable **Use car built-in GPS** on the Android Auto plugin page to advertise
location and send fresh HondaLink coordinates when the phone subscribes.
The phone still decides how to use those coordinates. Wireless Android Auto
is outside this integration.
The default discovery profile uses the original seven channels for phone
compatibility. The optional extended telephony, media status and driving sensor
profile is available for testing with `HLAUNCHER_AA_EXTENDED_SERVICES=1`.

CarPlay and Android Auto share an exclusive projection lease. Selecting the other
plugin stops the previous session and waits for USB release; automatic CarPlay
startup does not take over a running Android Auto session.

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
inferred from a generic phone error.

`/opt/hlauncher-deps/bin/hlauncher-android-auto --check-discovery` checks that
legacy identity fields are explicitly populated. It is an offline descriptor
check, not proof of phone compatibility.

A second Android 11 test confirmed that adding legacy identity did not resolve
error 2. The response still contained only five endpoints. The next correction
adds OpenAuto's microphone source and a small session sensor service (seven
unique channels total). It does not start an HFP call or reconfigure Bluetooth.
`--check-services` constructs the actual service factory without USB/Bluetooth,
and verifies unique IDs, microphone format, sensor types, video/audio and touch
geometry. The owner subsequently confirmed Android Auto working on the project setup.

Use `--check-driving-policy` to verify the parked, moving, and unknown cases
without a radio or phone.
