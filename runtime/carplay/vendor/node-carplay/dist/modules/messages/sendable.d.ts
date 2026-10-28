/// <reference types="node" />
import { DongleConfig } from '../DongleDriver.js';
import { MessageType, CommandMapping, CommandValue } from './common.js';
export declare abstract class SendableMessage {
    abstract type: MessageType;
    serialise(): Buffer;
}
export declare abstract class SendableMessageWithPayload extends SendableMessage {
    abstract type: MessageType;
    abstract getPayload(): Buffer;
    serialise(): Buffer;
}
export declare class SendCommand extends SendableMessageWithPayload {
    type: MessageType;
    value: CommandMapping;
    getPayload(): Buffer;
    constructor(value: CommandValue);
}
export declare enum TouchAction {
    Down = 14,
    Move = 15,
    Up = 16
}
export declare class SendTouch extends SendableMessageWithPayload {
    type: MessageType;
    x: number;
    y: number;
    action: TouchAction;
    getPayload(): Buffer;
    constructor(x: number, y: number, action: TouchAction);
}
export declare enum MultiTouchAction {
    Down = 1,
    Move = 2,
    Up = 0
}
declare class TouchItem {
    x: number;
    y: number;
    action: MultiTouchAction;
    id: number;
    constructor(x: number, y: number, action: MultiTouchAction, id: number);
    getPayload(): Buffer;
}
export declare class SendMultiTouch extends SendableMessageWithPayload {
    type: MessageType;
    touches: TouchItem[];
    getPayload(): Buffer;
    constructor(touchData: {
        x: number;
        y: number;
        action: MultiTouchAction;
    }[]);
}
export declare class SendAudio extends SendableMessageWithPayload {
    type: MessageType;
    data: Int16Array;
    getPayload(): Buffer;
    constructor(data: Int16Array);
}
export declare class SendFile extends SendableMessageWithPayload {
    type: MessageType;
    content: Buffer;
    fileName: string;
    private getFileName;
    private getLength;
    getPayload(): Buffer;
    constructor(content: Buffer, fileName: string);
}
export declare enum FileAddress {
    DPI = "/tmp/screen_dpi",
    NIGHT_MODE = "/tmp/night_mode",
    HAND_DRIVE_MODE = "/tmp/hand_drive_mode",
    CHARGE_MODE = "/tmp/charge_mode",
    BOX_NAME = "/etc/box_name",
    OEM_ICON = "/etc/oem_icon.png",
    AIRPLAY_CONFIG = "/etc/airplay.conf",
    ICON_120 = "/etc/icon_120x120.png",
    ICON_180 = "/etc/icon_180x180.png",
    ICON_250 = "/etc/icon_256x256.png",
    ANDROID_WORK_MODE = "/etc/android_work_mode"
}
export declare class SendNumber extends SendFile {
    constructor(content: number, file: FileAddress);
}
export declare class SendBoolean extends SendNumber {
    constructor(content: boolean, file: FileAddress);
}
export declare class SendString extends SendFile {
    constructor(content: string, file: FileAddress);
}
export declare class HeartBeat extends SendableMessage {
    type: MessageType;
}
export declare class SendOpen extends SendableMessageWithPayload {
    type: MessageType;
    config: DongleConfig;
    getPayload(): Buffer;
    constructor(config: DongleConfig);
}
export declare class SendBoxSettings extends SendableMessageWithPayload {
    type: MessageType;
    private syncTime;
    private config;
    getPayload(): Buffer;
    constructor(config: DongleConfig, syncTime?: number | null);
}
export declare enum LogoType {
    HomeButton = 1,
    Siri = 2
}
export declare class SendLogoType extends SendableMessageWithPayload {
    type: MessageType;
    logoType: LogoType;
    getPayload(): Buffer;
    constructor(logoType: LogoType);
}
export declare class SendIconConfig extends SendFile {
    constructor(config: {
        label?: string;
    });
}
export declare class SendCloseDongle extends SendableMessage {
    type: MessageType;
}
export declare class SendDisconnectPhone extends SendableMessage {
    type: MessageType;
}
export {};
