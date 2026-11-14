#include <assert.h>
#include <stdio.h>

#include "power_controller.h"

namespace {

class Bench {
public:
    explicit Bench(uint32_t initialTime = 0) : now(initialTime), controller(now) {}

    void feed(uint16_t mv, uint32_t durationMs) {
        assert(durationMs % config::samplePeriodMs == 0);
        for (uint32_t elapsed = 0; elapsed < durationMs; elapsed += config::samplePeriodMs) {
            now += config::samplePeriodMs;
            controller.update(now, mv);
        }
    }

    uint32_t now;
    PowerController controller;
};

constexpr uint16_t charging = 14200;
constexpr uint16_t low = 12000;
constexpr uint16_t between = (config::batteryStartMv + config::batteryStopMv) / 2;
constexpr uint32_t filterWindowMs = config::samplePeriodMs * config::filterSamples;

void expect(const Bench& bench, PowerController::State state) {
    assert(bench.controller.state() == state);
    assert(bench.controller.relayEnabled() == (state != PowerController::State::Off));
    assert(bench.controller.shutdownAsserted() == (state == PowerController::State::ShuttingDown));
}

void startupAndHysteresis() {
    Bench bench;
    expect(bench, PowerController::State::Off);
    bench.feed(between, config::minimumOffMs + config::startQualifyMs);
    expect(bench, PowerController::State::Off);

    bench.feed(charging, filterWindowMs + config::startQualifyMs / 2);
    expect(bench, PowerController::State::Off);
    bench.feed(between, config::samplePeriodMs);
    bench.feed(charging, config::startQualifyMs);
    expect(bench, PowerController::State::Off);
    bench.feed(charging, filterWindowMs);
    expect(bench, PowerController::State::Running);

    bench.feed(low, config::stopQualifyMs / 2);
    expect(bench, PowerController::State::Running);
    bench.feed(between, config::stopQualifyMs + filterWindowMs);
    expect(bench, PowerController::State::Running);
    assert(bench.controller.filteredMv() == between);
}

void shutdownAndRestartAcrossRollover() {
    Bench bench(UINT32_MAX - config::minimumOffMs - config::startQualifyMs -
                config::stopQualifyMs - filterWindowMs);
    bench.feed(charging, config::minimumOffMs + config::startQualifyMs -
                             config::samplePeriodMs);
    expect(bench, PowerController::State::Off);
    bench.feed(charging, config::samplePeriodMs);
    expect(bench, PowerController::State::Running);

    while (!bench.controller.shutdownAsserted()) {
        bench.feed(low, config::samplePeriodMs);
        assert(bench.now - (UINT32_MAX - config::stopQualifyMs - filterWindowMs) <=
               config::stopQualifyMs + filterWindowMs);
    }
    expect(bench, PowerController::State::ShuttingDown);
    // Battery recovery does not cancel the shutdown request.
    bench.feed(charging, config::shutdownGraceMs - config::samplePeriodMs);
    expect(bench, PowerController::State::ShuttingDown);
    bench.feed(charging, config::samplePeriodMs);
    expect(bench, PowerController::State::Off);
    bench.feed(charging, config::minimumOffMs + config::startQualifyMs -
                             config::samplePeriodMs);
    expect(bench, PowerController::State::Off);
    bench.feed(charging, config::samplePeriodMs);
    expect(bench, PowerController::State::Running);
}

void senseFaults() {
    Bench bench;
    const uint32_t startWindow = config::minimumOffMs + config::startQualifyMs;
    bench.feed(0, startWindow);
    expect(bench, PowerController::State::Off);
    bench.feed(45000, startWindow);
    expect(bench, PowerController::State::Off);

    bench.feed(charging, startWindow);
    expect(bench, PowerController::State::Running);
    bench.feed(45000, config::samplePeriodMs);
    bench.feed(charging, config::stopQualifyMs + filterWindowMs);
    expect(bench, PowerController::State::Running);
    bench.feed(45000, config::stopQualifyMs + filterWindowMs);
    expect(bench, PowerController::State::ShuttingDown);
    bench.feed(45000, config::shutdownGraceMs);
    bench.feed(45000, startWindow);
    expect(bench, PowerController::State::Off);
}

}  // namespace

int main() {
    startupAndHysteresis();
    shutdownAndRestartAcrossRollover();
    senseFaults();
    puts("Power controller tests passed");
}
