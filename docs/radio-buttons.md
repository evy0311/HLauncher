# Radio controls

HLauncher receives iAP Simple Remote and AVRCP track controls and HFP phone/voice commands from the
configured paired radio and forwards each action to one running projection app.
HDMI remains the media output. Enable Debug mode, then open Settings → System → Diagnostics → Hardware tests →
Radio buttons shows transport status, received counts, source and forwarding
results. The six Test controls test the projection side even when the radio sends
nothing. A USB or Android Auto send result confirms submission, not that the
phone performed the requested action.

The November 6 car recording established the HondaLink track path: Simple Remote
lingo 2, ContextButtonStatus command 0, with a two-byte transaction followed by
one to four button-state bytes. These were previously logged as `iap_unhandled`.
The decoder now recognizes Next (first-bank 0x08), Previous (0x10), play/pause
(0x01), and second-bank play/pause (0x01/0x02). It emits state transitions, never
repeat commands for an unchanged held mask. This command requires no iAP reply.
Unknown bits are observed without guessing phone/voice actions.

These physical events appear as source `hondalink-iap` in the same RX counts and
CarPlay forwarding results as AVRCP. Authentication, valid framing/checksum and
bounded packet length are required. A new connection or identification sequence
advances the input epoch so a lost release cannot retain an old held key.

Vehicle RX counts exclude screen tests. The receive footer separately counts
AVRCP packets, HFP commands and non-touch HondaLink frames, including messages
which do not decode to a supported button. A packet count is not a button count.
Dial/redial appear under Dial / answer and in the last-action record, but remain
rejected on HFP rather than being reinterpreted as answer or dialing a number.
Unknown HFP observations retain command names only, with destinations withheld.
AVRCP observations retain header/operation identifiers, not metadata contents.

The stock steering-mode report is Honda message C1 with payload 00 01 64 MODE.
Its numeric value appears in diagnostics. It is not a physical key event, and
HLauncher does not transmit guessed mode-change requests. Value 0 was present in
saved in-car logs; the meaning of that value has not been established.

CarPlay explicitly subscribes to next/previous, play/pause, play, pause, stop
(pause), assistant, answer and end/reject and maps them to dongle commands.
Android Auto subscribes to the same set and submits the corresponding engine key codes. Held presses and duplicate commands within 180 ms are suppressed;
queued controls expire after one second. Releases never trigger a second action.
The pinned dongle has Siri activation only; voice deactivation clears held state.
Diagnostics distinguish plugin queueing, USB submission, failure and acknowledgement
timeout. The receiving plugin must
already be running; projection plugins stay running in the background when Settings opens.

Bluetooth's crashing AVRCP plugin remains excluded by 90-hlauncher.conf.
A separate Python process registers a basic AVRCP 1.3 target on PSM 0x17. It
accepts only the configured authenticated radio, reconnects its control channel
when the paired Bluetooth peer is connected, handles bounded single packets,
and supplies available title/artist/album/duration and play status. No browsing
channel or remote-player browsing is advertised or used. Its failure cannot
terminate bluetoothd; the input monitor restarts it. BlueALSA still owns A2DP/SCO.

Connection-audit update: outgoing AVRCP recovery now follows the authenticated,
trusted Bluetooth peer independently of hands-free state. The known AVRCP PSM
does not require BlueZ ServicesResolved, which can remain false on this radio.
Channel ownership is serialized; BlueZ loss invalidates in-flight connects.
Standard charset/battery setup reports and MTU-bounded metadata continuation are
handled. An idle bridge reports stopped; explicitly unknown active playback
remains unknown. Use scripts/check_avrcp_receiver.py for an isolated receive-path replay.

The same process opens BlueALSA's peer-specific RFCOMM dispatcher, leaving its
built-in negotiation and codec handlers alone. It handles BVRA, answer/end and
the Honda Siri extension sequence. Stock BlueALSA 4 lacks the voice capability
advertisement this radio checks. scripts/install_button_audio.sh builds pinned
BlueALSA 4.0.0 into /opt/hlauncher-deps/bluealsa-buttons; the small configuration
patch adds AG voice support, XAPL voice capability and the iPhone response name
required by the stock Honda parser. This identifies the compatibility proxy; it
does not change the Pi's Bluetooth device name. The distro binary is retained.
The build script itself does not restart services.

During CarPlay call audio, the Bluetooth HFP `AT+CLCC` query returns the active
call with caller details when the adapter provides them. When both the name and
number are unavailable, the optional name field carries **CarPlay Call**. The
radio decides which fields to display. The query returns an empty list when the
call ends. Dial and redial remain unsupported. The standalone microphone probe
cannot share the RFCOMM dispatcher with this control worker.

## In-car check

1. Start CarPlay, then return to Settings.
2. Open Radio buttons. Use Test Next/Previous and verify the playing track changes.
3. Press the physical track buttons. Compare counts and source with the screen test.
4. Hold the physical Talk button. Compare its voice event with Test Voice and verify
   assistant activation. Check microphone operation separately.
5. With a real incoming/active phone call, compare physical answer/end with the
   screen controls. Record whether the radio exposes the command or consumes it.

A missing physical event and a failed projection send are separate outcomes on
this page. No radio firmware, SD image, or pairing reset is required.

HondaLink profile registration is retried every two seconds after a Bluetooth
daemon restart. Losing BlueZ clears connected HondaLink sessions; the launcher
keeps running and advertises both profiles again when BlueZ returns.

## Receive-only capture

When the radio is connected, run from /opt/hlauncher:

```sh
sudo python3 scripts/capture_radio_controls.py --seconds 180
```

This saves a bounded local Bluetooth controller trace, live service logs and a
service/controller snapshot under captures/radio-controls-TIMESTAMP. It sends no
radio commands and stops its capture processes after the duration or Ctrl-C.
The files may contain phone information; they are private and ignored by Git.
The running Bluetooth stack continues its ordinary operation during capture.
Use --check to verify tools without starting a capture.

Start with HondaLink open, without needing CarPlay. Press Next, Previous, Talk
short, Talk long, Dial/Answer and End separately, noting the order and times.
Repeat track keys in Bluetooth Audio mode to establish whether routing changes
with the radio's selected source. Call-state-dependent behavior needs a later
real incoming/active call check; idle presses do not establish answer/end support.

## Phone compatibility

scripts/configure_phone_identity.py --apply persists Classic Bluetooth Class of
Device 0x00020c (smartphone) in /etc/bluetooth/main.conf and backs up the original.
It does not restart services or change pairing data. Existing service-class bits
are maintained by BlueZ; this Pi reports 0x0048020c with services registered.
The public alias remains HLauncher. HFP AG voice feature flags, the Apple XAPL
iPhone response/Siri capability and Honda Siri query handling are separate from
this classification. This is protocol compatibility, not complete iPhone emulation.

## Experimental native volume

Settings → System → Diagnostics → Hardware tests → Radio volume (experimental)
provides Volume down and Volume up. Each tap sends one AVRCP pass-through
press/release pair (`0x42` / `0x41`) to the paired head unit over its existing
control channel, with a two-second cooldown and no automatic retries. It does
not adjust the Pi mixer or phone gain. The page distinguishes radio acceptance,
rejection, unsupported commands, disconnection and a missing reply. If the
channel is closed, a tap requests an immediate connection attempt and reports
the Bluetooth prerequisite or socket error. One pending tap expires after five
seconds and is discarded on connection failure; it is never retried automatically. Acceptance
alone does not prove that the radio changed its native volume; watch the factory
volume display, including when HDMI is selected. Honda support is unverified.
