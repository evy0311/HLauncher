import assert from 'node:assert/strict';
import {AudioData} from '../plugins/carplay/runtime/usb/vendor/node-carplay/dist/modules/messages/readable.js';
// A deliberately unaligned slice of a larger allocation, as USB buffers can be.
const backing=Buffer.alloc(1000,0x55), data=backing.subarray(17,17+20);
data.writeUInt32LE(4,0);data.writeFloatLE(1,4);data.writeUInt32LE(1,8);
[-32768,-1,0,32767].forEach((n,i)=>data.writeInt16LE(n,12+i*2));
const result=new AudioData({},data);
assert.deepEqual([...result.data],[-32768,-1,0,32767]);
assert.equal(result.data.byteLength,8);
console.log('PASS: PCM decoding respects USB buffer offset and payload length');
