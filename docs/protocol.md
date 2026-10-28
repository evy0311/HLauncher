# Connection outline

The launcher implements the phone side of the older Bluetooth HondaLink path. It is separate from the USB MirrorLink experiments.

The listener registers an authenticated serial profile on RFCOMM channel 10 and the Honda control profile `00000000-deca-fade-deca-deafdecacafe` on channel 11. The configured HandsFreeLink peer is the only accepted device.

`hlauncher/protocol/session.py` handles framing, identification, the radio's accessory-key challenge, application launch requests and the Honda general/HondaLink sessions. `hlauncher/protocol/frames.py` handles the nested Honda messages. The app identifiers are kept as the radio expects them: `com.honda.hondalink.launcher` and `com.honda.hondalink.connect`. The Pi's own model and serial are used for device information.

The authentication helper checks that the radio can sign a challenge using a key from its supplied certificate. It does not implement Apple certificate-chain policy validation or make the Pi a certified Apple device.

Video goes over HDMI. Honda touch messages travel back over the control connection, are decoded in `hlauncher/touch.py`, and are routed either to the launcher or to the CarPlay bridge. The current CarPlay input adapter forwards single-contact press/move/release events. Two-contact Honda messages are decoded, but pinch forwarding is not implemented in this baseline.

CarPlay's Honda icon produces a node-CarPlay host-UI request. The bridge exposes it as `host_ui_requested`, and the launcher returns to its home page while retaining the dongle session.

The microphone page uses a separate capture worker and BlueALSA's HFP PCM source. Merely opening PCM yielded digital silence during testing; the bounded local HFP call-state test enabled microphone samples. This is not connected to the CarPlay audio path.
