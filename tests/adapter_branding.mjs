import assert from 'node:assert/strict';
import {brandingMessages,applyBranding} from '../plugins/carplay/runtime/usb/branding.mjs';
const messages=brandingMessages();
assert.deepEqual(messages.map(m=>m.fileName),['/etc/oem_icon.png','/etc/icon_120x120.png','/etc/icon_180x180.png','/etc/icon_256x256.png','/etc/box_name','/etc/airplay.conf']);
for(let i=0;i<4;i++) {
  const m=messages[i],p=m.getPayload(),n=p.readUInt32LE(0);
  assert.equal(p.subarray(4,4+n-1).toString(),m.fileName);
  assert.equal(p[4+n-1],0);
  assert.equal(p.readUInt32LE(4+n),m.content.length);
  assert(p.subarray(8+n).equals(m.content));
  assert.equal(m.content.readUInt32BE(16),[256,120,180,256][i]);
}
assert.equal(messages[4].content.toString(),'HLauncher');
assert.match(messages[5].content.toString(),/^oemIconLabel = HLauncher$/m);
assert.match(messages[5].content.toString(),/^oemIconVisible = 1$/m);
assert.match(messages[5].content.toString(),/^oemIconPath = \/etc\/oem_icon.png$/m);
const sent=[],states=[];
assert(await applyBranding({send:async m=>{sent.push(m.fileName);return true;}},state=>states.push(state)));
assert.equal(sent.length,6);assert.deepEqual(states,['sending','sent']);
for(const result of [false,null,'throw']) {
  let calls=0;const reports=[];
  assert.equal(await applyBranding({send:async()=>{calls++;if(result==='throw')throw Error('Disconnected');return result;}},state=>reports.push(state)),false);
  assert.equal(calls,1);assert.deepEqual(reports,['sending','failed']);
}
console.log('Adapter branding: serialization, order and failure handling passed');
