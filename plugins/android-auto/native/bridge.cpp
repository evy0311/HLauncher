// Copyright (C) 2026 Evan Horsley (evy0311). GPL-3.0; see LICENSE and NOTICE.
// Uses OpenAuto's public projection/service interfaces. Upstream notices are
// retained in the separately fetched OpenAuto sources and third-party notices.
#include <QGuiApplication>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonArray>
#include <boost/asio.hpp>
#include <boost/log/utility/setup/console.hpp>
#include <boost/log/expressions.hpp>
#include <boost/log/trivial.hpp>
#include <libusb.h>
#include <aasdk/USB/USBWrapper.hpp>
#include <aasdk/USB/AccessoryModeQueryFactory.hpp>
#include <aasdk/USB/AccessoryModeQueryChainFactory.hpp>
#include <aasdk/USB/USBHub.hpp>
#include <aasdk/USB/ConnectedAccessoriesEnumerator.hpp>
#include <aasdk/TCP/TCPWrapper.hpp>
#include <f1x/openauto/autoapp/App.hpp>
#include <f1x/openauto/autoapp/Configuration/Configuration.hpp>
#include <f1x/openauto/autoapp/Service/AndroidAutoEntityFactory.hpp>
#include <f1x/openauto/autoapp/Service/MediaSink/VideoService.hpp>
#include <f1x/openauto/autoapp/Service/MediaSink/MediaAudioService.hpp>
#include <f1x/openauto/autoapp/Service/MediaSink/GuidanceAudioService.hpp>
#include <f1x/openauto/autoapp/Service/MediaSink/SystemAudioService.hpp>
#include <f1x/openauto/autoapp/Service/InputSource/InputSourceService.hpp>
#include <f1x/openauto/autoapp/Projection/IInputDeviceEventHandler.hpp>
#include <atomic>
#include <condition_variable>
#include <deque>
#include <iostream>
#include <mutex>
#include <thread>
#include <unistd.h>
#include <csignal>
#include <set>

namespace oa = f1x::openauto::autoapp;
namespace media = aap_protobuf::service::media::sink::message;

#include "session_services.hpp"

