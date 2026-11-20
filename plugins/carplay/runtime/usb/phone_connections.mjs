// CCPA protocol research: host type 0x11, NUL-terminated paired peer MAC.
// USB transfer success is not evidence that the phone connected.
import {createHash} from 'node:crypto';
import {SendCommand,SendableMessageWithPayload} from './vendor/node-carplay/dist/modules/index.js';
export function address(value) {
  return typeof value==='string' && /^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$/i.test(value)
    && value!=='00:00:00:00:00:00' ? value.toUpperCase() : '';
}
export class SelectPhone extends SendableMessageWithPayload {
  type=0x11;
  constructor(peer) {super();this.peer=address(peer);if(!this.peer)throw Error('Invalid phone address');}
  getPayload() {return Buffer.from(this.peer+'\0','ascii');}
}
export class EnableAutoConnect extends SendableMessageWithPayload {
  type=0x19;
  getPayload() {return Buffer.from(JSON.stringify({autoConn:true}),'utf8');}
}
export class DisconnectPhone extends SendableMessageWithPayload {
  type=0x0f;
  getPayload() {return Buffer.alloc(0);}
}
export class PhoneConnections {
  constructor(send, report, favorite='', clock=()=>performance.now()) {
    this.send=send;this.report=report;this.clock=clock;
    this.favorite=address(favorite);this.paired=new Set();this.ready=false;
    this.connected=false;this.peer='';this.peerRevision=0;this.pending=null;this.autoTried=false;this.generation=0;
  }
  result(request,result,reason='') {
    this.report('phone_connection',{request_id:request.id,phone_id:createHash('sha256').update(request.peer).digest('hex').slice(0,24),automatic:request.automatic,result,reason});
  }
  finish(result,reason='') {
    const request=this.pending;if(!request)return;
    this.pending=null;this.result(request,result,reason);
    if(request.automatic && result==='failed' && this.ready) {
      // Resume the driver's normal connection trigger once; never loop/reboot.
      void this.send(new SendCommand('wifiConnect')).then(sent=>{
        this.report('phone_connection_fallback',{request_id:request.id,result:sent===true?'requested':'failed'});
      }).catch(()=>this.report('phone_connection_fallback',{request_id:request.id,result:'failed'}));
    }
  }
  setFavorite(peer) {this.favorite=address(peer);this.autoTried=true;}
  async request(peer,id,automatic=false) {
    peer=address(peer);
    if(!peer || typeof id!=='string' || !id.length || id.length>80)return;
    const request={peer,id,automatic,generation:this.generation,stage:'queued',until:this.clock()+10000};
    if(this.pending) {this.result(request,'failed','busy');return;}
    if(!this.ready || !this.paired.has(peer)) {this.result(request,'failed','not_paired');return;}
    if(this.connected && this.peer===peer) {this.result(request,'connected');return;}
    if(automatic && this.connected) {this.result(request,'skipped','session_active');return;}
    this.pending=request;
    if(!automatic)this.autoTried=true;
    if(this.connected) {
      request.stage='disconnecting';this.result(request,'disconnecting');
      try {
        if(await this.send(new DisconnectPhone())!==true && this.pending===request)this.finish('failed','disconnect_send_failed');
      }catch {if(this.pending===request)this.finish('failed','disconnect_send_failed');}
    }else await this.select(request);
  }
  async select(request) {
    if(this.pending!==request || request.generation!==this.generation)return;
    request.minPeerRevision=this.peerRevision;
    request.stage='connecting';request.until=this.clock()+30000;this.result(request,'connecting');
    try {
      if(await this.send(new EnableAutoConnect())!==true) {
        if(this.pending===request)this.finish('failed','autoconnect_send_failed');
        return;
      }
      if(this.pending!==request || request.generation!==this.generation)return;
      if(await this.send(new SelectPhone(request.peer))!==true && this.pending===request)this.finish('failed','connect_send_failed');
    }catch {if(this.pending===request)this.finish('failed','connect_send_failed');}
  }
  async observe(settings) {
    if(!settings || typeof settings!=='object')return;
    if(Array.isArray(settings.DevList))this.paired=new Set(settings.DevList.slice(0,32).map(item=>address(item?.id)).filter(Boolean));
    const peer=address(settings.btMacAddr);if(peer){this.peer=peer;this.peerRevision++;}
    this.confirm();
    await this.autoConnect();
  }
  confirm() {
    if(this.pending?.stage==='connecting' && this.connected && this.peer===this.pending.peer && this.peerRevision>this.pending.minPeerRevision)this.finish('connected');
  }
  plugged() {this.connected=true;this.confirm();}
  async unplugged() {
    this.connected=false;this.peer='';
    if(this.pending?.stage==='disconnecting')await this.select(this.pending);
  }
  async autoConnect() {
    if(this.pending || !this.ready || this.autoTried || !this.favorite || !this.paired.has(this.favorite))return;
    this.autoTried=true;
    await this.request(this.favorite,'favorite',true);
  }
  tick() {
    if(this.pending && this.clock()>=this.pending.until)this.finish('failed',this.pending.stage==='disconnecting'?'disconnect_timeout':'connection_timeout');
  }
  close() {this.generation++;this.ready=false;this.finish('failed','adapter_disconnected');}
}
