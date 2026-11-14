// Copyright (C) 2026 Evan Horsley (evy0311). GPL-3.0; see LICENSE and NOTICE.
#pragma once
#include <aasdk/Channel/MediaPlaybackStatus/MediaPlaybackStatusService.hpp>
#include <aasdk/Messenger/MessageId.hpp>
#include <aap_protobuf/service/phonestatus/PhoneStatusMessageId.pb.h>
#include <aap_protobuf/service/phonestatus/message/PhoneStatus.pb.h>

static QString projectionText(const std::string& value) {
    return QString::fromUtf8(value.data(), static_cast<int>(std::min<size_t>(value.size(), 2048))).left(256);
}

static void acknowledgeChannel(aasdk::channel::Channel& channel, boost::asio::io_service::strand& strand) {
    using namespace aap_protobuf::service::control;
    using namespace aasdk::messenger;
    auto packet = std::make_shared<Message>(channel.getId(), EncryptionType::ENCRYPTED, MessageType::CONTROL);
    packet->insertPayload(MessageId(message::ControlMessageType::MESSAGE_CHANNEL_OPEN_RESPONSE).getData());
    message::ChannelOpenResponse response;
    response.set_status(aap_protobuf::shared::MessageStatus::STATUS_SUCCESS);
    packet->insertPayload(response);
    auto promise = aasdk::channel::SendPromise::defer(strand);
    promise->then([] {}, [](const auto&) {});
    channel.send(std::move(packet), std::move(promise));
}

class ProjectionPhoneStatus : public oa::service::IService,
                              public std::enable_shared_from_this<ProjectionPhoneStatus> {
    boost::asio::io_service::strand strand;
    aasdk::messenger::IMessenger::Pointer messenger;
    aasdk::channel::Channel channel;
    Output& out;
    bool running = false;

    void receive() {
        if (!running) return;
        auto promise = aasdk::messenger::ReceivePromise::defer(strand);
        promise->then([self=shared_from_this()](auto packet) { self->handle(packet->getPayload()); },
                      [self=shared_from_this()](const auto&) { self->stop(); });
        messenger->enqueueReceive(channel.getId(), std::move(promise));
    }

    void handle(const aasdk::common::Data& data) {
        using namespace aap_protobuf::service::phonestatus;
        using Status = message::PhoneStatus;
        if (!running) return;
        if (data.size() >= 2) {
            const auto id = aasdk::messenger::MessageId(data).getId();
            if (id == aap_protobuf::service::control::message::ControlMessageType::MESSAGE_CHANNEL_OPEN_REQUEST) {
                acknowledgeChannel(channel, strand);
            } else if (id == PhoneStatusMessageId::PHONE_STATUS && data.size() <= 1024 * 1024) {
                Status report;
                if (report.ParseFromArray(data.data() + 2, static_cast<int>(data.size() - 2))) {
                    QJsonObject call;
                    for (const auto& entry : report.calls()) {
                        auto state = entry.phone_state();
                        if (state == Status::INACTIVE || state == Status::UNKNOWN) continue;
                        bool incoming = state == Status::INCOMING;
                        bool held = state == Status::ON_HOLD;
                        call = {{"phase", incoming ? "incoming" : held ? "held" : "active"},
                                {"name", projectionText(entry.caller_id())},
                                {"number", projectionText(entry.caller_number())}};
                        if (incoming || held) call["incoming"] = incoming;
                        if (!held) break;
                    }
                    out.json({{"state", "projection_call"}, {"call", call}});
                }
            }
        }
        receive();
    }
public:
    ProjectionPhoneStatus(boost::asio::io_service& io, aasdk::messenger::IMessenger::Pointer m, Output& output)
        : strand(io), messenger(std::move(m)),
          channel(strand, messenger, aasdk::messenger::ChannelId::PHONE_STATUS), out(output) {}

    void fillFeatures(aap_protobuf::service::control::message::ServiceDiscoveryResponse& response) override {
        auto* service = response.add_channels();
        service->set_id(static_cast<uint32_t>(channel.getId()));
        service->mutable_phone_status_service();
    }
    void start() override { running = true; receive(); }
    void stop() override {
        if (!running) return;
        running = false;
        out.json({{"state", "projection_call"}, {"call", QJsonObject{}}});
    }
    void pause() override {}
    void resume() override {}
};

class ProjectionMediaStatus : public oa::service::IService,
    public aasdk::channel::mediaplaybackstatus::IMediaPlaybackStatusServiceEventHandler,
    public std::enable_shared_from_this<ProjectionMediaStatus> {
    boost::asio::io_service::strand strand;
    std::shared_ptr<aasdk::channel::mediaplaybackstatus::MediaPlaybackStatusService> channel;
    Output& out;
    bool running = false;

    void receive() { if (running) channel->receive(shared_from_this()); }
public:
    ProjectionMediaStatus(boost::asio::io_service& io, aasdk::messenger::IMessenger::Pointer m, Output& output)
        : strand(io), channel(std::make_shared<aasdk::channel::mediaplaybackstatus::MediaPlaybackStatusService>(
              strand, std::move(m))), out(output) {}

    void fillFeatures(aap_protobuf::service::control::message::ServiceDiscoveryResponse& response) override {
        auto* service = response.add_channels();
        service->set_id(static_cast<uint32_t>(channel->getId()));
        service->mutable_media_playback_service();
    }
    void start() override { running = true; receive(); }
    void stop() override {
        if (!running) return;
        running = false;
        out.json({{"state", "media_metadata"}, {"clear", true}, {"fields", QJsonObject{}}});
    }
    void pause() override {}
    void resume() override {}
    void onChannelOpenRequest(const aap_protobuf::service::control::message::ChannelOpenRequest&) override {
        if (!running) return;
        acknowledgeChannel(*channel, strand);
        receive();
    }
    void onChannelError(const aasdk::error::Error&) override { stop(); }

    void onMetadataUpdate(const aap_protobuf::service::mediaplayback::message::MediaPlaybackMetadata& data) override {
        if (!running) return;
        QJsonObject fields{{"title", projectionText(data.song())}, {"artist", projectionText(data.artist())},
                           {"album", projectionText(data.album())}};
        if (data.has_duration_seconds() && data.duration_seconds() <= 604800)
            fields["duration_ms"] = static_cast<int>(data.duration_seconds() * 1000);
        out.json({{"state", "media_metadata"}, {"fields", fields}});
        receive();
    }

    void onPlaybackUpdate(const aap_protobuf::service::mediaplayback::message::MediaPlaybackStatus& data) override {
        using Playback = aap_protobuf::service::mediaplayback::message::MediaPlaybackStatus;
        if (!running) return;
        QJsonObject fields;
        if (data.has_state()) {
            fields["playback_state"] = data.state() == Playback::PLAYING ? "playing" :
                data.state() == Playback::PAUSED ? "paused" : "stopped";
        }
        if (data.has_media_source()) fields["app"] = projectionText(data.media_source());
        if (data.has_playback_seconds() && data.playback_seconds() <= 604800)
            fields["position_ms"] = static_cast<int>(data.playback_seconds() * 1000);
        out.json({{"state", "media_metadata"}, {"fields", fields}});
        receive();
    }
};