// stdout is exclusively framed binary: uint32 big-endian size (including type),
// uint8 type (1=H264, 2=JSON status, 3=PCM), followed by payload.
class Output {
    std::mutex lock; std::condition_variable ready;
    std::deque<std::vector<uint8_t>> pending;
    size_t queued=0;
    std::thread writer;
public:
    Output():writer([this]{for(;;){std::vector<uint8_t> packet;
        {std::unique_lock<std::mutex> guard(lock);ready.wait(guard,[this]{return !pending.empty();});
         packet=std::move(pending.front());pending.pop_front();queued-=packet.size();}
        size_t pos=0;while(pos<packet.size()){auto n=::write(1,packet.data()+pos,packet.size()-pos);
          if(n<=0)std::_Exit(0);pos+=n;}}}) {writer.detach();}
    void send(uint8_t type,const uint8_t* data,size_t length) {
        if(length>8*1024*1024)std::_Exit(2);
        uint32_t n=length+1;std::vector<uint8_t> packet{uint8_t(n>>24),uint8_t(n>>16),uint8_t(n>>8),uint8_t(n),type};
        if(length)packet.insert(packet.end(),data,data+length);
        {std::lock_guard<std::mutex> guard(lock);
         if(queued+packet.size()>16*1024*1024){std::cerr<<"OpenAuto output stalled; restarting session\n";std::_Exit(3);}
         queued+=packet.size();pending.emplace_back(std::move(packet));}ready.notify_one();
    }
    void state(const char* text){auto b=QJsonDocument(QJsonObject{{"status",text}}).toJson(QJsonDocument::Compact);send(2,reinterpret_cast<const uint8_t*>(b.constData()),b.size());}
};
class Video:public oa::projection::IVideoOutput {
    Output& out;
public:
    explicit Video(Output& o):out(o){}
    bool open()override{out.state("Android phone connected; negotiating video");return true;}
    bool init()override{return true;}
    void stop()override{out.state("Connect an Android phone to the Pi USB port");}
    void write(uint64_t,const aasdk::common::DataConstBuffer& b)override{out.send(1,b.cdata,b.size);}
    media::VideoFrameRateType getVideoFPS()const override{return media::VIDEO_FPS_60;}
    media::VideoCodecResolutionType getVideoResolution()const override{return media::VIDEO_800x480;}
    size_t getScreenDPI()const override{return 140;}
    QRect getVideoMargins()const override{return QRect(0,0,0,0);}
};
class Audio:public oa::projection::IAudioOutput {
    Output& out;uint32_t rate,channels,stream;
public:
    Audio(Output& o,uint32_t r,uint32_t c,uint32_t s):out(o),rate(r),channels(c),stream(s){}
    bool open()override{return true;}void start()override{}void stop()override{}void suspend()override{}
    uint32_t getSampleSize()const override{return 16;}
    uint32_t getChannelCount()const override{return channels;}
    uint32_t getSampleRate()const override{return rate;}
    void write(uint64_t,const aasdk::common::DataConstBuffer& b)override{
      // rate big-endian, channel count and stream number, then S16LE PCM.
      std::vector<uint8_t> bytes{uint8_t(rate>>24),uint8_t(rate>>16),uint8_t(rate>>8),uint8_t(rate),uint8_t(channels),uint8_t(stream)};
      bytes.insert(bytes.end(),b.cdata,b.cdata+b.size);out.send(3,bytes.data(),bytes.size());}
};
class Input:public oa::projection::IInputDevice {
    std::mutex lock;oa::projection::IInputDeviceEventHandler* handler=nullptr;
public:
    void start(oa::projection::IInputDeviceEventHandler& h)override{std::lock_guard<std::mutex> guard(lock);handler=&h;}
    void stop()override{std::lock_guard<std::mutex> guard(lock);handler=nullptr;}
    ButtonCodes getSupportedButtonCodes()const override{return {};}
    bool hasTouchscreen()const override{return true;}
    QRect getTouchscreenGeometry()const override{return QRect(0,0,800,480);}
    void touch(const QJsonObject& obj){
      oa::projection::TouchEvent event;
      event.type=static_cast<aap_protobuf::service::inputsource::message::PointerAction>(obj["action"].toInt());
      event.actionIndex=obj["index"].toInt();
      for(auto item:obj["points"].toArray()){auto p=item.toObject();event.pointers.push_back({uint32_t(p["x"].toInt()),uint32_t(p["y"].toInt()),uint32_t(p["id"].toInt())});}
      if(event.pointers.empty()||event.pointers.size()>2||event.actionIndex>=event.pointers.size())return;
      std::lock_guard<std::mutex> guard(lock);if(handler)handler->onTouchEvent(event);
    }
};
class ProjectionVideo:public oa::service::mediasink::VideoService {
    Output& out;
public:
    ProjectionVideo(boost::asio::io_service& io,aasdk::messenger::IMessenger::Pointer messenger,Output& o):
      VideoService(io,messenger,std::make_shared<Video>(o)),out(o){}
    void onVideoFocusRequest(const aap_protobuf::service::media::video::message::VideoFocusRequestNotification& request)override{
      auto adjusted=request;
      if(request.mode()==aap_protobuf::service::media::video::message::VIDEO_FOCUS_NATIVE){
        const char home[]="{\"home\":true}";out.send(2,reinterpret_cast<const uint8_t*>(home),sizeof(home)-1);
        // Keep projection alive for background audio and instant foreground return.
        adjusted.set_mode(aap_protobuf::service::media::video::message::VIDEO_FOCUS_PROJECTED);
      }
      VideoService::onVideoFocusRequest(adjusted);
    }
};
// Older phone-side implementations read identity from tags 2–11. Newer
// schemas moved it to HeadUnitInfo (tag 17); populate both on the wire.
static void completeIdentity(aap_protobuf::service::control::message::ServiceDiscoveryResponse& response) {
    const auto& info=response.headunit_info();
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wdeprecated-declarations"
    response.set_make(info.make().empty()?"HLauncher":info.make());
    response.set_model(info.model().empty()?"HondaLink HDMI":info.model());
    response.set_year(info.year().empty()?"2026":info.year());
    response.set_vehicle_id(info.vehicle_id());
    response.set_head_unit_make(info.head_unit_make().empty()?"HLauncher":info.head_unit_make());
    response.set_head_unit_model(info.head_unit_model().empty()?"HLauncher OpenAuto":info.head_unit_model());
    response.set_head_unit_software_build(info.head_unit_software_build().empty()?"1":info.head_unit_software_build());
    response.set_head_unit_software_version(info.head_unit_software_version().empty()?"1.0":info.head_unit_software_version());
    response.set_can_play_native_media_during_vr(false);
#pragma GCC diagnostic pop
}
class DiscoveryCompatibility:public oa::service::IService {
public:
    void start()override{} void stop()override{} void pause()override{} void resume()override{}
    void fillFeatures(aap_protobuf::service::control::message::ServiceDiscoveryResponse& response)override {
        completeIdentity(response);
        std::cerr<<"[HLauncher] Service discovery: legacy identity + HeadUnitInfo; "
                 <<response.channels_size()<<" channels; initialized="<<response.IsInitialized()<<"\n"
                 <<response.DebugString()<<"\n";
    }
};
class Factory:public oa::service::IServiceFactory {
    boost::asio::io_service& io;Output& out;std::shared_ptr<Input> input;
public:
    Factory(boost::asio::io_service& i,Output& o,std::shared_ptr<Input> in):io(i),out(o),input(in){}
    oa::service::ServiceList create(aasdk::messenger::IMessenger::Pointer messenger)override{
      oa::service::ServiceList services;
      services.emplace_back(std::make_shared<ProjectionVideo>(io,messenger,out));
      services.emplace_back(std::make_shared<oa::service::mediasink::MediaAudioService>(io,messenger,std::make_shared<Audio>(out,48000,2,0)));
      services.emplace_back(std::make_shared<oa::service::mediasink::GuidanceAudioService>(io,messenger,std::make_shared<Audio>(out,16000,1,1)));
      services.emplace_back(std::make_shared<oa::service::mediasink::SystemAudioService>(io,messenger,std::make_shared<Audio>(out,16000,1,1)));
      services.emplace_back(std::make_shared<oa::service::mediasource::MicrophoneMediaSourceService>(io,messenger,std::make_shared<UnavailableMicrophone>()));
      services.emplace_back(std::make_shared<SessionSensors>(io,messenger));
      services.emplace_back(std::make_shared<oa::service::inputsource::InputSourceService>(io,messenger,input));
      services.emplace_back(std::make_shared<DiscoveryCompatibility>());
      return services;
    }
};
int main(int argc,char** argv){
    if(argc>1&&std::string(argv[1])=="--check-driving-policy"){
      std::cout<<"{\"driving_status\":"<<SessionSensors::drivingPolicy()<<"}\n";return 0;
    }

    if(argc>1&&std::string(argv[1])=="--check-services"){
      boost::log::core::get()->set_logging_enabled(false);
      std::cout.rdbuf(std::cerr.rdbuf());
      // Construct real factory descriptors without starting channels, USB or BT.
      // Output's normal lifetime ends with the process, as in the runtime path.
      auto* out=new Output();boost::asio::io_service io;auto input=std::make_shared<Input>();
      Factory factory(io,*out,input);auto services=factory.create(nullptr);
      aap_protobuf::service::control::message::ServiceDiscoveryResponse response;
      for(auto& service:services)service->fillFeatures(response);
      std::set<uint32_t> ids;bool mic=false,sensors=false,inputOk=false;int audio=0,video=0;
      for(const auto& channel:response.channels()){
        ids.insert(channel.id());
        if(channel.has_media_source_service()){
          const auto& config=channel.media_source_service().audio_config();
          mic=config.sampling_rate()==16000&&config.number_of_bits()==16&&config.number_of_channels()==1;
        }
        if(channel.has_sensor_source_service()){
          std::set<int> types;for(const auto& sensor:channel.sensor_source_service().sensors())types.insert(sensor.sensor_type());
          sensors=types==std::set<int>{10,13};
        }
        if(channel.has_input_source_service()){
          const auto& source=channel.input_source_service();
          if(source.touchscreen_size()==1){const auto& screen=source.touchscreen(0);inputOk=screen.width()==800&&screen.height()==480;}
        }
        if(channel.has_media_sink_service()){
          if(channel.media_sink_service().video_configs_size())++video;else ++audio;
        }
      }
      bool ok=response.IsInitialized()&&response.channels_size()==7&&ids.size()==7&&mic&&sensors&&inputOk&&audio==3&&video==1;
      auto result=QJsonDocument(QJsonObject{{"valid",ok},{"channels",response.channels_size()},{"microphone_endpoint",mic},{"sensor_endpoints",sensors},{"vehicle_gps_advertised",false},{"physical_capture_available",false}}).toJson(QJsonDocument::Compact);
      result.append('\n');::write(1,result.constData(),result.size());std::_Exit(ok?0:1);
    }

    if(argc>1&&std::string(argv[1])=="--check-discovery"){
      aap_protobuf::service::control::message::ServiceDiscoveryResponse response;
      completeIdentity(response);
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wdeprecated-declarations"
      bool ok=response.has_make()&&response.has_model()&&response.has_year()&&response.has_vehicle_id()
        &&response.has_head_unit_make()&&response.has_head_unit_model()&&response.has_head_unit_software_build()
        &&response.has_head_unit_software_version()&&response.has_can_play_native_media_during_vr();
#pragma GCC diagnostic pop
      std::cout<<"{\"legacy_identity_present\":"<<(ok?"true":"false")<<"}\n";return ok?0:1;
    }

    if(argc>1&&std::string(argv[1])=="--check"){std::cout<<"{\"engine\":\"OpenAuto\",\"usb\":true,\"video\":\"800x480@60\",\"touch_points\":2,\"microphone\":false}\n";return 0;}
    // Upstream console messages must never corrupt the framed stdout channel.
    std::cout.rdbuf(std::cerr.rdbuf());
    signal(SIGPIPE,SIG_IGN);qputenv("QT_QPA_PLATFORM","offscreen");QGuiApplication qt(argc,argv);
    boost::log::add_console_log(std::cerr);boost::log::core::get()->set_filter(boost::log::trivial::severity>=boost::log::trivial::info);
    libusb_context* context=nullptr;if(libusb_init(&context)!=0)return 1;Output out;
    boost::asio::io_service io;boost::asio::io_service::work work(io);
    aasdk::usb::USBWrapper usb(context);aasdk::tcp::TCPWrapper tcp;
    aasdk::usb::AccessoryModeQueryFactory query(usb,io);
    aasdk::usb::AccessoryModeQueryChainFactory chains(usb,io,query);
    auto config=std::make_shared<oa::configuration::Configuration>();
    auto input=std::make_shared<Input>();Factory services(io,out,input);
    oa::service::AndroidAutoEntityFactory entities(io,config,services);
    auto hub=std::make_shared<aasdk::usb::USBHub>(usb,io,chains);
    auto enumerator=std::make_shared<aasdk::usb::ConnectedAccessoriesEnumerator>(usb,io,chains);
    auto app=std::make_shared<oa::App>(io,usb,tcp,entities,hub,enumerator);
    std::thread usbThread([&]{for(;;){timeval timeout{0,100000};libusb_handle_events_timeout_completed(context,&timeout,nullptr);}});usbThread.detach();
    std::thread ioThread([&]{try{io.run();}catch(const std::exception& e){std::cerr<<e.what()<<'\n';std::_Exit(4);}});ioThread.detach();
    out.state("Connect an Android phone to the Pi USB port");app->waitForUSBDevice();
    std::string line;while(std::getline(std::cin,line)){
      auto obj=QJsonDocument::fromJson(QByteArray::fromStdString(line)).object();
      if(obj["type"].toString()=="touch")io.post([input,obj]{input->touch(obj);});
    }
    // All state belongs to this isolated process. Avoid blocking the launcher
    // during libusb teardown; kernel closes descriptors when the process exits.
    std::_Exit(0);
}
