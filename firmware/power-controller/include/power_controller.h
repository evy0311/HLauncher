#pragma once

#include "config.h"

class PowerController {
public:
    enum class State : uint8_t { Off, Running, ShuttingDown };

    explicit PowerController(uint32_t now) : stateSince_(now) {}

    void update(uint32_t now, uint16_t batteryMv) {
        // Wait for a full window before allowing a start.
        if (sampleCount_ < config::filterSamples) {
            ++sampleCount_;
        }
        sampleSum_ -= samples_[nextSample_];
        samples_[nextSample_] = batteryMv;
        sampleSum_ += batteryMv;
        if (++nextSample_ == config::filterSamples) {
            nextSample_ = 0;
        }

        const uint16_t filtered = filteredMv();
        switch (state_) {
            case State::Off:
                if (qualified(now,
                              now - stateSince_ >= config::minimumOffMs &&
                                  sampleCount_ == config::filterSamples &&
                                  filtered >= config::batteryStartMv &&
                                  filtered <= config::batteryMaxMv &&
                                  batteryMv >= config::batteryStartMv &&
                                  batteryMv <= config::batteryMaxMv,
                              config::startQualifyMs)) {
                    enter(State::Running, now);
                }
                break;
            case State::Running:
                if (qualified(now, filtered <= config::batteryStopMv ||
                                       filtered > config::batteryMaxMv,
                              config::stopQualifyMs)) {
                    enter(State::ShuttingDown, now);
                }
                break;
            case State::ShuttingDown:
                if (now - stateSince_ >= config::shutdownGraceMs) {
                    enter(State::Off, now);
                }
                break;
        }
    }

    State state() const { return state_; }
    uint16_t filteredMv() const { return sampleCount_ ? sampleSum_ / sampleCount_ : 0; }
    bool relayEnabled() const { return state_ != State::Off; }
    bool shutdownAsserted() const { return state_ == State::ShuttingDown; }

private:
    bool qualified(uint32_t now, bool condition, uint32_t duration) {
        if (!condition) {
            qualifying_ = false;
            return false;
        }
        if (!qualifying_) {
            qualifying_ = true;
            qualifySince_ = now;
        }
        // Unsigned subtraction handles millis() rollover.
        return now - qualifySince_ >= duration;
    }

    void enter(State state, uint32_t now) {
        state_ = state;
        stateSince_ = now;
        qualifying_ = false;
    }

    State state_ = State::Off;
    uint32_t stateSince_;
    uint32_t qualifySince_ = 0;
    bool qualifying_ = false;
    uint16_t samples_[config::filterSamples] = {};
    uint32_t sampleSum_ = 0;
    uint8_t sampleCount_ = 0;
    uint8_t nextSample_ = 0;
};
