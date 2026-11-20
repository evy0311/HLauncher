# Audio output and PipeWire EQ

Open **Settings → Audio**. Main media audio is fixed to stereo HDMI.
The EQ screen has one PipeWire on/off control and fourteen gain controls.
Frequencies run in order across three pages, with up to six bands per page.
Swipe left/right over the tracks or use **Previous** and **Next**; the page
count shows your position. Tap a frequency or its track
to select a band. One shared pair of large +/− buttons adjusts the selected
band, with its frequency and exact gain shown between them. Selection alone
does not change the sound. Each page remembers its selection while the page
is open. Tall tracks show the saved positions against +6, 0 and −6 dB marks.
Each band moves in 1 dB steps from −6 to +6 dB:

20, 25, 31.5, 50, 80, 125, 200, 315, 500 Hz; 1, 2, 4, 8 and 16 kHz.

The bands are peaking biquads with Q=1.4. Adjacent responses overlap: a +3 dB
slider does not define a rectangular frequency bin. **PipeWire On** enables the
saved EQ curve; **Off** uses direct ALSA without EQ. There is no separate EQ
switch. Choose **Flat** for neutral filters while PipeWire remains on. The status
line distinguishes the selected route and saved adjustments. Band edits remain
available while PipeWire is off, so you can prepare a curve without changing
playback. PipeWire on/off, legacy EQ bypass, all band gains and the selected
preset persist atomically in `/var/lib/hlauncher/audio.json`, on the image's
writable state partition. The audio process restores the selected route even
while idle. First-boot maintenance no longer stops its graph after restoration.

Old saved gains beyond ±6 dB are preserved. A page containing them displays the
previous ±12 dB scale and their exact values. Its outlying gains can be reduced
toward the new range but cannot be increased farther. Choosing a preset replaces
them explicitly. The saved format still accepts ±12 dB for updater rollback.

The old `eq` preference is retained for state compatibility. If an installation
has PipeWire enabled with EQ bypassed, the screen shows **EQ bypassed**
until the user acts. Tapping it enables both PipeWire and the saved curve;
subsequent taps switch between that processed route and direct output.

There is **no automatic preamp attenuation, normalization, compressor or limiter**.
Float processing preserves peaks above unity; the final integer HDMI endpoint
cannot represent those peaks and will clip them. A clean filter cannot make
positive gain on a full-scale track fit within that endpoint without changing
something else. The sliders remain uncompensated as requested.

## Presets and previous settings

Open **Presets** to choose from eight factory starting points across two pages.
The values below follow the fourteen-band order above:

| Preset | Band gains (dB) |
| --- | --- |
| Flat | 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 |
| Bass lift | 0, 0, +1, +2, +1, 0, −1, −1, 0, 0, 0, 0, 0, 0 |
| Deep bass | 0, +1, +2, +2, +1, 0, −1, −1, 0, 0, 0, 0, 0, 0 |
| Warm | 0, 0, 0, +1, +1, +1, 0, 0, 0, 0, 0, −1, −1, −1 |
| Vocal clarity | 0, 0, 0, 0, −1, −1, −1, 0, 0, +1, +2, +1, 0, 0 |
| Acoustic | 0, 0, 0, 0, 0, −1, −1, 0, 0, +1, +1, +1, +1, 0 |
| Rock | 0, 0, 0, +1, +2, +1, 0, −1, 0, +1, +1, +1, 0, 0 |
| Softer treble | 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, −1, −2, −2 |

These are mild tonal starting points, not measured corrections for a particular
car or speaker system. Overlapping bands can produce more boost than any single
slider value. Choosing a factory preset replaces all fourteen bands and clears previous
tone gains; manual changes become **Custom**. **Flat** is also the reset action.
Presets preserve whether PipeWire is on or off (and any legacy bypass state). Existing saved
curves, including the former EDM Bass curve, remain intact and appear as Custom.

Existing bass/mid/treble values are preserved in three compatibility filters.
When EQ is enabled through PipeWire, the page says if previous tone gains also apply.
Choosing a factory preset clears those old gains before applying the fourteen
bands. This avoids silently losing saved settings or silently stacking an old
bass shelf behind a new preset. The development Pi had all three at zero.

### Two saved user presets

Open **Presets** to see all eight factory curves and both user slots on one
screen. Tap **Save current** beside **User 1** or **User 2**. Replacing an occupied slot requires confirmation. Tap a saved slot
to load it; saving/loading keeps PipeWire on/off and EQ bypass as selected.
User slots capture all fourteen bands and any previous tone gains. Their active
name and curve survive reboots; both slots survive application updates.

