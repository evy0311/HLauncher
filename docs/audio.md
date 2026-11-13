# Audio output and PipeWire EQ

Open **Settings → Audio & EQ**. Main media audio is fixed to stereo HDMI.
The page has PipeWire on/off, EQ bypass, **Flat**, **EDM Bass**, and twelve gain
controls. Each band moves in 1 dB steps from −12 to +12 dB:

31.5, 50, 80, 125, 200, 315, 500 Hz; 1, 2, 4, 8 and 16 kHz.

The bands are peaking biquads with Q=1.4. Adjacent responses overlap: a +3 dB
slider does not define a rectangular frequency bin. Flat sets every gain to zero;
EQ bypass neutralizes all filters while leaving PipeWire running. PipeWire Off
uses direct ALSA and does not process EQ. Settings persist atomically in
`/var/lib/hlauncher/audio.json`. Gain changes apply during playback.

There is **no automatic preamp attenuation, normalization, compressor or limiter**.
Float processing preserves peaks above unity; the final integer HDMI endpoint
cannot represent those peaks and will clip them. A clean filter cannot make
positive gain on a full-scale track fit within that endpoint without changing
something else. The sliders remain uncompensated as requested.

## Presets and previous settings

EDM Bass sets +2/+3/+2 dB at 31.5/50/80 Hz, 0 at 125 Hz, −1 at 200/315 Hz and 0
above. Its measured response is about +4.35 dB at 50 Hz because bands overlap.
It is a starting point, not a car-specific subwoofer calibration. Flat is the
initial reference for comparisons; presets do not turn PipeWire on automatically.

Existing bass/mid/treble values are preserved in three compatibility filters.
If any are nonzero, the page explicitly says previous tone gains are active.
Choosing either new preset clears those old gains before applying the twelve
bands. This avoids silently losing saved settings or silently stacking an old
bass shelf behind a new preset. The development Pi had all three at zero.

## Processing and timing

Production playback is:

Plugin's dedicated PCM socket → separate audio process → float stereo mixer /
SoXR VHQ converter → direct ALSA, or buffered PipeWire input → EQ → native ALSA
HDMI sink.

The UI, frame rendering and Bluetooth control loop do not carry playback PCM.
The CarPlay USB bridge sends PCM and voice controls over a dedicated socket.
Voice controls apply in wire order before the next PCM packet. A separate
pipe carries H.264 video at the requested CarPlay frame rate (30 FPS by default). If that pipe backs up, the bridge sheds video
until it can resume at an IDR with the stream's parameter sets. The screen can
briefly hold its last picture while playback continues. The Pi gives the audio
process higher CPU scheduling priority when permitted and runs the CarPlay
decode thread at reduced priority.

The phone and adapter still control when PCM reaches the USB bridge. A prolonged
input gap can starve the HDMI output even with an idle Pi. Bridge statistics
report PCM interarrival gaps, PCM packet counts, and dropped video packets.
Compare those with PCM forwarding drops, mixer queue drops, and the HDMI
player's underrun diagnostics in the debug log. A PCM gap can also reflect
a pause or a change of stream. Player diagnostics are captured as they are
reported instead of waiting for the player to exit.

Source PCM is signed 16-bit at its declared rate. Mixing and EQ use float32 with
unity gain. Sources at 48 kHz are not resampled. Other rates use OS-provided
**libsoxr VHQ, 28-bit precision, linear phase, double-precision calculations**,
with float I/O, scale 1 and one converter thread. This replaces the much more
expensive libsamplerate best-sinc path. Idle streams flush the converter tail
after 150 ms and pad only their final partial block; new audio starts a fresh
converter. Another stream becoming ready does not pad a live partial block.

The native client in `native/pipewire_pcm.c` separates blocking stdin reads from
the PipeWire realtime callback with a bounded, preallocated 200 ms SPSC ring.
Playback starts after both stereo links exist and 80 ms is buffered. The
callback performs bounded copies and supplies silence on starvation; it does
not wait for stdin, allocate, log, or acquire a mutex. Diagnostic capture uses
a second nonblocking ring so file writes cannot stall the graph either.

The graph stays at 48 kHz stereo and a 960-frame / 20 ms quantum. In production,
the native ALSA HDMI sink owns the clock; there is no second record/aplay clock
between EQ and HDMI. The endpoint requests S32_LE. A 32-bit container preserves
DSP output precision; it does not add detail to the original source or establish
the radio DAC's bit depth. Check ALSA hw_params and ELD with the receiver powered
on. No arbitrary 96/192 kHz upsampling is introduced.

Float32 filters have a small numerical residual at zero gain. Bench Flat gain
was within 0.0011 dB of unity; do not describe the filtered path as bit-exact.

## Signal-level diagnostics

Each stream reports its discrete `source_peak`, `source_full_scale_samples`, and
post-conversion `converted_peak`. The mixer separately reports `peak` and
`clip_samples` before EQ. These cumulative values are available in journal
progress records and saved System diagnostics reports. They distinguish source
saturation risk, reconstruction overshoot and overload from summing streams.
Full-scale source samples alone are not proof that the original recording clipped.

