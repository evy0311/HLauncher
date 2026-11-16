# Connection outline

The launcher implements the phone side of the older Bluetooth HondaLink path.

See [legacy HondaLink capabilities and extension roadmap](hondalink-capabilities.md)
for findings from the recovered Connect native SDK: call and navigation handoff,
clock correction, voice notices, meter guidance, telemetry, and the remaining
work before exposing these through plugins. Recovered payload formats and
vehicle-tested features are identified separately. The [meter-guidance trace](meter-guidance.md)
records the outgoing display/text-data family and the stock Civic parser gates
that currently prevent using it through the recovered HondaLink sender.
The [i-MID Apps audio investigation](imid-audio.md) separates Connect audio
state, firmware AppMode status, AVRCP metadata and HLauncher source-only labels.

The listener registers an authenticated serial profile on RFCOMM channel 10 and the Honda control profile `00000000-deca-fade-deca-deafdecacafe` on channel 11. The listener accepts the saved HandsFreeLink peer. During first enrollment it accepts the admitted, paired candidate.

`hlauncher/protocol/session.py` handles framing, identification, the radio's accessory-key challenge, application launch requests and the Honda general/HondaLink sessions. `hlauncher/protocol/frames.py` handles the nested Honda messages. The app identifiers are kept as the radio expects them: `com.honda.hondalink.launcher` and `com.honda.hondalink.connect`. The Pi's own model and serial are used for device information.

The authentication helper checks that the radio can sign a challenge using a key from its supplied certificate. Certificate preparation and signature checks run in a worker thread. It does not implement Apple certificate-chain policy validation or make the Pi a certified Apple device.

Video goes over HDMI. Honda touch messages travel back over the control connection, are decoded in `hlauncher/touch.py`, and are routed either to the launcher or to the active projection worker. Both Honda contact slots are retained through the plugin API. The CarPlay adapter uses a stable two-slot multi-touch stream for both one- and two-finger gestures, retaining the first contact when the second is added.

CarPlay's Honda icon produces a node-CarPlay host-UI request. The bridge exposes it as `host_ui_requested`, and the launcher returns to its home page while retaining the dongle session.

The microphone capture API uses BlueALSA's HFP PCM source. CarPlay and Android
Auto request capture for their active voice sessions. Bench testing found that
opening the PCM source alone could yield silence until hands-free call state
enabled the radio mic. End-to-end behavior depends on the radio and phone.
[Projection voice and microphone](plugins.md#projection-voice-and-microphone)
