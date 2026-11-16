import { MessageType, SendableMessageWithPayload } from './vendor/node-carplay/dist/modules/index.js';

export class SendGpsReporting extends SendableMessageWithPayload {
  type = MessageType.Command;
  constructor(enabled) {
    super();
    this.enabled = enabled;
  }
  getPayload() {
    const payload = Buffer.alloc(4);
    payload.writeUInt32LE(this.enabled ? 18 : 19);
    return payload;
  }
}

function coordinate(value, width, positive, negative) {
  const totalMinutes = Math.round(Math.abs(value) * 60 * 1e6);
  const degrees = Math.floor(totalMinutes / 60e6);
  const minutes = ((totalMinutes % 60e6) / 1e6).toFixed(6);
  return [String(degrees).padStart(width, '0') + minutes.padStart(9, '0'), value < 0 ? negative : positive];
}

function sentence(fields) {
  const body = fields.join(',');
  let checksum = 0;
  for (const char of body) checksum ^= char.charCodeAt(0);
  return '$' + body + '*' + checksum.toString(16).toUpperCase().padStart(2, '0') + '\r\n';
}

export class SendVehicleGps extends SendableMessageWithPayload {
  type = 0x29;
  constructor(fix) {
    super();
    this.fix = fix;
  }
  getPayload() {
    const {latitude, longitude, utc_ms} = this.fix;
    const iso = new Date(utc_ms).toISOString();
    const time = iso.slice(11, 23).replaceAll(':', '');
    const date = iso.slice(8, 10) + iso.slice(5, 7) + iso.slice(2, 4);
    const coords = [...coordinate(latitude, 2, 'N', 'S'), ...coordinate(longitude, 3, 'E', 'W')];
    const speed = this.fix.speed_kph;
    const speedKnots = Date.now() < this.fix.speed_expires_ms &&
      Number.isFinite(speed) && speed >= 0 && speed <= 400 ? (speed / 1.852).toFixed(2) : '';
    // Leave unsupported receiver fields empty.
    const nmea = sentence(['GPGGA', time, ...coords, '1', '', '', '', '', '', '', '', '']) +
      sentence(['GPRMC', time, 'A', ...coords, speedKnots, '', date, '', '', 'A']);
    const ascii = Buffer.from(nmea, 'ascii');
    const size = Buffer.alloc(4);
    size.writeUInt32LE(ascii.length);
    return Buffer.concat([size, ascii]);
  }
}
