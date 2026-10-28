cmake_minimum_required(VERSION 3.16)
project(hlauncher_android_auto LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
find_package(Qt5 REQUIRED COMPONENTS Core Gui)
find_package(Boost REQUIRED COMPONENTS system log log_setup)
find_package(PkgConfig REQUIRED)
pkg_check_modules(USB REQUIRED IMPORTED_TARGET libusb-1.0)
find_package(OpenSSL REQUIRED)
find_package(Protobuf REQUIRED)
set(DEPS /opt/hlauncher-deps CACHE PATH "External dependency prefix")
set(OA ${DEPS}/src/openauto)
set(S ${OA}/src/autoapp)
add_executable(hlauncher-android-auto bridge.cpp
 ${S}/App.cpp ${S}/Configuration/Configuration.cpp
 ${S}/Service/AndroidAutoEntity.cpp ${S}/Service/AndroidAutoEntityFactory.cpp ${S}/Service/Pinger.cpp
 ${S}/Service/MediaSink/AudioMediaSinkService.cpp ${S}/Service/MediaSink/MediaAudioService.cpp
 ${S}/Service/MediaSink/GuidanceAudioService.cpp ${S}/Service/MediaSink/SystemAudioService.cpp
 ${S}/Service/MediaSink/VideoMediaSinkService.cpp ${S}/Service/MediaSink/VideoService.cpp
 ${S}/Service/InputSource/InputSourceService.cpp
 ${S}/Service/MediaSource/MediaSourceService.cpp ${S}/Service/MediaSource/MicrophoneMediaSourceService.cpp)
target_compile_definitions(hlauncher-android-auto PRIVATE BOOST_ALL_DYN_LINK)
target_include_directories(hlauncher-android-auto PRIVATE ${OA}/include ${DEPS}/src/aasdk/include ${DEPS}/src/aasdk/include/aasdk ${DEPS}/build/aasdk/include ${DEPS}/build/aasdk/protobuf ${DEPS}/include ${DEPS}/include/aasdk ${DEPS}/include/aap_protobuf)
target_link_directories(hlauncher-android-auto PRIVATE ${DEPS}/lib)
target_link_libraries(hlauncher-android-auto PRIVATE Qt5::Core Qt5::Gui Boost::system Boost::log Boost::log_setup PkgConfig::USB OpenSSL::SSL OpenSSL::Crypto protobuf::libprotobuf aasdk aap_protobuf pthread)
set_target_properties(hlauncher-android-auto PROPERTIES INSTALL_RPATH "${DEPS}/lib")
install(TARGETS hlauncher-android-auto RUNTIME DESTINATION bin)
