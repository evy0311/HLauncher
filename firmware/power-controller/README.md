# HLauncher Nano power controller

This PlatformIO project targets a classic 5 V Arduino Nano with an ATmega328P. The Nano stays on a protected, unswitched supply. A normally-open relay switches the **input** of the Raspberry Pi's separate 5 V converter.

## Behavior

- Reset starts with the relay off and D3 released. The Nano waits 5 seconds, then requires 5 seconds of battery voltage at or above 13.3 V and at or below 18.0 V before enabling the relay. Both the latest sample and its filtered value must qualify.
- Battery voltage is sampled every 50 ms and averaged over eight samples. While running, a filtered reading at or below 12.3 V or above 18.0 V must persist for 30 seconds to request shutdown. The gap between the on and off thresholds reduces cycling.
- The Nano pulls D3 low and keeps the relay closed for 60 seconds. It then opens the relay and releases D3, even if battery voltage recovered. The timer cannot detect an incomplete Pi shutdown. Adjust the interval with `shutdownGraceMs`.
- A restart requires a fresh off interval and voltage qualification.
- The Optiboot build uses a two-second hardware watchdog. Reset or loss of Nano power de-energizes the relay immediately through the external pull-down. A reset, loss of converter input, or protection trip can therefore cut Pi power before a graceful shutdown completes.

This is a voltage-only policy for a 12 V system. The 13.3 V / 12.3 V values are bench starting points. Measure the vehicle during crank, charging, engine-off, and while the Pi is running before selecting thresholds. Smart charging can overlap parked battery voltage, so the controller can shut off while driving or stay on after parking. Measure parked current from the always-on Nano and its regulator.

## Bench wiring

| Nano | Connection |
| --- | --- |
| A0 | Protected battery sense through the divider below |
| D4 | Active-high relay coil driver, with an external gate or input pull-down (e.g. 10 kΩ to ground for a logic-level N-MOSFET driver) |
| D3 | BCM GPIO17 (physical pin 11) through a 1 kΩ series resistor |
| GND | Shared ground with the Pi and the protected supplies |

- **Power path.** Use a fused battery feed with an automotive front end specified for reverse polarity, jump start, load dump, negative pulses and crank conditions. Use its protected output for the relay COM, the sense divider, and a suitable always-on Nano regulator. Wire relay NO to the Pi converter input. Use an automotive-rated converter sized for the Pi and its peripherals. Select relay contacts and fuse for the converter's input current and inrush. Drive the coil with a transistor or MOSFET and use flyback suppression sized for the coil. Verify the external pull-down keeps the coil off while D4 is floating during reset and upload. Keep coil and converter return currents away from the ADC ground connection.
- **Sense path.** Run 82 kΩ from the protected battery sense node to the divider junction, and 10 kΩ and 100 nF from that junction to ground. Run the junction through 1 kΩ to A0. Nominally 14.4 V gives 1.57 V at A0, with about 9.9 kΩ source resistance including the series resistor. This divider assumes the front end bounds the sense node during transients. Provide a current-limited ADC clamp or protected buffer sized for the remaining positive and negative excursions and the Nano's power-off condition. Ensure the sense path cannot feed the unpowered 5 V rail through A0, for example by using a buffer or switch specified for powered-off input protection. Keep A0 within its limits during supply sequencing as well as steady-state operation. The divider and capacitor alone provide scaling and filtering. Check the ATmega328P limits and the actual front-end clamp voltage before applying vehicle power.
- **Shutdown path.** Connect Nano D3 through 1 kΩ to Pi BCM GPIO17 (physical pin 11) and tie Nano GND to Pi GND (for example, physical pin 39). The Pi provides the 3.3 V pull-up. The Nano uses only output-low and high-impedance input with its pull-up disabled. Keep GPIO17 configured as an input and keep 5 V off that line. With this direct connection, keep the Nano powered whenever the Pi can be powered, including bench setup. If the Pi stays powered with the Nano off, the Pi pull-up can feed the Nano through D3's protection diode. The series resistor does not isolate the supplies. Avoid a Pi-to-Nano USB connection in this installation.

Reference designs and pin limits are available from [TI's automotive battery protection design](https://www.ti.com/tool/TIDA-01167), [Microchip's ATmega328P documentation](https://www.microchip.com/en-us/product/atmega328p), and [Raspberry Pi's GPIO documentation](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html).

## Raspberry Pi setup

On Raspberry Pi OS, reserve GPIO17 for the controller. Add this line to `/boot/firmware/config.txt` (older images use `/boot/config.txt`), then reboot. Remove the previous `gpio-poweroff` overlay if it was added. Verify that systemd-logind responds to the GPIO17 power-button event and that HLauncher and its services stop cleanly within the grace period.

```ini
dtoverlay=gpio-shutdown,gpio_pin=17,active_low=1,gpio_pull=up
```

See the [Raspberry Pi overlay reference](https://github.com/raspberrypi/firmware/blob/master/boot/overlays/README#L1703).

## Build and verify

Open this folder in VS Code with PlatformIO. The default build is `nanoatmega328new` for Optiboot. The `nanoatmega328` environment supports the old ATmegaBOOT upload speed and disables the watchdog for bench testing because that bootloader can get stuck in a watchdog reset loop. Use a verified watchdog-compatible bootloader for the installed controller. See the [PlatformIO board definitions](https://docs.platformio.org/en/stable/boards/atmelavr/nanoatmega328new.html) and [Arduino's bootloader discussion](https://github.com/arduino/ArduinoCore-avr/issues/150).

```sh
pio run
pio run -e nanoatmega328new -t upload
pio device monitor -b 115200
```

The monitor prints raw and filtered battery millivolts and controller state. With the Pi disconnected, use a current-limited bench supply and meter to check the relay and GPIO states. At a stable known input, scale `adcReferenceMv` in `include/config.h` by measured input voltage divided by reported voltage, then verify it near both thresholds. Tune the remaining constants in that same file. Verify the relay stays open during reset, brief sags leave it on, and D3 pulls low while the relay stays closed for 60 seconds. Confirm watchdog recovery with a temporary firmware stall on the bench. Then connect the Pi and verify a low-voltage request shuts it down before the relay opens. Include a request during boot and input-voltage recovery during shutdown.

Run the state-machine checks on a computer with a C++ compiler from this project directory.

```sh
c++ -std=c++11 -Wall -Wextra -Werror -Iinclude test/power_controller_test.cpp -o /tmp/hlauncher-power-controller-test
/tmp/hlauncher-power-controller-test
```
