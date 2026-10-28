export var AudioCommand;
(function (AudioCommand) {
    AudioCommand[AudioCommand["AudioOutputStart"] = 1] = "AudioOutputStart";
    AudioCommand[AudioCommand["AudioOutputStop"] = 2] = "AudioOutputStop";
    AudioCommand[AudioCommand["AudioInputConfig"] = 3] = "AudioInputConfig";
    AudioCommand[AudioCommand["AudioPhonecallStart"] = 4] = "AudioPhonecallStart";
    AudioCommand[AudioCommand["AudioPhonecallStop"] = 5] = "AudioPhonecallStop";
    AudioCommand[AudioCommand["AudioNaviStart"] = 6] = "AudioNaviStart";
    AudioCommand[AudioCommand["AudioNaviStop"] = 7] = "AudioNaviStop";
    AudioCommand[AudioCommand["AudioSiriStart"] = 8] = "AudioSiriStart";
    AudioCommand[AudioCommand["AudioSiriStop"] = 9] = "AudioSiriStop";
    AudioCommand[AudioCommand["AudioMediaStart"] = 10] = "AudioMediaStart";
    AudioCommand[AudioCommand["AudioMediaStop"] = 11] = "AudioMediaStop";
    AudioCommand[AudioCommand["AudioAlertStart"] = 12] = "AudioAlertStart";
    AudioCommand[AudioCommand["AudioAlertStop"] = 13] = "AudioAlertStop";
})(AudioCommand || (AudioCommand = {}));
export class Message {
    header;
    constructor(header) {
        this.header = header;
    }
}
export class Command extends Message {
    value;
    constructor(header, data) {
        super(header);
        this.value = data.readUInt32LE(0);
    }
}
export class ManufacturerInfo extends Message {
    a;
    b;
    constructor(header, data) {
        super(header);
        this.a = data.readUInt32LE(0);
        this.b = data.readUInt32LE(4);
    }
}
export class SoftwareVersion extends Message {
    version;
    constructor(header, data) {
        super(header);
        this.version = data.toString('ascii');
    }
}
export class BluetoothAddress extends Message {
    address;
    constructor(header, data) {
        super(header);
        this.address = data.toString('ascii');
    }
}
export class BluetoothPIN extends Message {
    pin;
    constructor(header, data) {
        super(header);
        this.pin = data.toString('ascii');
    }
}
export class BluetoothDeviceName extends Message {
    name;
    constructor(header, data) {
        super(header);
        this.name = data.toString('ascii');
    }
}
export class WifiDeviceName extends Message {
    name;
    constructor(header, data) {
        super(header);
        this.name = data.toString('ascii');
    }
}
export class HiCarLink extends Message {
    link;
    constructor(header, data) {
        super(header);
        this.link = data.toString('ascii');
    }
}
export class BluetoothPairedList extends Message {
    data;
    constructor(header, data) {
        super(header);
        this.data = data.toString('ascii');
    }
}
export var PhoneType;
(function (PhoneType) {
    PhoneType[PhoneType["AndroidMirror"] = 1] = "AndroidMirror";
    PhoneType[PhoneType["CarPlay"] = 3] = "CarPlay";
    PhoneType[PhoneType["iPhoneMirror"] = 4] = "iPhoneMirror";
    PhoneType[PhoneType["AndroidAuto"] = 5] = "AndroidAuto";
    PhoneType[PhoneType["HiCar"] = 6] = "HiCar";
})(PhoneType || (PhoneType = {}));
export class Plugged extends Message {
    phoneType;
    wifi;
    constructor(header, data) {
        super(header);
        const wifiAvail = Buffer.byteLength(data) === 8;
        if (wifiAvail) {
            this.phoneType = data.readUInt32LE(0);
            this.wifi = data.readUInt32LE(4);
            console.debug('wifi avail, phone type: ', PhoneType[this.phoneType], ' wifi: ', this.wifi);
        }
        else {
            this.phoneType = data.readUInt32LE(0);
            console.debug('no wifi avail, phone type: ', PhoneType[this.phoneType]);
        }
    }
}
export class Unplugged extends Message {
    constructor(header) {
        super(header);
    }
}
export const decodeTypeMap = {
    1: {
        frequency: 44100,
        channel: 2,
        bitDepth: 16,
        format: "S16LE",
        mimeType: "audio/L16; rate=44100; channels=2"
    },
    2: {
        frequency: 44100,
        channel: 2,
        bitDepth: 16,
        format: "S16LE",
        mimeType: "audio/L16; rate=44100; channels=2"
    },
    3: {
        frequency: 8000,
        channel: 1,
        bitDepth: 16,
        format: "S16LE",
        mimeType: "audio/L16; rate=8000; channels=1"
    },
    4: {
        frequency: 48000,
        channel: 2,
        bitDepth: 16,
        format: "S16LE",
        mimeType: "audio/L16; rate=48000; channels=2"
    },
    5: {
        frequency: 16000,
        channel: 1,
        bitDepth: 16,
        format: "S16LE",
        mimeType: "audio/L16; rate=16000; channels=1"
    },
    6: {
        frequency: 24000,
        channel: 1,
        bitDepth: 16,
        format: "S16LE",
        mimeType: "audio/L16; rate=24000; channels=1"
    },
    7: {
        frequency: 16000,
        channel: 2,
        bitDepth: 16,
        format: "S16LE",
        mimeType: "audio/L16; rate=16000; channels=2"
    },
};
export class AudioData extends Message {
    command;
    decodeType;
    volume;
    volumeDuration;
    audioType;
    data;
    constructor(header, data) {
        super(header);
        this.decodeType = data.readUInt32LE(0);
        this.volume = data.readFloatLE(4);
        this.audioType = data.readUInt32LE(8);
        const amount = data.length - 12;
        if (amount === 1) {
            this.command = data.readInt8(12);
        }
        else if (amount === 4) {
            this.volumeDuration = data.readFloatLE(12);
        }
        else {
            this.data = new Int16Array(data.buffer, 12);
        }
    }
}
export class VideoData extends Message {
    width;
    height;
    flags;
    length;
    unknown;
    data;
    constructor(header, data) {
        super(header);
        this.width = data.readUInt32LE(0);
        this.height = data.readUInt32LE(4);
        this.flags = data.readUInt32LE(8);
        this.length = data.readUInt32LE(12);
        this.unknown = data.readUInt32LE(16);
        this.data = data.subarray(20);
    }
}
var MediaType;
(function (MediaType) {
    MediaType[MediaType["Data"] = 1] = "Data";
    MediaType[MediaType["AlbumCover"] = 3] = "AlbumCover";
})(MediaType || (MediaType = {}));
export class MediaData extends Message {
    payload;
    constructor(header, data) {
        super(header);
        const type = data.readUInt32LE(0);
        if (type === MediaType.AlbumCover) {
            const imageData = data.subarray(4);
            this.payload = {
                type,
                base64Image: imageData.toString('base64'),
            };
        }
        else if (type === MediaType.Data) {
            const mediaData = data.subarray(4, data.length - 1);
            this.payload = {
                type,
                media: JSON.parse(mediaData.toString('utf8')),
            };
        }
        else {
            console.info(`Unexpected media type: ${type}`);
        }
    }
}
export class Opened extends Message {
    width;
    height;
    fps;
    format;
    packetMax;
    iBox;
    phoneMode;
    constructor(header, data) {
        super(header);
        this.width = data.readUInt32LE(0);
        this.height = data.readUInt32LE(4);
        this.fps = data.readUInt32LE(8);
        this.format = data.readUInt32LE(12);
        this.packetMax = data.readUInt32LE(16);
        this.iBox = data.readUInt32LE(20);
        this.phoneMode = data.readUInt32LE(24);
    }
}
export class BoxInfo extends Message {
    settings;
    constructor(header, data) {
        super(header);
        this.settings = JSON.parse(data.toString());
    }
}
export class Phase extends Message {
    phase;
    constructor(header, data) {
        super(header);
        //TODO: find correct mapped values
        this.phase = data.readUInt32LE(0);
    }
}
//# sourceMappingURL=readable.js.map