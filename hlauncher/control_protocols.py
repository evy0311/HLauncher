"""Bounded AVRCP target and HFP extension handling; no audio ownership."""
import hashlib
import re
import struct
import time
from .projection_voice import normalize_call

OPERATIONS = {0x44:'play',0x46:'pause',0x45:'stop',0x4b:'next',0x4c:'previous'}
# BlueALSA 4 owns these commands even when its external dispatcher is open.
BUILTIN = {'+BRSF','+CIND','+CMER','+BIA','+NREC','+VGM','+VGS','+BTRH',
           '+BCC','+BCS','+BAC','+ANDROID','+IPHONEACCEV','+XAPL'}


class HfpProjection:
    """Mirror confirmed call audio and Siri state."""
    def __init__(self):
        self.previous=None
        self.call_started = None

    def update(self, fields):
        current=(fields.get('call_audio') is True,fields.get('siri') is True)
        if not current[0]:
            self.call_started = None
        elif self.call_started is None:
            self.call_started = time.monotonic()
        messages=[]
        for i,prefix in enumerate(('+CIEV:2,','+BVRA:')):
            if self.previous is None:
                # Clear a previous call lease, but do not cancel a radio-originated
                # BVRA request while the dongle is starting Siri.
                if i==0 or current[i]:messages.append(prefix+str(int(current[i])))
            elif current[i]!=self.previous[i]:messages.append(prefix+str(int(current[i])))
        self.previous=current
        return messages

def hfp_observation(raw):
    """Describe incoming commands without retaining dial strings or other values."""
    text=raw[:512].decode('ascii',errors='replace').strip().upper()
    if text.startswith('ATD'):
        command='ATD [destination withheld]'
    elif text.startswith('AT+'):
        match=re.match(r'AT\+[A-Z0-9]+',text)
        command=match[0] if match else 'Unrecognized AT command'
        if text in ('AT+BVRA=0','AT+BVRA=1','AT+APLSIRI?'):
            command=text
    elif text=='ATA':command='ATA'
    else:command='Unrecognized HFP message'
    return dict(source='hfp',summary=command,bytes=len(raw))

def avrcp_observation(raw,reply=None):
    """Keep the protocol header and operation, never metadata or arbitrary operands."""
    summary='AVCTP header '+raw[:6].hex()
    if len(raw)>=8 and raw[5]==0x7c:
        summary=f'Operation 0x{raw[6]&0x7f:02x} '+('release' if raw[6]&0x80 else 'press')
    elif len(raw)>=13 and raw[5]==0:
        summary=f'AVRCP PDU 0x{raw[9]:02x}'
        if raw[9] in (0x10,0x31) and len(raw)>13:
            summary+=f' / selector {raw[13]}'
    if reply and len(reply)>=6:summary+=f' / reply 0x{reply[3]:02x}'
    return dict(source='avrcp',summary=summary,bytes=len(raw))

def hfp_request(raw, voice=None):
    """Return (responses, event). Never log dial strings or invent call state."""
    if len(raw)>512: return (), None
    text=raw.decode('ascii',errors='replace').strip().upper()
    if not text.startswith('AT'): return (), None
    cmd=text[2:]
    name=cmd.split('=',1)[0].rstrip('?')
    if name in BUILTIN: return (), None
    if cmd == '+APLSIRI?': return ('+APLSIRI:1','OK'), None
    if cmd in ('+APLEFM=1','+APLEFM=0','+APLNRSTAT=1','+APLNRSTAT=0',
               '+CLIP=1','+CLIP=0','+CCWA=1','+CCWA=0','+CMEE=1','+CMEE=0'):
        return ('OK',), None
    if cmd in ('+BVRA=1','+BVRA=0'):
        return ('OK',), ('voice_assistant','activate' if cmd.endswith('1') else 'deactivate')
    if cmd=='A': return ('OK',), ('answer','trigger')
    if cmd=='+CHUP': return ('OK',), ('hang_up','trigger')
    # Observe these physical requests even though projection has no dial API.
    if cmd.startswith('D'): return ('ERROR',), ('dial','trigger')
    if cmd=='+BLDN': return ('ERROR',), ('redial','trigger')
    if cmd == '+CLCC':
        if not voice or voice.get('call_audio') is not True:
            return ('OK',), None
        details = normalize_call(voice.get('call'))
        number = details.get('number', '')
        label = details.get('name')
        if not label and not number:
            label = 'CarPlay Call' if voice.get('plugin') == 'carplay' else 'Projection Call'
        # HFP requires a direction. Use outgoing as the neutral default when
        # the adapter reports only call audio, with no incoming call event.
        direction = int(details.get('incoming', False))
        number_type = 145 if number.startswith('+') else 129
        listing = f'+CLCC: 1,{direction},0,0,0,"{number}",{number_type}'
        if label:
            listing += f',"{label}"'
        return (listing, 'OK'), None
    if cmd in ('+CNUM','+COPS?'): return ('OK',), None
    # Dial/redial needs a destination-aware telephony API. Never reinterpret it as answer.
    return ('ERROR',), None

