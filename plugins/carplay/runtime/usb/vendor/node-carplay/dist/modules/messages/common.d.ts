/// <reference types="node" />
import { Message } from './readable.js';
export declare enum CommandMapping {
    invalid = 0,
    startRecordAudio = 1,
    stopRecordAudio = 2,
    requestHostUI = 3,
    siri = 5,
    mic = 7,
    boxMic = 15,
    enableNightMode = 16,
    disableNightMode = 17,
    wifi24g = 24,
    wifi5g = 25,
    left = 100,
    right = 101,
    frame = 12,
    audioTransferOn = 22,
    audioTransferOff = 23,
    selectDown = 104,
    selectUp = 105,
    back = 106,
    up = 113,
    down = 114,
    home = 200,
    play = 201,
    pause = 202,
    playOrPause = 203,
    next = 204,
    prev = 205,
    acceptPhone = 300,
    rejectPhone = 301,
    requestVideoFocus = 500,
    releaseVideoFocus = 501,
    wifiEnable = 1000,
    autoConnetEnable = 1001,
    wifiConnect = 1002,
    scanningDevice = 1003,
    deviceFound = 1004,
    deviceNotFound = 1005,
    connectDeviceFailed = 1006,
    btConnected = 1007,
    btDisconnected = 1008,
    wifiConnected = 1009,
    wifiDisconnected = 1010,
    btPairStart = 1011,
    wifiPair = 1012
}
export type CommandValue = keyof typeof CommandMapping;
export declare enum MessageType {
    Open = 1,
    Plugged = 2,
    Phase = 3,
    Unplugged = 4,
    Touch = 5,
    VideoData = 6,
    AudioData = 7,
    Command = 8,
    LogoType = 9,
    DisconnectPhone = 15,
    CloseDongle = 21,
    BluetoothAddress = 10,
    BluetoothPIN = 12,
    BluetoothDeviceName = 13,
    WifiDeviceName = 14,
    BluetoothPairedList = 18,
    ManufacturerInfo = 20,
    MultiTouch = 23,
    HiCarLink = 24,
    BoxSettings = 25,
    MediaData = 42,
    SendFile = 153,
    HeartBeat = 170,
    SoftwareVersion = 204
}
export declare class HeaderBuildError extends Error {
}
export declare class MessageHeader {
    length: number;
    type: MessageType;
    constructor(length: number, type: MessageType);
    static fromBuffer(data: Buffer): MessageHeader;
    static asBuffer(messageType: MessageType, byeLength: number): Buffer;
    toMessage(data?: Buffer): Message | null;
    static dataLength: number;
    static magic: number;
}
