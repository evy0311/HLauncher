import assert from 'node:assert/strict';
import {PhoneConnections,SelectPhone,DisconnectPhone,EnableAutoConnect} from '../plugins/carplay/runtime/usb/phone_connections.mjs';
const a='02:00:00:00:00:01', b='02:00:00:00:00:02';
const packet=new SelectPhone(a).serialise();
assert.equal(packet.readUInt32LE(0),0x55aa55aa);
assert.equal(packet.readUInt32LE(4),18);
assert.equal(packet.readUInt32LE(8),0x11);
assert.equal(packet.readUInt32LE(12),~0x11>>>0);
assert.equal(packet.subarray(16).toString(),a+'\0');
assert.equal(new DisconnectPhone().serialise().length,16);
assert.deepEqual(JSON.parse(new EnableAutoConnect().getPayload()),{autoConn:true});
for(const value of ['',null,'garbage','00:00:00:00:00:00',a+'\0'])assert.throws(()=>new SelectPhone(value));
function fixture(favorite='') {
  let now=0;const sent=[],events=[];
  const controller=new PhoneConnections(async m=>{sent.push(m);return true;},(state,event)=>events.push({state,...event}),favorite,()=>now);
  controller.ready=true;
  return {controller,sent,events,advance(ms){now+=ms;controller.tick();}};
}
{
  const {controller:c,sent,events}=fixture();
  await c.request(a,'unknown');assert.equal(events.at(-1).reason,'not_paired');assert.equal(sent.length,0);
  await c.observe({DevList:[{id:a},{id:b}]});
  await c.request(a,'manual');
  assert.deepEqual(sent.map(m=>m.type),[0x19,0x11]);
  assert.equal(events.at(-1).result,'connecting');
  c.plugged();assert.equal(events.at(-1).result,'connecting');
  await c.observe({btMacAddr:b});assert.equal(events.at(-1).result,'connecting');
  await c.observe({btMacAddr:a});assert.equal(events.at(-1).result,'connected');
  assert.ok(!JSON.stringify(events).includes(a));
  assert.ok(!JSON.stringify(events).includes(b));
}
{
  const {controller:c,sent,events}=fixture();
  await c.observe({DevList:[{id:a},{id:b}],btMacAddr:b});c.plugged();
  await c.request(a,'switch');assert.deepEqual(sent.map(m=>m.type),[0x0f]);
  assert.equal(events.at(-1).result,'disconnecting');
  await c.unplugged();assert.deepEqual(sent.map(m=>m.type),[0x0f,0x19,0x11]);
  await c.observe({btMacAddr:b});c.plugged();assert.equal(events.at(-1).result,'connecting');
  await c.observe({btMacAddr:a});assert.equal(events.at(-1).result,'connected');
}
{
  const {controller:c,sent,events,advance}=fixture(a);
  await c.observe({DevList:[{id:a}]});assert.deepEqual(sent.map(m=>m.type),[0x19,0x11]);
  await c.observe({DevList:[{id:a}]});assert.equal(sent.length,2);
  advance(30001);assert.equal(events.at(-1).reason,'connection_timeout');
  await c.observe({DevList:[{id:a}]});assert.equal(sent.length,3);
  assert.equal(sent.at(-1).getPayload().readUInt32LE(),1002);
}
{
  const {controller:c,sent,events}=fixture(a);
  c.connected=true;c.peer=b;
  await c.observe({DevList:[{id:a},{id:b}]});
  assert.equal(sent.length,0);assert.equal(events.at(-1).result,'skipped');
  await c.unplugged();await c.autoConnect();assert.equal(sent.length,0);
}
{
  const {controller:c,sent,events,advance}=fixture();
  await c.observe({DevList:[{id:a}],btMacAddr:b});c.plugged();
  await c.request(a,'disconnect-timeout');advance(10001);
  assert.equal(events.at(-1).reason,'disconnect_timeout');
  await c.unplugged();assert.deepEqual(sent.map(m=>m.type),[0x0f]);
}
{
  const {controller:c,sent,events}=fixture();await c.observe({DevList:[{id:a}]});
  c.send=async()=>false;await c.request(a,'send-failed');
  assert.equal(events.at(-1).result,'failed');assert.equal(events.at(-1).reason,'autoconnect_send_failed');
  c.setFavorite(a);await c.autoConnect();assert.equal(sent.length,0);
}
{
  const {controller:c,events}=fixture();await c.observe({DevList:[{id:a}]});
  let release;c.send=()=>new Promise(resolve=>{release=resolve;});
  const request=c.request(a,'stale');c.close();release(true);await request;
  assert.equal(events.at(-1).reason,'adapter_disconnected');assert.equal(c.pending,null);
}
{
  const {controller:c,events}=fixture();
  await c.observe({DevList:[{id:a}],btMacAddr:a});
  await c.request(a,'stale-identity');c.plugged();
  assert.equal(events.at(-1).result,'connecting');
  await c.observe({btMacAddr:a});assert.equal(events.at(-1).result,'connected');
}
console.log('PASS: targeted phone wire format, peer confirmation, switching, favorite policy, timeout and stale USB cancellation');