class AvrcpTarget:
    def __init__(self,max_packet_size=512):
        self.subscriptions={}
        self.media={}
        self.max_packet_size=max(48,min(512,max_packet_size))
        self.pending=None

    def uid(self):
        if not self.media.get('title'):return b'\xff'*8
        return hashlib.sha256((self.media.get('title','')+'\0'+self.media.get('artist','')).encode()).digest()[:8]

    def play_state(self):
        # The input bridge is idle without a media owner, not in a playback error.
        # Preserve explicit unknown state when an active owner cannot report it.
        if not self.media or self.media.get('available') is False:return 0
        return {'playing':1,'paused':2,'stopped':0}.get(self.media.get('playback_state'),255)

    def notification(self,event):
        return bytes([event,self.play_state()]) if event==1 else bytes([event])+self.uid()

    @staticmethod
    def vendor(header,pdu,payload,ctype=12,packet_type=0):
        return header+bytes([ctype,0x48,0])+b'\x00\x19\x58'+bytes([pdu,packet_type])+struct.pack('!H',len(payload))+payload

    def receive(self,data):
        """One AVCTP single packet, maximum 512 bytes; returns (reply,event)."""
        if not 6<=len(data)<=512 or data[0]&3 or (data[0]>>2)&3:return None,None
        if data[1:3]!=b'\x11\x0e':return bytes([data[0]|3])+data[1:3],None
        header=bytes([data[0]|2])+data[1:3]
        ctype,subunit,opcode=data[3:6]
        if opcode==0x7c and ctype==0 and len(data)>=8:
            op,count=data[6:8]
            if count!=len(data)-8:return None,None
            name=OPERATIONS.get(op&0x7f) if subunit==0x48 and count==0 else None
            reply=header+bytes([9 if name else 10,subunit,opcode])+data[6:]
            return reply, (name,'up' if op&0x80 else 'down') if name else None
        if opcode in (0x30,0x31) and ctype==1 and len(data)==11:
            payload=(bytes([12,subunit,opcode,7,0x48,0,0x19,0x58]) if opcode==0x30 else bytes([12,subunit,opcode,data[6],0x48,0xff,0xff,0xff]))
            return header+payload,None
        if opcode!=0 or subunit!=0x48 or ctype not in (0,1,3) or len(data)<13:return header+bytes([8,subunit,opcode])+data[6:],None
        company,pdu,packet,length=data[6:9],data[9],data[10],struct.unpack('!H',data[11:13])[0]
        if company!=b'\x00\x19\x58':return header+bytes([8,subunit,opcode]),None
        if packet!=0 or length!=len(data)-13:return None,None
        args=data[13:]
        reject=lambda status:(self.vendor(header,pdu,bytes([status]),10),None)
        expected={0x10:1,0x11:1,0x12:1,0x13:1,0x14:0,0x15:1,0x16:1,
                  0x17:1,0x18:1,0x20:1,0x30:1,0x31:3,0x40:0,0x41:0}
        if pdu not in expected or ctype!=expected[pdu]:return reject(0)
        if pdu==0x10 and len(args)==1:
            if args[0]==2:payload=b'\x02\x01\x00\x19\x58'
            elif args[0]==3:payload=b'\x03\x02\x01\x02'
            else:return reject(1)
        elif pdu==0x11:
            # ListPlayerApplicationSettingAttributes: no remotely adjustable
            # repeat/shuffle/EQ settings. Honda asks this during connection setup.
            # Return an empty successful list, matching BlueZ's no-settings path.
            if args:return reject(1)
            payload=b'\x00'
        elif pdu in (0x12,0x13,0x14,0x15,0x16):
            return reject(1)  # No advertised player settings to read or modify.
        elif pdu==0x17:
            if not args or not args[0] or len(args)!=1+args[0]*2:return reject(1)
            payload=b''  # Acknowledge display charsets; metadata stays UTF-8.
        elif pdu==0x18:
            if len(args)!=1 or args[0]>4:return reject(1)
            payload=b''  # Controller battery report; no phone state is fabricated.
        elif pdu==0x20 and len(args)>=9:
            n=args[8]
            if len(args)!=9+n*4 or args[:8]!=bytes(8):return reject(1)
            ids=[struct.unpack('!I',args[9+i*4:13+i*4])[0] for i in range(n)] if n else [1,2,3,7]
            fields={1:'title',2:'artist',3:'album',7:'duration_ms'};items=[]
            for key in ids[:7]:
                if key not in fields:continue
                value=self.media.get(fields[key])
                value=str(value if value is not None else '').encode('utf-8')[:48].decode('utf-8',errors='ignore').encode('utf-8')
                items.append(struct.pack('!IHH',key,106,len(value))+value)
            if not items:return reject(1)
            payload=bytes([len(items)])+b''.join(items)
        elif pdu==0x30 and not args:
            duration=self.media.get('duration_ms');position=self.media.get('position_ms')
            payload=struct.pack('!IIB',int(duration) if duration is not None else 0xffffffff,
                int(position) if position is not None else 0xffffffff,self.play_state())
        elif pdu==0x31 and len(args)==5 and args[0] in (1,2):
            self.pending=None
            self.subscriptions[args[0]]=header
            return self.vendor(header,pdu,self.notification(args[0]),15),None
        elif pdu in (0x40,0x41):
            if len(args)!=1 or self.pending is None or args[0]!=self.pending[0]:return reject(1)
            original,remaining=self.pending
            if pdu==0x41:
                self.pending=None
                return self.vendor(header,pdu,b'',9),None
            limit=self.max_packet_size-13
            chunk,rest=remaining[:limit],remaining[limit:]
            self.pending=(original,rest) if rest else None
            return self.vendor(header,original,chunk,packet_type=2 if rest else 3),None
        else:return reject(1)
        self.pending=None
        if pdu==0x20 and len(payload)>self.max_packet_size-13:
            limit=self.max_packet_size-13
            self.pending=(pdu,payload[limit:])
            return self.vendor(header,pdu,payload[:limit],packet_type=1),None
        return self.vendor(header,pdu,payload),None

    def update(self,media):
        old_state,old_uid=self.play_state(),self.uid();self.media=media
        changed=[]
        for event,diff in ((1,old_state!=self.play_state()),(2,old_uid!=self.uid())):
            if diff and event in self.subscriptions:
                changed.append(self.vendor(self.subscriptions.pop(event),0x31,self.notification(event),13))
        return changed
