// Headless Carlinkit adapter, using pinned node-carplay DongleDriver (MIT).
// Framing: type:u8 + payload_length:u32be + payload. Production stdout is video
// only (1=H264, 4=reset). The inherited PCM socket carries status and audio.
// stdin: JSON lines: single touch or two fixed-slot multitouch contacts (normalized x/y).
import fs from 'node:fs';
import {Socket} from 'node:net';
import {VideoOutput} from './video_output.mjs';
import readline from 'node:readline';
import {applyBranding} from './branding.mjs';
import { format } from 'node:util';
import { DongleDriver, DEFAULT_CONFIG, VideoData, AudioData, Plugged, Unplugged,
         SendTouch, SendMultiTouch, SendCommand, SendAudio, Command, MediaData, SoftwareVersion, ManufacturerInfo, BoxInfo, Opened,
         MessageType, SendableMessageWithPayload } from './vendor/node-carplay/dist/modules/index.js';
const write = process.stdout.write.bind(process.stdout);
const realtime = process.env.HLAUNCHER_CARPLAY_PCM_FD
  ? new Socket({fd:Number(process.env.HLAUNCHER_CARPLAY_PCM_FD),readable:false,writable:true})
  : process.stdout;
for (const name of ['log','debug','info','warn','error']) {
  console[name] = (...args) => process.stderr.write(format(...args)+'\n');
}
let shutting = false, driver = null, connected = false, down = false, multiDown = false;
let nightMode = process.env.HLAUNCHER_NIGHT_MODE === '1';
let appliedNightMode, nightModeWrite = Promise.resolve();
class SendNightMode extends SendableMessageWithPayload {
  type = MessageType.Command;
  constructor(enabled) {
    super();
    this.enabled = enabled;
  }
  getPayload() {
    const payload = Buffer.alloc(4);
    // Carlinkit host commands StartNightMode (16) and StopNightMode (17).
    payload.writeUInt32LE(this.enabled ? 16 : 17);
    return payload;
  }
}
function syncNightMode() {
  nightModeWrite = nightModeWrite.then(async () => {
    if (!connected || shutting || appliedNightMode === nightMode) return;
    const requested = nightMode;
    const sent = await driver.send(new SendNightMode(requested));
    if (sent === true) appliedNightMode = requested;
    console.error(JSON.stringify({state:'carplay_night_mode', night_mode:requested, sent:sent === true}));
  }).catch(error => console.error('CarPlay night mode:', String(error)));
  return nightModeWrite;
}
let videoPackets = 0, audioPackets = 0, lastStats = 0, lastSize = '', lastStatsVideo = 0, lastVideoAt = 0, maxVideoGap = 0;
function packet(type, payload) {
  if (shutting) return;
  const output = type === 1 || type === 4 ? process.stdout : realtime;
  const b = Buffer.isBuffer(payload) ? payload : Buffer.from(payload);
  if (b.length > 8*1024*1024 || output.writableLength > 2*1024*1024) {
    console.error('Bridge backlog/packet limit exceeded; restarting instead of accumulating latency');
    process.exit(75);
  }
  const h=Buffer.alloc(5); h[0]=type; h.writeUInt32BE(b.length,1);
  output.write(Buffer.concat([h,b]));
}
const video = new VideoOutput(process.stdout, packet, () => {
  if (driver && connected) void driver.send(new SendCommand('frame')).catch(() => {});
});
const lastPCM = new Map();
let maxAudioGap = 0, pcmPackets = 0;
const testStatuses=process.argv.includes('--self-test')?[]:null;
function status(state, extra={}) {
  if(testStatuses) testStatuses.push({state,...extra});
  packet(2,JSON.stringify({state,...extra}));
}
process.stdout.on('error',()=>{ if (realtime === process.stdout) process.exit(0); });
if (realtime !== process.stdout) realtime.on('error',()=>process.exit(0));
let touchChain=Promise.resolve(), touchSequence=0;
let voice={call_audio:false,siri:false,recording:false};
let micChain=Promise.resolve(),micPending=0,micBytes=0,micDropped=0,micErrors=0;
let mediaSchema='',mediaState='';
let brandingBusy=false, brandingPending=null, adapterOpened=false, initialBrandingOK=false;
async function brandAdapter(requestId=null) {
  if(brandingBusy){if(requestId!==null)brandingPending=requestId;return false;}
  brandingBusy=true;
  try {
    const result=await applyBranding(driver,(result,error)=>status('adapter_branding',{
      result:result==='sent'?'transferred':result,label:'HLauncher',request_id:requestId,error,
      verified:false,stage:adapterOpened?'opened':'initializing'}));
    return result;
  } finally {
    brandingBusy=false;
    if(brandingPending!==null && connected && adapterOpened){const id=brandingPending;brandingPending=null;void brandAdapter(id);}
  }
}
function requestBranding(id) {
  brandingPending=String(id || 'manual');
  status('adapter_branding',{result:'waiting',request_id:brandingPending,label:'HLauncher',verified:false});
  if(connected && adapterOpened){const pending=brandingPending;brandingPending=null;void brandAdapter(pending);}
}
function voiceChange(fields) {
  voice={...voice,...fields};status('projection_voice',{fields:voice});
}
function microphone(m) {
  if(!connected || !Object.values(voice).some(Boolean))return;
  if(typeof m.pcm!=='string' || m.pcm.length>856 || !/^[A-Za-z0-9+/]*={0,2}$/.test(m.pcm))return;
  const raw=Buffer.from(m.pcm,'base64');
  if(!raw.length || raw.length>640 || raw.length%2)return;
  if(micPending>=4){micDropped+=raw.length;return;}
  micPending++;
  micChain=micChain.then(async()=>{
    if(!connected || !Object.values(voice).some(Boolean)){micDropped+=raw.length;return;}
    const samples=Int16Array.from({length:raw.length/2},(_,i)=>raw.readInt16LE(i*2));
    try {
      if(await driver.send(new SendAudio(samples))===true)micBytes+=raw.length;
      else {micErrors++;micDropped+=raw.length;}
    } catch(e){micErrors++;micDropped+=raw.length;}
  }).finally(()=>{micPending--;});
}
function handleCommand(value) {
  console.error(JSON.stringify({state:'dongle_command',value}));
  if(value===3) status('host_ui_requested');
  if(value===1 || value===2)voiceChange({recording:value===1});
}
function handleMedia(message) {
    if (message.payload?.type === 100) {
      const call = message.payload.call;
      if (!call || ![0, 1, 2, 3, 4].includes(call.CallStatus)) return;
      const details = {};
      if (call.CallStatus !== 0) {
        if ([1, 2].includes(call.CallDirection)) details.incoming = call.CallDirection === 1;
        if (typeof call.CallName === 'string') details.name = call.CallName.slice(0, 128);
        if (typeof call.CallNumber === 'string') details.number = call.CallNumber.slice(0, 64);
      }
      status('projection_call', {call: details});
      return;
    }
    if(message.payload?.type===1 && message.payload.media && typeof message.payload.media==='object') {
      const fields=message.payload.media,keys=Object.keys(fields).slice(0,64);
      const schema=JSON.stringify(keys);
      if(schema!==mediaSchema){mediaSchema=schema;console.error(JSON.stringify({state:'projection_media_schema',keys}));}
      const states={};
      for(const key of keys)if(/state|status|phase|mode|event|error|command/i.test(key)) {
        const value=fields[key];
        if(typeof value==='boolean' || typeof value==='number' && Number.isFinite(value))states[key]=value;
        else if(typeof value==='string' && value.length<=32 && !/number|name|contact/i.test(key))states[key]=value;
      }
      const state=JSON.stringify(states);
      if(state!==mediaState){mediaState=state;console.error(JSON.stringify({state:'projection_media_state',fields:states}));}
      const media={};
      for(const key of ['MediaSongName','MediaArtistName','MediaAlbumName','MediaAPPName','MediaSongDuration','MediaSongPlayTime','MediaPlayStatus']) {
        const value=message.payload.media[key];
        if(value===null || typeof value==='number' && Number.isFinite(value)) media[key]=value;
        else if(typeof value==='string') media[key]=value.slice(0,512);
      }
      status('media_metadata',{media});
    }
}
function touch(m) {
  if (!m) return;
  if (!connected) {
    if(m.type==='button') status('button_usb_result',{sequence:m.sequence,command:m.command,result:'no_device'});
    return;
  }
  let message;
  if (m.type==='button') {
    if (!['next','prev','playOrPause','play','pause','siri','acceptPhone','rejectPhone'].includes(m.command)) return;
    message=new SendCommand(m.command);
  } else if (m.type==='touch') {
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
    if(m.type==='button' && started-queued>1000) { status('button_expired',{sequence:m.sequence}); return; }
    if(m.type==='button' && !connected) { status('button_usb_result',{sequence:m.sequence,command:m.command,result:'no_device'}); return; }
    const pending=setTimeout(()=>console.error(JSON.stringify({state:'touch_usb_pending',sequence,elapsed_ms:Date.now()-started})),1500);
    try {
      const result=await driver.send(message);
      if(m.type==='button') status('button_usb_result',{sequence:m.sequence,command:m.command,result:result===true?'sent':result===false?'failed':'no_device'});
      console.error(JSON.stringify({state:'touch_usb_complete',sequence,mode:m.type,result:result===true?'ok':result===false?'failed':'no_device',queue_ms:started-queued,transfer_ms:Date.now()-started}));
    } catch(e) {
      if(m.type==='button') status('button_usb_result',{sequence:m.sequence,command:m.command,result:'error'});
      console.error(JSON.stringify({state:'touch_usb_error',sequence,error:String(e)}));
    }
    finally {clearTimeout(pending);}
  });
}
if (!process.argv.includes('--self-test')) readline.createInterface({input:process.stdin}).on('line',line=>{
  if (line.length>1024) return;
  try { const m=JSON.parse(line);if(m.type==='adapter.branding') {
    requestBranding(m.request_id);
  }else if(m.type==='projection.appearance' && typeof m.night_mode==='boolean') {
    nightMode=m.night_mode;
    void syncNightMode();
  }else if(m.type==='microphone')microphone(m);else touch(m); } catch(e) { console.error('Bridge input:',String(e)); }
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
  const frames = [];
  const testOutput = {writableLength: 0};
  let requested = 0;
  const output = new VideoOutput(testOutput, (kind, data)=>frames.push([kind,data]), ()=>requested++);
  const sps = Buffer.from([0,0,1,0x67,1]), pps = Buffer.from([0,0,1,0x68,2]);
  const delta = Buffer.from([0,0,1,0x41,3]), idr = Buffer.from([0,0,1,0x65,4]);
  output.push(Buffer.concat([sps,pps]));
  testOutput.writableLength = 256 * 1024;
  output.push(delta);
  testOutput.writableLength = 0;
  output.push(delta);
  output.push(delta);
  output.push(idr);
  output.push(delta);
  if (requested !== 1 || output.dropped !== 3 || frames.map(([kind])=>kind).join() !== '1,4,1,1'
      || !frames[2][1].equals(Buffer.concat([sps,pps,idr]))) {
    throw Error('Video congestion did not recover at a decodable keyframe');
  }
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
  const mediaBody=Buffer.concat([Buffer.from([1,0,0,0]),Buffer.from(JSON.stringify({MediaSongName:'Metadata fixture',MediaSongDuration:180000,MediaSongPlayTime:12000})+'\0')]);
  handleMedia(new MediaData({},mediaBody));
  handleCommand(3);
  if (sent.length!==6 || sent[0].getPayload().readUInt32LE(0)!==14 ||
      sent[0].getPayload().readUInt32LE(4)!==2500 ||
      sent[0].getPayload().readUInt32LE(8)!==7500 ||
      sent[1].getPayload().readUInt32LE(4)!==10000 ||
      sent[1].getPayload().readUInt32LE(8)!==0) throw Error('Touch serialization failed');
  const fixture=process.env.CIVIC_CARPLAY_FIXTURE;
  if(fixture) packet(1,fs.readFileSync(fixture));
  for(const command of ['next','prev','playOrPause','play','pause','siri','acceptPhone','rejectPhone'])
    touch({type:'button',command,sequence:42});
  await touchChain;
  const codes=sent.slice(6).map(m=>m.getPayload().readUInt32LE(0));
  if(JSON.stringify(codes)!==JSON.stringify([204,205,203,201,202,5,300,301])) throw Error('Button serialization failed');
  connected=false;
  touch({type:'button',command:'next',sequence:100});
  connected=true;
  touch({type:'button',command:'prev',sequence:101});
  connected=false;
  await touchChain;
  connected=true;
  driver={send:async()=>false};
  touch({type:'button',command:'next',sequence:102});
  await touchChain;
  driver={send:async()=>{throw Error('USB fixture failure');}};
  touch({type:'button',command:'prev',sequence:103});
  await touchChain;
  const failures=testStatuses.filter(s=>s.state==='button_usb_result' && s.sequence>=100).map(s=>s.result);
  if(JSON.stringify(failures)!==JSON.stringify(['no_device','no_device','failed','error'])) throw Error('Button failure acknowledgement failed');
  const micSent=[];driver={send:async m=>{micSent.push(m);return true;}};
  const pcm=Buffer.alloc(6);pcm.writeInt16LE(-32768,0);pcm.writeInt16LE(0,2);pcm.writeInt16LE(32767,4);
  microphone({pcm:pcm.toString('base64')});await micChain;
  if(micSent.length)throw Error('Microphone sent without a projection request');
  handleCommand(1);microphone({pcm:pcm.toString('base64')});await micChain;
  if(micSent.length!==1)throw Error('Requested microphone was not forwarded');
  const mic=micSent[0].getPayload();
  if(mic.length!==18 || mic.readUInt32LE(0)!==5 || mic.readUInt32LE(8)!==3 || !mic.subarray(12).equals(pcm))throw Error('Microphone serialization failed');
  handleCommand(2);microphone({pcm:pcm.toString('base64')});await micChain;
  if(micSent.length!==1)throw Error('Microphone continued after recording stopped');
  const callHeader = Buffer.alloc(4);
  callHeader.writeUInt32LE(100);
  const callPacket = json => new MediaData(null, Buffer.concat([callHeader, Buffer.from(json)]));
  handleMedia(callPacket('{"CallStatus":4,"CallDirection":1,"CallName":"Test Caller","CallNumber":"+15550100","CallID":"private"}\0'));
  const call = testStatuses.at(-1);
  if (call.state !== 'projection_call' || call.call.name !== 'Test Caller' ||
      call.call.number !== '+15550100' || call.call.incoming !== true || 'CallID' in call.call)
    throw Error('Call metadata decoding failed');
  handleMedia(callPacket('{"CallName":"malformed test'));
  if (testStatuses.at(-1) !== call) throw Error('Malformed call data was forwarded');
  handleMedia(callPacket('{"CallStatus":0}'));
  if (testStatuses.at(-1).state !== 'projection_call' || Object.keys(testStatuses.at(-1).call).length)
    throw Error('Call metadata was retained after call end');
  const brandFiles=[];driver={send:async m=>{brandFiles.push(m);return true;}};
  connected=false;adapterOpened=false;
  requestBranding('queued-fixture');
  if(brandFiles.length || brandingPending!=='queued-fixture')throw Error('Branding request was lost before adapter readiness');
  connected=true;adapterOpened=true;
  const pendingBrand=brandingPending;brandingPending=null;
  await brandAdapter(pendingBrand);
  if(brandFiles.length!==6 || !testStatuses.some(s=>s.state==='adapter_branding' && s.request_id==='queued-fixture' && s.result==='transferred' && s.verified===false))throw Error('Queued branding was not transferred after readiness');
  const appearance = [];
  driver = {send: async message => { appearance.push(message.serialise()); return true; }};
  nightMode = true;
  await syncNightMode();
  await syncNightMode();
  nightMode = false;
  await syncNightMode();
  if (appearance.length !== 2 || appearance.some((bytes, index) =>
      bytes.readUInt32LE(4) !== 4 || bytes.readUInt32LE(8) !== MessageType.Command ||
      bytes.readUInt32LE(16) !== 16 + index)) {
    throw Error('CarPlay night mode did not send the expected USB commands');
  }
  status('self_test_ok',{touch_messages:sent.length});
  if (realtime !== process.stdout) {
    packet(3,Buffer.from('pcm fixture'));
    await new Promise(resolve=>realtime.write(Buffer.alloc(0),resolve));
  }
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
// Serialize protocol transfers, including the driver's parallel startup messages.
const originalSend=driver.send.bind(driver);let usbWrites=Promise.resolve();
driver.send=message=>{
  const sent=usbWrites.then(()=>originalSend(message));
  usbWrites=sent.catch(()=>{});return sent;
};
const usbTypes={}, mediaSubtypes={};
driver.on('protocol_message',m=>{
  usbTypes[m.type]=(usbTypes[m.type]||0)+1;
  if(m.type===0x2a) {
    mediaSubtypes[m.subtype]=(mediaSubtypes[m.subtype]||0)+1;
    if(mediaSubtypes[m.subtype]===1) console.error(JSON.stringify({state:'media_packet_seen',...m}));
  }
});
driver.on('failure',()=>{status('usb_failure');process.exit(75);});
driver.on('message',message=>{
  if(message instanceof Command) {handleCommand(message.value);}
  else if(message instanceof SoftwareVersion) {
    const version=String(message.version).replace(/\0/g,'');
    console.error(JSON.stringify({state:'dongle_software_version',version}));
    status('dongle_software_version',{version});
  }
  else if(message instanceof ManufacturerInfo) {
    console.error(JSON.stringify({state:'dongle_manufacturer_info',a:message.a,b:message.b}));
  }
  else if(message instanceof BoxInfo) {
    console.error(JSON.stringify({state:'dongle_box_info',settings:message.settings}));
  }
  else if(message instanceof Opened) {
    adapterOpened=true;
    if(brandingPending!==null){const pending=brandingPending;brandingPending=null;void brandAdapter(pending);}
    else if(!initialBrandingOK)void brandAdapter();
    console.error(JSON.stringify({state:'dongle_opened',width:message.width,height:message.height,fps:message.fps,iBox:message.iBox,phoneMode:message.phoneMode}));
  }
  else if(message instanceof MediaData) { handleMedia(message); }
  else if(message instanceof Plugged) {
    video.reset();lastPCM.clear();status('phone_connected',{phone_type:message.phoneType});
    appliedNightMode = undefined;
    void syncNightMode();
  }
  else if(message instanceof Unplugged) { lastPCM.clear();voiceChange({call_audio:false,siri:false,recording:false});status('phone_disconnected'); }
  else if(message instanceof VideoData && message.data?.length) {
    videoPackets++;
    const receivedAt=Date.now();
    if(lastVideoAt) maxVideoGap=Math.max(maxVideoGap,receivedAt-lastVideoAt);
    lastVideoAt=receivedAt;
    const size=`${message.width}x${message.height}`;
    if(size!==lastSize) {lastSize=size;status('video_size',{width:message.width,height:message.height});}
    if (realtime === process.stdout) packet(1,message.data);
    else video.push(message.data);
  } else if(message instanceof AudioData) {
    audioPackets++;
    if(message.data?.length) {
      const now=performance.now(), stream=message.audioType;
      if(lastPCM.has(stream))maxAudioGap=Math.max(maxAudioGap,now-lastPCM.get(stream));
      lastPCM.set(stream,now);
      pcmPackets++;
      const h=Buffer.alloc(12);h.writeUInt32LE(message.decodeType,0);
      h.writeUInt32LE(message.audioType,4);h.writeFloatLE(message.volume,8);
      packet(3,Buffer.concat([h,Buffer.from(message.data.buffer,message.data.byteOffset,message.data.byteLength)]));
    } else {
      lastPCM.delete(message.audioType);
      if(message.command===4 || message.command===5)voiceChange({call_audio:message.command===4});
      if(message.command===8 || message.command===9)voiceChange({siri:message.command===8});
      status('audio_control',{command:message.command,decode_type:message.decodeType,audio_type:message.audioType,volume:message.volume,volume_duration:message.volumeDuration});
    }
  }
  const now=Date.now();
  if(now-lastStats>=1000) {
    const elapsed=lastStats ? now-lastStats : 0;
    status('stream_stats',{video_packets:videoPackets,video_packets_delta:videoPackets-lastStatsVideo,window_ms:elapsed,video_gap_max_ms:maxVideoGap,video_packets_dropped:video.dropped,audio_packets:audioPackets,pcm_packets:pcmPackets,pcm_gap_max_ms:Math.round(maxAudioGap),audio_forwarding:'launcher_hdmi',usb_message_types:usbTypes,media_subtypes:mediaSubtypes,mic_bytes:micBytes,mic_dropped:micDropped,mic_errors:micErrors});
    lastStats=now;lastStatsVideo=videoPackets;maxVideoGap=0;maxAudioGap=0;
  }
});
const fps=process.env.CIVIC_CARPLAY_FPS === '60' ? 60 : 30;
const config={...DEFAULT_CONFIG,width:800,height:480,fps,
  boxName:'HLauncher',micType:'os',audioTransferMode:false,nightMode};
await driver.initialise(device);
initialBrandingOK=await brandAdapter();
appliedNightMode=config.nightMode;
await driver.start(config);connected=true;
void syncNightMode();
if(adapterOpened && brandingPending!==null){const pending=brandingPending;brandingPending=null;void brandAdapter(pending);}
status('metadata_requested',{DashboardInfo:1});
status('dongle_ready',{width:800,height:480,fps:config.fps,audio_forwarding:'launcher_hdmi'});
const keyframe=setInterval(()=>{
  void driver.send(new SendCommand('frame'));
  if (appliedNightMode !== nightMode) void syncNightMode();
},5000);
setTimeout(()=>driver.send(new SendCommand('wifiPair')),15000).unref();
process.on('exit',()=>clearInterval(keyframe));
