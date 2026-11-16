// Copyright (C) 2026 Evan Horsley (evy0311). GPL-3.0; see LICENSE and NOTICE.
// Wired-session endpoints. The HLauncher host owns Bluetooth and microphone capture.
#pragma once
#include <algorithm>
#include <array>
#include <optional>
#include <boost/asio/steady_timer.hpp>
#include <f1x/openauto/autoapp/Projection/IAudioInput.hpp>
#include <f1x/openauto/autoapp/Service/MediaSource/MicrophoneMediaSourceService.hpp>
#include <aasdk/Channel/SensorSource/SensorSourceService.hpp>
#include <aap_protobuf/service/sensorsource/message/DrivingStatus.pb.h>

class RadioMicrophone : public oa::projection::IAudioInput {
    std::function<void(bool)> captureRequested;
    ReadPromise::Pointer pending;
    std::deque<aasdk::common::Data> frames;
    bool active = false;
public:
    explicit RadioMicrophone(std::function<void(bool)> callback)
        : captureRequested(std::move(callback)) {}

    bool open() override { return true; }
    bool isActive() const override { return active; }

    void start(StartPromise::Pointer promise) override {
        if (!active) {
            active = true;
            captureRequested(true);
        }
        promise->resolve();
    }

    void stop() override {
        if (!active) return;
        active = false;
        captureRequested(false);
        frames.clear();
        if (auto read = std::move(pending)) read->reject();
    }

    void read(ReadPromise::Pointer promise) override {
        if (!active || pending) {
            promise->reject();
        } else if (frames.empty()) {
            pending = std::move(promise);
        } else {
            auto data = std::move(frames.front());
            frames.pop_front();
            promise->resolve(std::move(data));
        }
    }

    void push(aasdk::common::Data data) {
        if (!active || data.empty()) return;
        if (auto read = std::move(pending)) {
            read->resolve(std::move(data));
        } else {
            if (frames.size() >= 3) frames.pop_front();
            frames.push_back(std::move(data));
        }
    }

    uint32_t getSampleSize() const override { return 16; }
    uint32_t getChannelCount() const override { return 1; }
    uint32_t getSampleRate() const override { return 16000; }
};

struct VehicleState {
    std::optional<int> speedMmPerSecond;
    std::optional<bool> parkingBrake;
    using Clock = std::chrono::steady_clock;
    Clock::time_point speedUntil = Clock::time_point::max();
    Clock::time_point brakeUntil = Clock::time_point::max();

    void expire() {
        const auto now = Clock::now();
        if (now >= speedUntil) speedMmPerSecond.reset();
        if (now >= brakeUntil) parkingBrake.reset();
    }
};

struct GpsFix {
    int latitudeE7;
    int longitudeE7;
    std::chrono::steady_clock::time_point expires;
};

