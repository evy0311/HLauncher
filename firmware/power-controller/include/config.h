#pragma once

#include <stdint.h>

namespace config {

constexpr uint8_t relayPin = 4;     // Active HIGH driver with a hardware pull-down.
constexpr uint8_t shutdownPin = 3;  // LOW asserts, high-impedance releases.

// Measure and calibrate this value on the actual Nano supply.
constexpr uint32_t adcReferenceMv = 5000;
constexpr uint32_t dividerTopOhms = 82000;
constexpr uint32_t dividerBottomOhms = 10000;
constexpr uint32_t batteryFullScaleMv =
    adcReferenceMv * (dividerTopOhms + dividerBottomOhms) / dividerBottomOhms;

constexpr uint16_t batteryStartMv = 13300;
constexpr uint16_t batteryStopMv = 12300;
constexpr uint16_t batteryMaxMv = 18000;

constexpr uint32_t samplePeriodMs = 50;
constexpr uint8_t filterSamples = 8;
constexpr uint32_t minimumOffMs = 5000;
constexpr uint32_t startQualifyMs = 5000;
constexpr uint32_t stopQualifyMs = 30000;
constexpr uint32_t shutdownGraceMs = 60000;

static_assert(batteryStopMv > 0 && batteryStopMv < batteryStartMv &&
                  batteryStartMv < batteryMaxMv && batteryMaxMv < batteryFullScaleMv,
              "Check battery thresholds against the configured divider and reference");
static_assert(filterSamples > 0 && samplePeriodMs > 0, "Check ADC sampling settings");

}  // namespace config
