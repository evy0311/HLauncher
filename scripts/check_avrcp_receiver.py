"""Verify the isolated receiver with a local synthetic controller; no Bluetooth I/O."""
import argparse
from collections import Counter
import json
from pathlib import Path
import socket
import struct
import subprocess
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hlauncher.debug_tools import InputMonitor


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds',type=int,default=60)
    args=parser.parse_args()
    if not 15<=args.seconds<=300:parser.error('--seconds must be between 15 and 300')
    receiver,controller=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
    controller.settimeout(3)
    monitor=InputMonitor(lambda **v:None,'')
    errors=[];counts=Counter();transaction=0;sent=Counter()
    code='''import socket,sys
from hlauncher import controls_worker as worker
worker.metadata=lambda:dict(available=True,title='Receiver check',artist='Synthetic controller',
                           album='Local test fixture',playback_state='paused',duration_ms=60000,position_ms=1000)
worker.serve_avrcp(socket.socket(fileno=int(sys.argv[1])))
'''
    child=subprocess.Popen([sys.executable,'-c',code,str(receiver.fileno())],cwd=ROOT,
                           pass_fds=(receiver.fileno(),),stdout=subprocess.PIPE,text=True)
    receiver.close()

    def read_events():
        try:
            for line in child.stdout:
                monitor.receive_control(json.loads(line))
        except Exception as exc:errors.append(type(exc).__name__)

    reader=threading.Thread(target=read_events,daemon=True);reader.start()

    def exchange(raw):
        controller.sendall(raw)
        reply=controller.recv(512)
        if len(reply)<6 or reply[0]!=(raw[0]|2):raise RuntimeError('Invalid transaction response')
        if len(reply)>48:raise RuntimeError('Reply exceeded minimum MTU')
        return reply

    def vendor(pdu,payload=b'',ctype=1):
        nonlocal transaction
        transaction=(transaction+1)%16
        raw=bytes([transaction<<4])+b'\x11\x0e'+bytes([ctype,0x48,0,0,0x19,0x58,pdu,0])+struct.pack('!H',len(payload))+payload
        reply=exchange(raw)
        if reply[3] not in (12,15):raise RuntimeError(f'PDU 0x{pdu:02x} rejected')
        return reply

    def drain():
        for event in monitor.drain():
            if event['action']=='down':counts[event['button']]+=1

    start=time.monotonic()
    try:
        # The four observed Honda setup PDUs, plus basic follow-up queries.
        for pdu,payload,ctype in ((0x10,b'\x03',1),(0x31,b'\x01'+bytes(4),3),
                                  (0x31,b'\x02'+bytes(4),3),(0x11,b'',1),
                                  (0x17,b'\x01\x00\x6a',1),(0x18,b'\x00',1),(0x30,b'',1)):
            vendor(pdu,payload,ctype)
        reply=vendor(0x20,bytes(9));parts=[reply[13:]];fragments=1
        while reply[10] in (1,2):
            reply=vendor(0x40,b'\x20',ctype=0);parts.append(reply[13:]);fragments+=1
            if fragments>16:raise RuntimeError('Metadata continuation did not terminate')
        if b''.join(parts)[0]!=4:raise RuntimeError('Metadata attributes lost')
        # Exceeds the recorded radio disconnect interval without sending commands.
        idle=min(10,args.seconds/3)
        time.sleep(idle)
        vendor(0x30)
        deadline=start+args.seconds
        while time.monotonic()<deadline:
            for operation,name in ((0x4b,'next'),(0x4c,'previous')):
                for op in (operation,operation|0x80):
                    raw=bytes([transaction<<4])+bytes.fromhex('110e00487c')+bytes([op,0])
                    if exchange(raw)[3]!=9:raise RuntimeError('Track key rejected')
                sent[name]+=1
            drain()
            if errors or child.poll() is not None:raise RuntimeError('Receiver exited during check')
            time.sleep(.25)
    finally:
        controller.close()
        try:child.wait(timeout=3)
        except subprocess.TimeoutExpired:child.terminate();child.wait(timeout=3)
        reader.join(timeout=3);child.stdout.close()
    drain()
    if errors or child.returncode or counts!=sent:raise RuntimeError(f'Lost receive events: sent={sent}, received={counts}, errors={errors}')
    print(json.dumps(dict(method='isolated process / local SOCK_SEQPACKET controller',
                          synthetic_controller=True,physical_radio_verified=False,
                          duration_seconds=round(time.monotonic()-start,3),idle_seconds=idle,
                          negotiated_fixture_mtu=48,metadata_fragments=fragments,
                          sent_presses=dict(sent),received_presses=dict(counts),
                          rx_counts={key:monitor.buttons[key]['count'] for key in sent},
                          child_exit_code=child.returncode),indent=2))


if __name__=='__main__':main()
