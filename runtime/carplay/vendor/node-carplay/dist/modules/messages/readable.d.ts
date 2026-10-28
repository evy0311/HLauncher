/// <reference types="node" />
import { MessageHeader, CommandMapping } from './common.js';
export declare enum AudioCommand {
    AudioOutputStart = 1,
    AudioOutputStop = 2,
    AudioInputConfig = 3,
    AudioPhonecallStart = 4,
    AudioPhonecallStop = 5,
    AudioNaviStart = 6,
    AudioNaviStop = 7,
    AudioSiriStart = 8,
    AudioSiriStop = 9,
    AudioMediaStart = 10,
    AudioMediaStop = 11,
    AudioAlertStart = 12,
    AudioAlertStop = 13
}
export declare abstract class Message {
    header: MessageHeader;
    constructor(header: MessageHeader);
}
export declare class Command extends Message {
    value: CommandMapping;
    constructor(header: MessageHeader, data: Buffer);
}
export declare class ManufacturerInfo extends Message {
    a: number;
    b: number;
    constructor(header: MessageHeader, data: Buffer);
}
export declare class SoftwareVersion extends Message {
    version: string;
    constructor(header: MessageHeader, data: Buffer);
}
export declare class BluetoothAddress extends Message {
    address: string;
    constructor(header: MessageHeader, data: Buffer);
}
export declare class BluetoothPIN extends Message {
    pin: string;
    constructor(header: MessageHeader, data: Buffer);
}
export declare class BluetoothDeviceName extends Message {
    name: string;
    constructor(header: MessageHeader, data: Buffer);
}
export declare class WifiDeviceName extends Message {
    name: string;
    constructor(header: MessageHeader, data: Buffer);
}
export declare class HiCarLink extends Message {
    link: string;
    constructor(header: MessageHeader, data: Buffer);
}
export declare class BluetoothPairedList extends Message {
    data: string;
    constructor(header: MessageHeader, data: Buffer);
}
export declare enum PhoneType {
    AndroidMirror = 1,
    CarPlay = 3,
    iPhoneMirror = 4,
    AndroidAuto = 5,
    HiCar = 6
}
export declare class Plugged extends Message {
    phoneType: PhoneType;
    wifi?: number;
    constructor(header: MessageHeader, data: Buffer);
}
export declare class Unplugged extends Message {
    constructor(header: MessageHeader);
}
export type AudioFormat = {
    frequency: 48000 | 44100 | 24000 | 16000 | 8000;
    channel: 1 | 2;
    bitDepth: number;
    format?: string;
    mimeType?: string;
};
type DecodeTypeMapping = {
    [key: number]: AudioFormat;
};
export declare const decodeTypeMap: DecodeTypeMapping;
export declare class AudioData extends Message {
    command?: AudioCommand;
    decodeType: number;
    volume: number;
    volumeDuration?: number;
    audioType: number;
    data?: Int16Array;
    constructor(header: MessageHeader, data: Buffer);
}
export declare class VideoData extends Message {
    width: number;
    height: number;
    flags: number;
    length: number;
    unknown: number;
    data: Buffer;
    constructor(header: MessageHeader, data: Buffer);
}
declare enum MediaType {
    Data = 1,
    AlbumCover = 3
}
export declare class MediaData extends Message {
    payload?: {
        type: MediaType.Data;
        media: {
            MediaSongName?: string;
            MediaAlbumName?: string;
            MediaArtistName?: string;
            MediaAPPName?: string;
            MediaSongDuration?: number;
            MediaSongPlayTime?: number;
        };
    } | {
        type: MediaType.AlbumCover;
        base64Image: string;
    };
    constructor(header: MessageHeader, data: Buffer);
}
export declare class Opened extends Message {
    width: number;
    height: number;
    fps: number;
    format: number;
    packetMax: number;
    iBox: number;
    phoneMode: number;
    constructor(header: MessageHeader, data: Buffer);
}
export declare class BoxInfo extends Message {
    settings: {
        HiCar: number;
        OemName: string;
        WiFiChannel: number;
        boxType: string;
        hwVersion: string;
        productType: string;
        uuid: string;
    } | {
        MDLinkType: string;
        MDModel: string;
        MDOSVersion: string;
        MDLinkVersion: string;
        cpuTemp: number;
    };
    constructor(header: MessageHeader, data: Buffer);
}
export declare class Phase extends Message {
    phase: number;
    constructor(header: MessageHeader, data: Buffer);
}
export {};
