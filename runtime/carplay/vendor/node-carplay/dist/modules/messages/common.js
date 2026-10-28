import { AudioData, VideoData, MediaData, BluetoothAddress, BluetoothDeviceName, BluetoothPIN, ManufacturerInfo, SoftwareVersion, Command, Plugged, WifiDeviceName, HiCarLink, BluetoothPairedList, Opened, BoxInfo, Unplugged, Phase, } from './readable.js';
export var CommandMapping;
(function (CommandMapping) {
    CommandMapping[CommandMapping["invalid"] = 0] = "invalid";
    CommandMapping[CommandMapping["startRecordAudio"] = 1] = "startRecordAudio";
    CommandMapping[CommandMapping["stopRecordAudio"] = 2] = "stopRecordAudio";
    CommandMapping[CommandMapping["requestHostUI"] = 3] = "requestHostUI";
    CommandMapping[CommandMapping["siri"] = 5] = "siri";
    CommandMapping[CommandMapping["mic"] = 7] = "mic";
    CommandMapping[CommandMapping["boxMic"] = 15] = "boxMic";
    CommandMapping[CommandMapping["enableNightMode"] = 16] = "enableNightMode";
    CommandMapping[CommandMapping["disableNightMode"] = 17] = "disableNightMode";
    CommandMapping[CommandMapping["wifi24g"] = 24] = "wifi24g";
    CommandMapping[CommandMapping["wifi5g"] = 25] = "wifi5g";
    CommandMapping[CommandMapping["left"] = 100] = "left";
    CommandMapping[CommandMapping["right"] = 101] = "right";
    CommandMapping[CommandMapping["frame"] = 12] = "frame";
    CommandMapping[CommandMapping["audioTransferOn"] = 22] = "audioTransferOn";
    CommandMapping[CommandMapping["audioTransferOff"] = 23] = "audioTransferOff";
    CommandMapping[CommandMapping["selectDown"] = 104] = "selectDown";
    CommandMapping[CommandMapping["selectUp"] = 105] = "selectUp";
    CommandMapping[CommandMapping["back"] = 106] = "back";
    CommandMapping[CommandMapping["up"] = 113] = "up";
    CommandMapping[CommandMapping["down"] = 114] = "down";
    CommandMapping[CommandMapping["home"] = 200] = "home";
    CommandMapping[CommandMapping["play"] = 201] = "play";
    CommandMapping[CommandMapping["pause"] = 202] = "pause";
    CommandMapping[CommandMapping["playOrPause"] = 203] = "playOrPause";
    CommandMapping[CommandMapping["next"] = 204] = "next";
    CommandMapping[CommandMapping["prev"] = 205] = "prev";
    CommandMapping[CommandMapping["acceptPhone"] = 300] = "acceptPhone";
    CommandMapping[CommandMapping["rejectPhone"] = 301] = "rejectPhone";
    CommandMapping[CommandMapping["requestVideoFocus"] = 500] = "requestVideoFocus";
    CommandMapping[CommandMapping["releaseVideoFocus"] = 501] = "releaseVideoFocus";
    CommandMapping[CommandMapping["wifiEnable"] = 1000] = "wifiEnable";
    CommandMapping[CommandMapping["autoConnetEnable"] = 1001] = "autoConnetEnable";
    CommandMapping[CommandMapping["wifiConnect"] = 1002] = "wifiConnect";
    CommandMapping[CommandMapping["scanningDevice"] = 1003] = "scanningDevice";
    CommandMapping[CommandMapping["deviceFound"] = 1004] = "deviceFound";
    CommandMapping[CommandMapping["deviceNotFound"] = 1005] = "deviceNotFound";
    CommandMapping[CommandMapping["connectDeviceFailed"] = 1006] = "connectDeviceFailed";
    CommandMapping[CommandMapping["btConnected"] = 1007] = "btConnected";
    CommandMapping[CommandMapping["btDisconnected"] = 1008] = "btDisconnected";
    CommandMapping[CommandMapping["wifiConnected"] = 1009] = "wifiConnected";
    CommandMapping[CommandMapping["wifiDisconnected"] = 1010] = "wifiDisconnected";
    CommandMapping[CommandMapping["btPairStart"] = 1011] = "btPairStart";
    CommandMapping[CommandMapping["wifiPair"] = 1012] = "wifiPair";
})(CommandMapping || (CommandMapping = {}));
export var MessageType;
(function (MessageType) {
    MessageType[MessageType["Open"] = 1] = "Open";
    MessageType[MessageType["Plugged"] = 2] = "Plugged";
    MessageType[MessageType["Phase"] = 3] = "Phase";
    MessageType[MessageType["Unplugged"] = 4] = "Unplugged";
    MessageType[MessageType["Touch"] = 5] = "Touch";
    MessageType[MessageType["VideoData"] = 6] = "VideoData";
    MessageType[MessageType["AudioData"] = 7] = "AudioData";
    MessageType[MessageType["Command"] = 8] = "Command";
    MessageType[MessageType["LogoType"] = 9] = "LogoType";
    MessageType[MessageType["DisconnectPhone"] = 15] = "DisconnectPhone";
    MessageType[MessageType["CloseDongle"] = 21] = "CloseDongle";
    MessageType[MessageType["BluetoothAddress"] = 10] = "BluetoothAddress";
    MessageType[MessageType["BluetoothPIN"] = 12] = "BluetoothPIN";
    MessageType[MessageType["BluetoothDeviceName"] = 13] = "BluetoothDeviceName";
    MessageType[MessageType["WifiDeviceName"] = 14] = "WifiDeviceName";
    MessageType[MessageType["BluetoothPairedList"] = 18] = "BluetoothPairedList";
    MessageType[MessageType["ManufacturerInfo"] = 20] = "ManufacturerInfo";
    MessageType[MessageType["MultiTouch"] = 23] = "MultiTouch";
    MessageType[MessageType["HiCarLink"] = 24] = "HiCarLink";
    MessageType[MessageType["BoxSettings"] = 25] = "BoxSettings";
    MessageType[MessageType["MediaData"] = 42] = "MediaData";
    MessageType[MessageType["SendFile"] = 153] = "SendFile";
    MessageType[MessageType["HeartBeat"] = 170] = "HeartBeat";
    MessageType[MessageType["SoftwareVersion"] = 204] = "SoftwareVersion";
})(MessageType || (MessageType = {}));
export class HeaderBuildError extends Error {
}
export class MessageHeader {
    length;
    type;
    constructor(length, type) {
        this.length = length;
        this.type = type;
    }
    static fromBuffer(data) {
        if (data.length !== 16) {
            throw new HeaderBuildError(`Invalid buffer size - Expecting 16, got ${data.length}`);
        }
        const magic = data.readUInt32LE(0);
        if (magic !== MessageHeader.magic) {
            throw new HeaderBuildError(`Invalid magic number, received ${magic}`);
        }
        const length = data.readUInt32LE(4);
        const msgType = data.readUInt32LE(8);
        const typeCheck = data.readUInt32LE(12);
        if (typeCheck != ((msgType ^ -1) & 0xffffffff) >>> 0) {
            throw new HeaderBuildError(`Invalid type check, received ${typeCheck}`);
        }
        return new MessageHeader(length, msgType);
    }
    static asBuffer(messageType, byeLength) {
        const dataLen = Buffer.alloc(4);
        dataLen.writeUInt32LE(byeLength);
        const type = Buffer.alloc(4);
        type.writeUInt32LE(messageType);
        const typeCheck = Buffer.alloc(4);
        typeCheck.writeUInt32LE(((messageType ^ -1) & 0xffffffff) >>> 0);
        const magicNumber = Buffer.alloc(4);
        magicNumber.writeUInt32LE(MessageHeader.magic);
        return Buffer.concat([magicNumber, dataLen, type, typeCheck]);
    }
    toMessage(data) {
        const { type } = this;
        if (data) {
            switch (type) {
                case MessageType.AudioData:
                    return new AudioData(this, data);
                case MessageType.VideoData:
                    return new VideoData(this, data);
                case MessageType.MediaData:
                    return new MediaData(this, data);
                case MessageType.BluetoothAddress:
                    return new BluetoothAddress(this, data);
                case MessageType.BluetoothDeviceName:
                    return new BluetoothDeviceName(this, data);
                case MessageType.BluetoothPIN:
                    return new BluetoothPIN(this, data);
                case MessageType.ManufacturerInfo:
                    return new ManufacturerInfo(this, data);
                case MessageType.SoftwareVersion:
                    return new SoftwareVersion(this, data);
                case MessageType.Command:
                    return new Command(this, data);
                case MessageType.Plugged:
                    return new Plugged(this, data);
                case MessageType.WifiDeviceName:
                    return new WifiDeviceName(this, data);
                case MessageType.HiCarLink:
                    return new HiCarLink(this, data);
                case MessageType.BluetoothPairedList:
                    return new BluetoothPairedList(this, data);
                case MessageType.Open:
                    return new Opened(this, data);
                case MessageType.BoxSettings:
                    return new BoxInfo(this, data);
                case MessageType.Phase:
                    return new Phase(this, data);
                default:
                    console.debug(`Unknown message type: ${type}, data: ${data.toString()}`);
                    return null;
            }
        }
        else {
            switch (type) {
                case MessageType.Unplugged:
                    return new Unplugged(this);
                default:
                    console.debug(`Unknown message type without data: ${type}`);
                    return null;
            }
        }
    }
    static dataLength = 16;
    static magic = 0x55aa55aa;
}
//# sourceMappingURL=common.js.map