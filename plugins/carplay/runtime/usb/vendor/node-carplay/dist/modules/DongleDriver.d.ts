/// <reference types="w3c-web-usb" />
/// <reference types="node" />
import EventEmitter from 'events';
import { PhoneType } from './messages/readable.js';
import { SendableMessage } from './messages/sendable.js';
export declare enum HandDriveType {
    LHD = 0,
    RHD = 1
}
export type PhoneTypeConfig = {
    frameInterval: number | null;
};
type PhoneTypeConfigMap = {
    [K in PhoneType]: PhoneTypeConfig;
};
export type DongleConfig = {
    androidWorkMode?: boolean;
    width: number;
    height: number;
    fps: number;
    dpi: number;
    format: number;
    iBoxVersion: number;
    packetMax: number;
    phoneWorkMode: number;
    nightMode: boolean;
    boxName: string;
    hand: HandDriveType;
    mediaDelay: number;
    audioTransferMode: boolean;
    wifiType: '2.4ghz' | '5ghz';
    micType: 'box' | 'os';
    phoneConfig: Partial<PhoneTypeConfigMap>;
};
export declare const DEFAULT_CONFIG: DongleConfig;
export declare class DriverStateError extends Error {
}
export declare class DongleDriver extends EventEmitter {
    private _heartbeatInterval;
    private _device;
    private _inEP;
    private _outEP;
    private errorCount;
    static knownDevices: {
        vendorId: number;
        productId: number;
    }[];
    initialise: (device: USBDevice) => Promise<void>;
    send: (message: SendableMessage) => Promise<boolean | null>;
    private readLoop;
    start: (config: DongleConfig) => Promise<void>;
    close: () => Promise<void>;
}
export {};
