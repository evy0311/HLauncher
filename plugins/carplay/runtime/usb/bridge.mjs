// Headless Carlinkit adapter, using pinned node-carplay DongleDriver (MIT).
// stdout: type:u8 + payload_length:u32be + payload; type1=H264, type2=JSON status.
// stdin: JSON lines: single touch or two fixed-slot multitouch contacts (normalized x/y).
import fs from 'node:fs';
import readline from 'node:readline';
import { format } from 'node:util';
import { DongleDriver, DEFAULT_CONFIG, VideoData, AudioData, Plugged, Unplugged,
         SendTouch, SendMultiTouch, SendCommand, Command } from './vendor/node-carplay/dist/modules/index.js';
const write = process.stdout.write.bind(process.stdout);
for (const name of ['log','debug','info','warn','error']) {
  console[name] = (...args) => process.stderr.write(format(...args)+'\n');
}
let shutting = false, driver = null, connected = false, down = false, multiDown = false;
let videoPackets = 0, audioPackets = 0, lastStats = 0, lastSize = '', lastStatsVideo = 0, lastVideoAt = 0, maxVideoGap = 0;
function packet(type, payload) {
  if (shutting) return;
  const b = Buffer.isBuffer(payload) ? payload : Buffer.from(payload);
  if (b.length > 8*1024*1024 || process.stdout.writableLength > 2*1024*1024) {
    console.error('Bridge backlog/packet limit exceeded; restarting instead of accumulating latency');
    process.exit(75);
  }
  const h=Buffer.alloc(5); h[0]=type; h.writeUInt32BE(b.length,1);
  write(Buffer.concat([h,b]));
}
function status(state, extra={}) { packet(2,JSON.stringify({state,...extra})); }
process.stdout.on('error',()=>process.exit(0));
let touchChain=Promise.resolve(), touchSequence=0;
function handleCommand(value) {
  console.error(JSON.stringify({state:'dongle_command',value}));
  if(value===3) status('host_ui_requested');
}
function touch(m) {
  if (!m || !connected) return;
  let message;
  if (m.type==='touch') {
    if (![14,15,16].includes(m.action) || !Number.isFinite(m.x) || !Number.isFinite(m.y)) return;
    message=new SendTouch(Math.max(0,Math.min(1,m.x)),Math.max(0,Math.min(1,m.y)),m.action);
    down=m.action!==16;
  } else if (m.type==='multitouch') {
    if (!Array.isArray(m.touches) || m.touches.length!==2 || m.touches.some(t=>
        !t || ![0,1,2].includes(t.action) || !Number.isFinite(t.x) || !Number.isFinite(t.y))) return;
    const touches=m.touches.map(t=>({action:t.action,x:Math.max(0,Math.min(1,t.x)),y:Math.max(0,Math.min(1,t.y))}));
    message=new SendMultiTouch(touches);
    multiDown=touches.some(t=>t.action!==0);
  } else return;
  const sequence=++touchSequence, queued=Date.now();
  console.error(JSON.stringify({state:'touch_node_received',sequence,mode:m.type,action:m.action,touches:m.touches,x:m.x,y:m.y,payload:message.getPayload().toString('hex')}));
  touchChain=touchChain.then(async()=>{
    const started=Date.now();
    const pending=setTimeout(()=>console.error(JSON.stringify({state:'touch_usb_pending',sequence,elapsed_ms:Date.now()-started})),1500);
    try {
      const result=await driver.send(message);
      console.error(JSON.stringify({state:'touch_usb_complete',sequence,mode:m.type,result:result===true?'ok':result===false?'failed':'no_device',queue_ms:started-queued,transfer_ms:Date.now()-started}));
    } catch(e) {console.error(JSON.stringify({state:'touch_usb_error',sequence,error:String(e)}));}
    finally {clearTimeout(pending);}
  });
}
if (!process.argv.includes('--self-test')) readline.createInterface({input:process.stdin}).on('line',line=>{
  if (line.length>1024) return;
  try { touch(JSON.parse(line)); } catch(e) { console.error('Touch input:',String(e)); }
});
async function stop() {
  if (shutting) return; shutting=true;
  if (driver) {
    await touchChain;
    if (down) await driver.send(new SendTouch(0,0,16));
    if (multiDown) await driver.send(new SendMultiTouch([{x:0,y:0,action:0},{x:0,y:0,action:0}]));
    await driver.close().catch(()=>{});
  }
  process.exit(0);
}
process.on('SIGTERM',stop);process.on('SIGINT',stop);
if (!process.argv.includes('--self-test')) process.stdin.on('end',stop);
process.on('uncaughtException',e=>{ console.error(e);process.exit(1); });
process.on('unhandledRejection',e=>{ console.error(e);process.exit(1); });
if (process.argv.includes('--self-test')) {
  const sent=[];driver={send:async m=>{sent.push(m);return true;}};connected=true;
  touch({type:'touch',action:14,x:0.25,y:0.75});
  touch({type:'touch',action:15,x:2,y:-1});
  touch({type:'touch',action:16,x:0.5,y:0.5});
  touch({type:'touch',action:99,x:0,y:0});
  touch({type:'multitouch',touches:[{x:.2,y:.4,action:1},{x:.8,y:.6,action:1}]});
  touch({type:'multitouch',touches:[{x:.1,y:.4,action:2},{x:.9,y:.6,action:2}]});
  touch({type:'multitouch',touches:[{x:.1,y:.4,action:0},{x:.9,y:.6,action:0}]});
  touch({type:'multitouch',touches:[{x:NaN,y:0,action:1},{x:1,y:1,action:1}]});
  await touchChain;
  const multi=sent[3]?.getPayload();
  if (!multi || multi.length!==32 || Math.abs(multi.readFloatLE(0)-.2)>.00001 ||
      multi.readUInt32LE(8)!==1 || multi.readUInt32LE(12)!==0 ||
      Math.abs(multi.readFloatLE(16)-.8)>.00001 || multi.readUInt32LE(28)!==1 ||
      sent[5].getPayload().readUInt32LE(24)!==0) throw Error('Multitouch serialization failed');
  handleCommand(3);
  if (sent.length!==6 || sent[0].getPayload().readUInt32LE(0)!==14 ||
      sent[0].getPayload().readUInt32LE(4)!==2500 ||
      sent[0].getPayload().readUInt32LE(8)!==7500 ||
      sent[1].getPayload().readUInt32LE(4)!==10000 ||
      sent[1].getPayload().readUInt32LE(8)!==0) throw Error('Touch serialization failed');
  const fixture=process.env.CIVIC_CARPLAY_FIXTURE;
  if(fixture) packet(1,fs.readFileSync(fixture));
  status('self_test_ok',{touch_messages:sent.length});
  await new Promise(resolve=>write(Buffer.alloc(0),resolve));
  process.exit(0);
}
const {webusb}=await import('usb');
if(process.argv.includes('--check')) {
  const {getDeviceList}=await import('usb');
  const devices=getDeviceList().filter(d=>DongleDriver.knownDevices.some(f=>
    d.deviceDescriptor.idVendor===f.vendorId && d.deviceDescriptor.idProduct===f.productId));
  console.error(JSON.stringify({known_dongles:devices.map(d=>({vendor:d.deviceDescriptor.idVendor,
    product:d.deviceDescriptor.idProduct,bus:d.busNumber,address:d.deviceAddress}))}));
  process.exit(devices.length?0:2);
}
status('waiting_dongle');
let device;
while(!device && !shutting) {
  try {device=await webusb.requestDevice({filters:DongleDriver.knownDevices});}
  catch(e) {console.error('Waiting for imported dongle:',String(e));}
  if(!device) await new Promise(r=>setTimeout(r,3000));
}
if(shutting) process.exit(0);
await device.open();
// Remote USB exporters may not survive a USB reset. Default: no automatic reset.
if(process.env.CIVIC_CARPLAY_RESET==='1') {
  status('resetting_dongle');await device.reset();await device.close();
  await new Promise(r=>setTimeout(r,3000));
  device=await webusb.requestDevice({filters:DongleDriver.knownDevices});await device.open();
}
driver=new DongleDriver();
driver.on('failure',()=>{status('usb_failure');process.exit(75);});
driver.on('message',message=>{
  if(message instanceof Command) {handleCommand(message.value);}
  else if(message instanceof Plugged) { status('phone_connected',{phone_type:message.phoneType}); }
  else if(message instanceof Unplugged) { status('phone_disconnected'); }
  else if(message instanceof VideoData && message.data?.length) {
    videoPackets++;
    const receivedAt=Date.now();
    if(lastVideoAt) maxVideoGap=Math.max(maxVideoGap,receivedAt-lastVideoAt);
    lastVideoAt=receivedAt;
    const size=`${message.width}x${message.height}`;
    if(size!==lastSize) {lastSize=size;status('video_size',{width:message.width,height:message.height});}
    packet(1,message.data);
  } else if(message instanceof AudioData) { audioPackets++; }
  const now=Date.now();
  if(now-lastStats>=1000) {
    const elapsed=lastStats ? now-lastStats : 0;
    status('stream_stats',{video_packets:videoPackets,video_packets_delta:videoPackets-lastStatsVideo,window_ms:elapsed,video_gap_max_ms:maxVideoGap,audio_packets:audioPackets,audio_routed:false});
    lastStats=now;lastStatsVideo=videoPackets;maxVideoGap=0;
  }
});
const fps=Number(process.env.CIVIC_CARPLAY_FPS || 15);
const config={...DEFAULT_CONFIG,width:800,height:480,fps:Number.isFinite(fps)?Math.max(5,Math.min(60,fps)):15,
  boxName:'CivicCarPlay',micType:'box',audioTransferMode:false};
await driver.initialise(device);await driver.start(config);connected=true;
status('dongle_ready',{width:800,height:480,fps:config.fps,audio_routed:false});
const keyframe=setInterval(()=>driver.send(new SendCommand('frame')),5000);
setTimeout(()=>driver.send(new SendCommand('wifiPair')),15000).unref();
process.on('exit',()=>clearInterval(keyframe));
