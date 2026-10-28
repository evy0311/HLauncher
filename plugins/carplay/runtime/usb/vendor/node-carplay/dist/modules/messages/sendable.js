import { MessageType, MessageHeader, CommandMapping, } from './common.js';
import { clamp, getCurrentTimeInMs } from './utils.js';
export class SendableMessage {
    serialise() {
        return MessageHeader.asBuffer(this.type, 0);
    }
}
export class SendableMessageWithPayload extends SendableMessage {
    serialise() {
        const data = this.getPayload();
        const byteLength = Buffer.byteLength(data);
        const header = MessageHeader.asBuffer(this.type, byteLength);
        return Buffer.concat([header, data]);
    }
}
export class SendCommand extends SendableMessageWithPayload {
    type = MessageType.Command;
    value;
    getPayload() {
        const data = Buffer.alloc(4);
        data.writeUInt32LE(this.value);
        return data;
    }
    constructor(value) {
        super();
        this.value = CommandMapping[value];
    }
}
export var TouchAction;
(function (TouchAction) {
    TouchAction[TouchAction["Down"] = 14] = "Down";
    TouchAction[TouchAction["Move"] = 15] = "Move";
    TouchAction[TouchAction["Up"] = 16] = "Up";
})(TouchAction || (TouchAction = {}));
export class SendTouch extends SendableMessageWithPayload {
    type = MessageType.Touch;
    x;
    y;
    action;
    getPayload() {
        const actionB = Buffer.alloc(4);
        const xB = Buffer.alloc(4);
        const yB = Buffer.alloc(4);
        const flags = Buffer.alloc(4);
        actionB.writeUInt32LE(this.action);
        const finalX = clamp(10000 * this.x, 0, 10000);
        const finalY = clamp(10000 * this.y, 0, 10000);
        xB.writeUInt32LE(finalX);
        yB.writeUInt32LE(finalY);
        const data = Buffer.concat([actionB, xB, yB, flags]);
        return data;
    }
    constructor(x, y, action) {
        super();
        this.x = x;
        this.y = y;
        this.action = action;
    }
}
export var MultiTouchAction;
(function (MultiTouchAction) {
    MultiTouchAction[MultiTouchAction["Down"] = 1] = "Down";
    MultiTouchAction[MultiTouchAction["Move"] = 2] = "Move";
    MultiTouchAction[MultiTouchAction["Up"] = 0] = "Up";
})(MultiTouchAction || (MultiTouchAction = {}));
class TouchItem {
    x;
    y;
    action;
    id;
    constructor(x, y, action, id) {
        this.x = x;
        this.y = y;
        this.action = action;
        this.id = id;
    }
    getPayload() {
        const actionB = Buffer.alloc(4);
        const xB = Buffer.alloc(4);
        const yB = Buffer.alloc(4);
        const idB = Buffer.alloc(4);
        actionB.writeUInt32LE(this.action);
        idB.writeUInt32LE(this.id);
        //const finalX = clamp(10000 * this.x, 0, 10000)
        //const finalY = clamp(10000 * this.y, 0, 10000)
        xB.writeFloatLE(this.x);
        yB.writeFloatLE(this.y);
        const data = Buffer.concat([xB, yB, actionB, idB]);
        return data;
    }
}
export class SendMultiTouch extends SendableMessageWithPayload {
    type = MessageType.MultiTouch;
    touches;
    getPayload() {
        const data = Buffer.concat(this.touches.map(i => i.getPayload()));
        return data;
    }
    constructor(touchData) {
        super();
        this.touches = touchData.map(({ x, y, action }, index) => {
            return new TouchItem(x, y, action, index);
        });
    }
}
export class SendAudio extends SendableMessageWithPayload {
    type = MessageType.AudioData;
    data;
    getPayload() {
        const audioData = Buffer.alloc(12);
        audioData.writeUInt32LE(5, 0);
        audioData.writeFloatLE(0.0, 4);
        audioData.writeUInt32LE(3, 8);
        return Buffer.concat([audioData, Buffer.from(this.data.buffer)]);
    }
    constructor(data) {
        super();
        this.data = data;
    }
}
export class SendFile extends SendableMessageWithPayload {
    type = MessageType.SendFile;
    content;
    fileName;
    getFileName = (name) => {
        return Buffer.from(name + '\0', 'ascii');
    };
    getLength = (data) => {
        const buffer = Buffer.alloc(4);
        buffer.writeUInt32LE(Buffer.byteLength(data));
        return buffer;
    };
    getPayload() {
        const newFileName = this.getFileName(this.fileName);
        const nameLength = this.getLength(newFileName);
        const contentLength = this.getLength(this.content);
        const message = [nameLength, newFileName, contentLength, this.content];
        const data = Buffer.concat(message);
        return data;
    }
    constructor(content, fileName) {
        super();
        this.content = content;
        this.fileName = fileName;
    }
}
export var FileAddress;
(function (FileAddress) {
    FileAddress["DPI"] = "/tmp/screen_dpi";
    FileAddress["NIGHT_MODE"] = "/tmp/night_mode";
    FileAddress["HAND_DRIVE_MODE"] = "/tmp/hand_drive_mode";
    FileAddress["CHARGE_MODE"] = "/tmp/charge_mode";
    FileAddress["BOX_NAME"] = "/etc/box_name";
    FileAddress["OEM_ICON"] = "/etc/oem_icon.png";
    FileAddress["AIRPLAY_CONFIG"] = "/etc/airplay.conf";
    FileAddress["ICON_120"] = "/etc/icon_120x120.png";
    FileAddress["ICON_180"] = "/etc/icon_180x180.png";
    FileAddress["ICON_250"] = "/etc/icon_256x256.png";
    FileAddress["ANDROID_WORK_MODE"] = "/etc/android_work_mode";
})(FileAddress || (FileAddress = {}));
export class SendNumber extends SendFile {
    constructor(content, file) {
        const message = Buffer.alloc(4);
        message.writeUInt32LE(content);
        super(message, file);
    }
}
export class SendBoolean extends SendNumber {
    constructor(content, file) {
        super(Number(content), file);
    }
}
export class SendString extends SendFile {
    constructor(content, file) {
        if (content.length > 16) {
            console.error('string too long');
        }
        const message = Buffer.from(content, 'ascii');
        super(message, file);
    }
}
export class HeartBeat extends SendableMessage {
    type = MessageType.HeartBeat;
}
export class SendOpen extends SendableMessageWithPayload {
    type = MessageType.Open;
    config;
    getPayload() {
        const { config } = this;
        const width = Buffer.alloc(4);
        width.writeUInt32LE(config.width);
        const height = Buffer.alloc(4);
        height.writeUInt32LE(config.height);
        const fps = Buffer.alloc(4);
        fps.writeUInt32LE(config.fps);
        const format = Buffer.alloc(4);
        format.writeUInt32LE(config.format);
        const packetMax = Buffer.alloc(4);
        packetMax.writeUInt32LE(config.packetMax);
        const iBox = Buffer.alloc(4);
        iBox.writeUInt32LE(config.iBoxVersion);
        const phoneMode = Buffer.alloc(4);
        phoneMode.writeUInt32LE(config.phoneWorkMode);
        return Buffer.concat([
            width,
            height,
            fps,
            format,
            packetMax,
            iBox,
            phoneMode,
        ]);
    }
    constructor(config) {
        super();
        this.config = config;
    }
}
export class SendBoxSettings extends SendableMessageWithPayload {
    type = MessageType.BoxSettings;
    syncTime;
    config;
    getPayload() {
        // Intentionally using "syncTime" from now to avoid any drift
        // & delay between constructor() and getData()
        return Buffer.from(JSON.stringify({
            mediaDelay: this.config.mediaDelay,
            syncTime: this.syncTime ?? getCurrentTimeInMs(),
            androidAutoSizeW: this.config.width,
            androidAutoSizeH: this.config.height,
        }), 'ascii');
    }
    constructor(config, syncTime = null) {
        super();
        this.config = config;
        this.syncTime = syncTime;
    }
}
export var LogoType;
(function (LogoType) {
    LogoType[LogoType["HomeButton"] = 1] = "HomeButton";
    LogoType[LogoType["Siri"] = 2] = "Siri";
})(LogoType || (LogoType = {}));
export class SendLogoType extends SendableMessageWithPayload {
    type = MessageType.LogoType;
    logoType;
    getPayload() {
        const data = Buffer.alloc(4);
        data.writeUInt32LE(this.logoType);
        return data;
    }
    constructor(logoType) {
        super();
        this.logoType = logoType;
    }
}
export class SendIconConfig extends SendFile {
    constructor(config) {
        const valueMap = {
            oemIconVisible: 1,
            name: 'AutoBox',
            model: 'Magic-Car-Link-1.00',
            oemIconPath: FileAddress.OEM_ICON,
        };
        if (config.label) {
            valueMap.oemIconLabel = config.label;
        }
        const fileData = Object.entries(valueMap)
            .map(e => `${e[0]} = ${e[1]}`)
            .join('\n');
        super(Buffer.from(fileData + '\n', 'ascii'), FileAddress.AIRPLAY_CONFIG);
    }
}
// Disconnects phone and closes dongle - need to send open command again
export class SendCloseDongle extends SendableMessage {
    type = MessageType.CloseDongle;
}
// Disconnects phone session - dongle is still open and phone can re-connect
export class SendDisconnectPhone extends SendableMessage {
    type = MessageType.DisconnectPhone;
}
//# sourceMappingURL=sendable.js.map