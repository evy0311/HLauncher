import assert from 'node:assert/strict';
import {SendBoxSettings} from '../plugins/carplay/runtime/usb/vendor/node-carplay/dist/modules/messages/sendable.js';
import {MediaData} from '../plugins/carplay/runtime/usb/vendor/node-carplay/dist/modules/messages/readable.js';
const settings = JSON.parse(new SendBoxSettings({mediaDelay:300,width:800,height:480}).getPayload().toString());
for (const enabled of [true, false]) {
  const gps = JSON.parse(new SendBoxSettings({carGps:enabled}).getPayload().toString());
  if (gps.gps !== Number(enabled) || gps.GNSSCapability !== (enabled ? 3 : 0) || gps.DashboardInfo !== 1) {
    throw Error('CarPlay adapter GPS capability settings are incorrect');
  }
}
assert.equal(settings.DashboardInfo,1);
assert.equal(settings.androidAutoSizeW,800);
const fields={MediaSongName:'Song',MediaSongDuration:180000,MediaSongPlayTime:12000};
const data=Buffer.concat([Buffer.from([1,0,0,0]),Buffer.from(JSON.stringify(fields)+'\0')]);
assert.deepEqual(new MediaData({},data).payload.media,fields);
console.log('PASS: media capability requested; dongle metadata parser preserves timing fields');
