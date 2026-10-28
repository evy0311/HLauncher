// Copyright (C) 2026 Evan Horsley (evy0311). GPL-3.0; see LICENSE and NOTICE.
// Wired-session endpoints using OpenAuto/aasdk interfaces. No Bluetooth
// management, location simulation or automatic microphone/call activation.
#pragma once
#include <f1x/openauto/autoapp/Projection/IAudioInput.hpp>
#include <f1x/openauto/autoapp/Service/MediaSource/MicrophoneMediaSourceService.hpp>
#include <aasdk/Channel/SensorSource/SensorSourceService.hpp>
#include <aap_protobuf/service/sensorsource/message/DrivingStatus.pb.h>

class UnavailableMicrophone:public oa::projection::IAudioInput {
public:
    // Opening the logical transport is distinct from activating capture.
    bool open()override{std::cerr<<"[HLauncher] Microphone channel opened; capture is unavailable\n";return true;}
    bool isActive()const override{return false;}
    void read(ReadPromise::Pointer promise)override{promise->reject();}
    void start(StartPromise::Pointer promise)override{
        std::cerr<<"[HLauncher] Microphone capture requested; returning unavailable (no capture route configured)\n";
        promise->reject();
    }
    void stop()override{}
    uint32_t getSampleSize()const override{return 16;}
    uint32_t getChannelCount()const override{return 1;}
    uint32_t getSampleRate()const override{return 16000;}
};

class SessionSensors:public oa::service::IService,
                     public aasdk::channel::sensorsource::ISensorSourceServiceEventHandler,
                     public std::enable_shared_from_this<SessionSensors> {
    boost::asio::io_service::strand strand;
    std::shared_ptr<aasdk::channel::sensorsource::SensorSourceService> channel;
    bool stopped=false;
public:
    // Bench build: the owner explicitly requested a fixed parked state.
    static int drivingPolicy(){return 0;}
private:
    using Status=aap_protobuf::shared::MessageStatus;
    using Type=aap_protobuf::service::sensorsource::message::SensorType;
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
            batch.add_driving_status_data()->set_status(drivingPolicy());
            std::cerr<<"[HLauncher] Driving status: hard-coded parked bench mode\n";
        }else if(type==Type::SENSOR_NIGHT_MODE){
            batch.add_night_mode_data()->set_night_mode(false);
            std::cerr<<"[HLauncher] Display appearance: day mode\n";
        }else{return;}
        channel->sendSensorEventIndication(batch,promise());
    }
public:
    SessionSensors(boost::asio::io_service& io,aasdk::messenger::IMessenger::Pointer messenger):
        strand(io),channel(std::make_shared<aasdk::channel::sensorsource::SensorSourceService>(strand,std::move(messenger))){}
    void start()override{stopped=false;receive();}
    void stop()override{stopped=true;}
    void pause()override{} void resume()override{}
    void fillFeatures(aap_protobuf::service::control::message::ServiceDiscoveryResponse& response)override{
        auto* entry=response.add_channels();entry->set_id(static_cast<uint32_t>(channel->getId()));
        auto* sensors=entry->mutable_sensor_source_service();
        sensors->add_sensors()->set_sensor_type(Type::SENSOR_DRIVING_STATUS_DATA);
        sensors->add_sensors()->set_sensor_type(Type::SENSOR_NIGHT_MODE);
    }
    void onChannelOpenRequest(const aap_protobuf::service::control::message::ChannelOpenRequest& request)override{
        std::cerr<<"[HLauncher] Sensor channel open: "<<request.service_id()<<"\n";
        aap_protobuf::service::control::message::ChannelOpenResponse response;
        response.set_status(Status::STATUS_SUCCESS);
        channel->sendChannelOpenResponse(response,promise());receive();
    }
    void onSensorStartRequest(const aap_protobuf::service::sensorsource::message::SensorRequest& request)override{
        auto type=request.type();
        bool supported=type==Type::SENSOR_DRIVING_STATUS_DATA||type==Type::SENSOR_NIGHT_MODE;
        std::cerr<<"[HLauncher] Sensor start: "<<static_cast<int>(type)<<" supported="<<supported<<"\n";
        aap_protobuf::service::sensorsource::message::SensorStartResponseMessage response;
        response.set_status(supported?Status::STATUS_SUCCESS:Status::STATUS_INVALID_SENSOR);
        auto p=aasdk::channel::SendPromise::defer(strand);
        p->then([self=shared_from_this(),supported,type](){if(supported)self->sendValue(type);},
                [self=shared_from_this()](const auto& error){self->onChannelError(error);});
        channel->sendSensorStartResponse(response,p);receive();
    }
    void onChannelError(const aasdk::error::Error& error)override{
        std::cerr<<"[HLauncher] Sensor channel ended: "<<error.what()<<"\n";stop();
    }
};