class SessionSensors:public oa::service::IService,
                     public aasdk::channel::sensorsource::ISensorSourceServiceEventHandler,
                     public std::enable_shared_from_this<SessionSensors> {
    boost::asio::io_service::strand strand;
    std::shared_ptr<aasdk::channel::sensorsource::SensorSourceService> channel;
    bool stopped=false;
    bool nightMode;
    bool carGps;
    boost::asio::steady_timer vehicleExpiry;
    std::optional<GpsFix> gps;
    std::set<aap_protobuf::service::sensorsource::message::SensorType> subscriptions;
    VehicleState vehicle;
public:
    static int drivingPolicy(const VehicleState& state) {
        using namespace aap_protobuf::service::sensorsource::message;
        if (state.parkingBrake == true && state.speedMmPerSecond == 0)
            return DRIVE_STATUS_UNRESTRICTED;
        return DRIVE_STATUS_NO_VIDEO | DRIVE_STATUS_NO_KEYBOARD_INPUT |
               DRIVE_STATUS_NO_CONFIG | DRIVE_STATUS_LIMIT_MESSAGE_LEN;
    }
private:
    using Status=aap_protobuf::shared::MessageStatus;
    using Type=aap_protobuf::service::sensorsource::message::SensorType;
    static constexpr std::array<Type, 4> supportedTypes{
        Type::SENSOR_DRIVING_STATUS_DATA, Type::SENSOR_NIGHT_MODE,
        Type::SENSOR_SPEED, Type::SENSOR_PARKING_BRAKE
    };
    void receive(){if(!stopped)channel->receive(shared_from_this());}
    aasdk::channel::SendPromise::Pointer promise(){
        auto p=aasdk::channel::SendPromise::defer(strand);
        p->then([](){},[self=shared_from_this()](const auto& error){self->onChannelError(error);});
        return p;
    }
    void sendValue(Type type){
        if(stopped)return;
        aap_protobuf::service::sensorsource::message::SensorBatch batch;
        if(type==Type::SENSOR_DRIVING_STATUS_DATA){
            batch.add_driving_status_data()->set_status(drivingPolicy(vehicle));
        }else if(type==Type::SENSOR_NIGHT_MODE){
            batch.add_night_mode_data()->set_night_mode(nightMode);
            std::cerr<<"[HLauncher] Display appearance: "<<(nightMode?"night":"day")<<" mode\n";
        } else if (type == Type::SENSOR_SPEED && vehicle.speedMmPerSecond) {
            batch.add_speed_data()->set_speed_e3(*vehicle.speedMmPerSecond);
        } else if (type == Type::SENSOR_PARKING_BRAKE && vehicle.parkingBrake) {
            batch.add_parking_brake_data()->set_parking_brake(*vehicle.parkingBrake);
        } else if (type == Type::SENSOR_LOCATION && gps && std::chrono::steady_clock::now() < gps->expires) {
            auto* location = batch.add_location_data();
            location->set_latitude_e7(gps->latitudeE7);
            location->set_longitude_e7(gps->longitudeE7);
        } else {
            return;
        }
        channel->sendSensorEventIndication(batch,promise());
    }
public:
    SessionSensors(boost::asio::io_service& io,aasdk::messenger::IMessenger::Pointer messenger,bool initialNightMode,
                   VehicleState initialVehicle, bool carGps, std::optional<GpsFix> gps):
        strand(io),channel(std::make_shared<aasdk::channel::sensorsource::SensorSourceService>(strand,std::move(messenger))),
        nightMode(initialNightMode), carGps(carGps), vehicleExpiry(io), gps(gps), vehicle(initialVehicle){}
    void setGps(std::optional<GpsFix> fix) {
        boost::asio::post(strand, [self=shared_from_this(), fix] {
            self->gps = fix;
            if (self->subscriptions.count(Type::SENSOR_LOCATION)) self->sendValue(Type::SENSOR_LOCATION);
        });
    }
    void setNightMode(bool enabled){
        boost::asio::post(strand,[self=shared_from_this(),enabled]{
            if(self->nightMode==enabled)return;
            self->nightMode=enabled;
            if(self->subscriptions.count(Type::SENSOR_NIGHT_MODE))self->sendValue(Type::SENSOR_NIGHT_MODE);
        });
    }
    void updateVehicle(VehicleState state) {
        state.expire();
        const auto previous = vehicle;
        vehicle = state;
        if (subscriptions.count(Type::SENSOR_SPEED) && previous.speedMmPerSecond != state.speedMmPerSecond)
            sendValue(Type::SENSOR_SPEED);
        if (subscriptions.count(Type::SENSOR_PARKING_BRAKE) && previous.parkingBrake != state.parkingBrake)
            sendValue(Type::SENSOR_PARKING_BRAKE);
        if (subscriptions.count(Type::SENSOR_DRIVING_STATUS_DATA) && drivingPolicy(previous) != drivingPolicy(state))
            sendValue(Type::SENSOR_DRIVING_STATUS_DATA);
        vehicleExpiry.cancel();
        auto next = VehicleState::Clock::time_point::max();
        if (state.speedMmPerSecond) next = state.speedUntil;
        if (state.parkingBrake) next = std::min(next, state.brakeUntil);
        if (stopped || next == VehicleState::Clock::time_point::max()) return;
        vehicleExpiry.expires_at(next);
        vehicleExpiry.async_wait(strand.wrap([weak=weak_from_this()](const boost::system::error_code& error) {
            if (!error) {
                if (auto self = weak.lock(); self && !self->stopped) self->updateVehicle(self->vehicle);
            }
        }));
    }
    void setVehicle(VehicleState state) {
        boost::asio::post(strand, [self=shared_from_this(), state] {
            if (!self->stopped) self->updateVehicle(state);
        });
    }
    void start()override{stopped=false;updateVehicle(vehicle);receive();}
    void stop()override{stopped=true;vehicleExpiry.cancel();subscriptions.clear();}
    void pause()override{} void resume()override{}
    void fillFeatures(aap_protobuf::service::control::message::ServiceDiscoveryResponse& response)override{
        auto* entry=response.add_channels();entry->set_id(static_cast<uint32_t>(channel->getId()));
        auto* sensors=entry->mutable_sensor_source_service();
        for (auto type : supportedTypes) {
            if (supports(type)) sensors->add_sensors()->set_sensor_type(type);
        }
        if (carGps) sensors->add_sensors()->set_sensor_type(Type::SENSOR_LOCATION);
    }
    void onChannelOpenRequest(const aap_protobuf::service::control::message::ChannelOpenRequest& request)override{
        std::cerr<<"[HLauncher] Sensor channel open: "<<request.service_id()<<"\n";
        aap_protobuf::service::control::message::ChannelOpenResponse response;
        response.set_status(Status::STATUS_SUCCESS);
        channel->sendChannelOpenResponse(response,promise());receive();
    }
    void onSensorStartRequest(const aap_protobuf::service::sensorsource::message::SensorRequest& request)override{
        auto type=request.type();
        bool supported = supports(type);
        std::cerr<<"[HLauncher] Sensor start: "<<static_cast<int>(type)<<" supported="<<supported<<"\n";
        aap_protobuf::service::sensorsource::message::SensorStartResponseMessage response;
        response.set_status(supported?Status::STATUS_SUCCESS:Status::STATUS_INVALID_SENSOR);
        auto p=aasdk::channel::SendPromise::defer(strand);
        p->then([self=shared_from_this(),supported,type](){
                    if(!supported || self->stopped)return;
                    self->subscriptions.insert(type);
                    self->sendValue(type);
                },
                [self=shared_from_this()](const auto& error){self->onChannelError(error);});
        channel->sendSensorStartResponse(response,p);receive();
    }
    void onChannelError(const aasdk::error::Error& error)override{
        std::cerr<<"[HLauncher] Sensor channel ended: "<<error.what()<<"\n";stop();
    }
private:
    bool supports(Type type) const {
        if (type == Type::SENSOR_LOCATION) return carGps;
        return std::find(supportedTypes.begin(), supportedTypes.end(), type) != supportedTypes.end();
    }
};