`scripts/check_audio_peaks.py` passively meters post-EQ float output. Comparing
that meter with the source/converter/mixer meters locates the first above-unity
stage. A positive digital peak is separate from queue drops/xruns, amplifier
clipping, and the Pi's supply voltage. No compensation is applied by any meter.

## Measured indoors

The new graph passed a three-minute jitter/navigation test with every source
frame retained, zero active-graph error counters, and zero ring underruns.
Direct playback and the complete 44.1 kHz plugin-to-flat-EQ path each passed
one minute under UI navigation with zero queue drops and zero playback failures.
These checks use isolated software-clock graphs or ALSA null, never the radio;
HDMI clocking, actual listening and the car's crossover remain in-car checks.

## Installation and checks

The installer includes libsoxr0, libpipewire-0.3-dev, a compiler and pkg-config,
and builds the native input client with `scripts/build_pipewire_pcm.sh`.
The generated executable is `build/hlauncher-pw-input` and is not committed.
libsamplerate0 remains a benchmark/reference dependency. For an existing install:

```sh
sudo apt-get install libsoxr0 libpipewire-0.3-dev build-essential pkg-config
cd /opt/hlauncher
bash scripts/build_pipewire_pcm.sh
sudo systemctl restart hlauncher-pipewire hlauncher
```

The private PipeWire service uses `/run/hlauncher-pipewire` (0700), enumerates no
hardware and owns no Bluetooth profiles. BlueALSA remains the Bluetooth owner.
The profiler module supplies read-only graph error counters for diagnostics.
No HLauncher services are started merely by running the installer.

Receiver-free, isolated checks from the checkout:

```sh
sudo python3 scripts/check_audio_stack.py --seconds 180 --output /tmp/timing.json
sudo python3 scripts/check_audio_bypass.py --seconds 60 --output /tmp/bypass.json
sudo python3 scripts/check_audio_bypass.py --seconds 60 --pipewire --output /tmp/pipeline.json
sudo python3 scripts/check_eq_response.py --output /tmp/response.json
python3 scripts/check_signal_levels.py
python3 scripts/check_resampler.py --output /tmp/resampler.json
```

These use temporary settings and their own runtime directory; they do not alter
the production EQ or send tones to HDMI. The older check_audio_eq.py and
check_audio_pipeline.py use the shared private graph and must only be run with
playback idle. The former pw-cat stdin client is available solely for a
capture-file A/B diagnostic (`--compare-pw-cat`), not as a production fallback.

## In-car comparison

1. Put the radio's bass/mid/treble at neutral, disable loudness/extra EQ where
   available, and note its subwoofer setting. Keep listening volume constant.
2. Start with Flat and PipeWire Off. Play a familiar track for several minutes
   and navigate HLauncher. Record any interruption.
3. Turn PipeWire On with Flat. Repeat the same track/navigation and inspect drops,
   graph errors and levels. Compare EQ bypass against Flat without changing route.
4. Compare the radio's own subwoofer level first. Then try EDM Bass, adjusting
   31.5/50/80 Hz separately. Use 125/200/315 Hz to reduce upper-bass muddiness.
5. If distortion appears, return to Flat and compare stage peaks. Any boost can
   exceed full scale on a loud recording; lower individual bands as desired.

The Pi sends full-range stereo HDMI, not a separately addressable subwoofer/LFE
channel. The car's DSP/crossover decides what reaches the dedicated subwoofer.
There is no verified crossover frequency from the stock image in this work.
Phone-call routing and microphone support remain separate checks.

## Clean shutdown

System diagnostics → Shutdown opens the existing confirmation page and requests
`systemctl poweroff --no-block`. It allows normal systemd shutdown; tests mock
this action and never actually power off the development Pi.

## Verifying the connected HDMI receiver

With the Honda radio powered on and music playing, inspect
`/proc/asound/card*/eld*` for receiver capabilities and
`/proc/asound/card*/pcm*p/sub*/hw_params` for the active hardware format.
Expect the HDMI playback endpoint to be stereo, 48000 Hz and S32_LE; a closed
endpoint does not establish an active format. ELD describes advertised receiver
capabilities, not the source recording or radio DAC's effective resolution.
Compare journal `audio_stream_format` events (adapter PCM rate/channels) with
`audio_hdmi_open`, playback errors/drops and stage peak meters during repeated
CarPlay app-grid / Now Playing transitions.

The adapter protocol currently exposes signed 16-bit PCM. HLauncher preserves
those samples at unity before mixing/conversion, with no additional lossy codec
on its HDMI path. The source app, phone and dongle's internal transport are not
verified by checking the Pi's endpoint. A 32-bit output container or a higher
advertised HDMI rate does not prove lossless/high-resolution phone transport.
Positive EQ gains can still clip at the final endpoint; Flat or bypass is the
reference when checking signal quality.