User curves are stored separately and atomically in
`/var/lib/hlauncher/audio-presets.json`. An older application saving its own
`audio.json` therefore cannot erase the user library. For rollback readability,
`audio.json` keeps its original twelve-band `bands` shape and stores the added
frequencies in `low_bands`. Older versions ignore those added frequencies;
they can still read the original curve. The new app reads existing twelve-band
files without changing them and starts both added frequencies at 0 dB.

The Pi still sends full-range stereo HDMI. These bands do not independently
address the factory subwoofer output or change the headunit's unknown crossover.
They do not guarantee that the factory system reproduces 20 or 25 Hz. The
factory curves use modest boosts; gain/headroom behavior is otherwise unchanged.

The UI received a light spacing/type polish with the requested existing track
and shared +/− layout retained. Navigation and inactive actions use quieter
surfaces; the selected frequency is the accent. The pass follows
[unslop by Damir Sokolovsky (@heydamir)](https://heydamir.design/unslop), CC BY 4.0.

Bookworm compatibility: the private graph uses the access module's normal
same-user permissions. In the [PipeWire 0.3.65 access module](https://github.com/PipeWire/pipewire/blob/0.3.65/src/modules/module-access.c), `access.force` requests an external
permission grant even when its value says unrestricted, which can leave CLI
clients waiting. The private runtime directory remains restricted to its owner.

## PipeWire with neutral EQ

Enabling PipeWire alone does not enable an enhancement, normalization,
compression or limiting. Direct output and PipeWire both receive the same float
mixer output and SoXR sample-rate conversion described below. With the Flat preset,
the intended frequency response is neutral in both paths. PipeWire adds its
graph, buffering, and endpoint conversion; it is not an automatic quality upgrade
or a guaranteed bit-exact alternative. Timing and numerical output can differ.

## Processing and timing

Production playback is:

Plugin's dedicated PCM socket → separate audio process → float stereo mixer /
SoXR VHQ converter → direct ALSA, or buffered PipeWire input → EQ → native ALSA
HDMI sink.

The dedicated PCM socket keeps playback traffic off the UI and Bluetooth control
loop. The mixer rejects malformed packets. On a mixer process exit, the installed
systemd service restarts HLauncher.
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
`clip_samples` before EQ. These cumulative values are available in the Debug log
and saved System diagnostics reports. They distinguish source
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
sudo systemctl restart hlauncher
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
   graph errors and levels. Use PipeWire Off to compare against the direct route.
4. Compare the radio's own subwoofer level first. Then try Bass lift, adjusting
   31.5/50/80 Hz separately. Use 125/200/315 Hz to reduce upper-bass muddiness.
5. If distortion appears, return to Flat and compare stage peaks. Any boost can
   exceed full scale on a loud recording; lower individual bands as desired.

The Pi sends full-range stereo HDMI, not a separately addressable subwoofer/LFE
channel. The car's DSP/crossover decides what reaches the dedicated subwoofer.
There is no verified crossover frequency from the stock image in this work.
Phone-call routing and microphone support remain separate checks.

## Clean shutdown

Settings → System → Shut down opens a confirmation page and requests
`systemctl poweroff --no-block`. Diagnostics also links to that confirmation.
See the [optional Arduino Nano power controller](../firmware/power-controller/README.md)
for the separate ignition and shutdown hardware experiment.

## Verifying the connected HDMI receiver

With the Honda radio powered on and music playing, inspect
`/proc/asound/card*/eld*` for receiver capabilities and
`/proc/asound/card*/pcm*p/sub*/hw_params` for the active hardware format.
Expect the HDMI playback endpoint to be stereo, 48000 Hz and S32_LE; a closed
endpoint does not establish an active format. ELD describes advertised receiver
capabilities, not the source recording or radio DAC's effective resolution.
Compare Debug log `audio_stream_format` events (adapter PCM rate/channels) with
`audio_hdmi_open`, playback errors/drops and stage peak meters during repeated
CarPlay app-grid / Now Playing transitions.

The adapter protocol currently exposes signed 16-bit PCM. HLauncher preserves
those samples at unity before mixing/conversion, with no additional lossy codec
on its HDMI path. The source app, phone and dongle's internal transport are not
verified by checking the Pi's endpoint. A 32-bit output container or a higher
advertised HDMI rate does not prove lossless/high-resolution phone transport.
Positive EQ gains can still clip at the final endpoint; Flat or bypass is the
reference when checking signal quality.
