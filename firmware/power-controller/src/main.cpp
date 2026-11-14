#include <Arduino.h>
#include <avr/wdt.h>

#include "config.h"
#include "power_controller.h"

// Reset-mode watchdogs can stay enabled across a watchdog reset.
void disableWatchdogAtStartup() __attribute__((naked, used, section(".init3")));
void disableWatchdogAtStartup() {
    MCUSR = 0;
    wdt_disable();
}

namespace {

constexpr uint8_t batterySensePin = A0;
constexpr uint32_t statusPeriodMs = 1000;
PowerController controller(0);
uint32_t lastSampleMs;
uint32_t lastStatusMs;

uint16_t readBatteryMv() {
    constexpr uint16_t adcSteps = 1024;
    const uint32_t counts = analogRead(batterySensePin);
    return (counts * config::batteryFullScaleMv + adcSteps / 2) / adcSteps;
}

void applyOutputs() {
    digitalWrite(config::relayPin, controller.relayEnabled() ? HIGH : LOW);

    // The latch stays LOW in both modes. INPUT leaves the pull-up disabled.
    digitalWrite(config::shutdownPin, LOW);
    pinMode(config::shutdownPin, controller.shutdownAsserted() ? OUTPUT : INPUT);
}

const __FlashStringHelper* stateName() {
    switch (controller.state()) {
        case PowerController::State::Off:
            return F("OFF");
        case PowerController::State::Running:
            return F("RUNNING");
        case PowerController::State::ShuttingDown:
            return F("SHUTTING_DOWN");
    }
    return F("UNKNOWN");
}

}  // namespace

void setup() {
    applyOutputs();
    pinMode(config::relayPin, OUTPUT);
    analogReference(DEFAULT);
    analogRead(batterySensePin);  // Discard the first conversion.
    Serial.begin(115200);

    const uint32_t now = millis();
    controller = PowerController(now);
    lastSampleMs = now;
    lastStatusMs = now;
#if ENABLE_WATCHDOG
    wdt_enable(WDTO_2S);
#endif
}

void loop() {
    const uint32_t now = millis();
    if (now - lastSampleMs < config::samplePeriodMs) {
        return;
    }
    lastSampleMs = now;

    const uint16_t batteryMv = readBatteryMv();
    controller.update(now, batteryMv);
    applyOutputs();
#if ENABLE_WATCHDOG
    wdt_reset();
#endif

    if (now - lastStatusMs >= statusPeriodMs && Serial.availableForWrite() >= 56) {
        lastStatusMs = now;
        Serial.print(F("raw_mV="));
        Serial.print(batteryMv);
        Serial.print(F(" filtered_mV="));
        Serial.print(controller.filteredMv());
        Serial.print(F(" state="));
        Serial.println(stateName());
    }
}
