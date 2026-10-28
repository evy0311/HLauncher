"""Isolated BLE ELM327 reader. Never changes adapter power, pairing or profiles."""
import asyncio
import json
import logging
from logging.handlers import RotatingFileHandler
import re
import signal
import time
from .config import STATE_DIR, LOG_DIR
from .obd import atomic_json, read_json

log = logging.getLogger('obd')
FOLDER = STATE_DIR/'obd'
# Known serial-over-GATT layouts. Unknown layouts are reported, never guessed.
UARTS = [
    ('0000ffe0-0000-1000-8000-00805f9b34fb','0000ffe1-0000-1000-8000-00805f9b34fb','0000ffe1-0000-1000-8000-00805f9b34fb'),
    ('6e400001-b5a3-f393-e0a9-e50e24dcca9e','6e400002-b5a3-f393-e0a9-e50e24dcca9e','6e400003-b5a3-f393-e0a9-e50e24dcca9e'),
    ('0000fff0-0000-1000-8000-00805f9b34fb','0000fff2-0000-1000-8000-00805f9b34fb','0000fff1-0000-1000-8000-00805f9b34fb'),
]
PIDS = {'coolant':0x05, 'oil':0x5c, 'ltft':0x07, 'maf':0x10}


def response_bytes(reply, pid):
    """Headers off, one ECU response per line; choose the first matching ECU."""
    for line in re.split(r'[\r\n>]', reply.upper()):
        compact = re.sub(r'\s+', '', line)
        if not re.fullmatch(r'[0-9A-F]+',compact) or len(compact)%2:
            continue
        data = bytes.fromhex(compact)
        if data[:2] == bytes((0x41,pid)):
            return data[2:]
    return None


def decode_pid(pid, data):
    if not data:return None
    if pid in (0x05,0x5c):return (data[0]-40)*9/5+32
    if pid == 0x07:return (data[0]-128)*100/128
    if pid == 0x10 and len(data)>=2:return (data[0]*256+data[1])/100
    return None


def supported_pids(base, data):
    if data is None or len(data)<4:return set()
    bits = int.from_bytes(data[:4],'big')
    return {base+i for i in range(1,33) if bits & (1 << (32-i))}


def radio_ready(now=None):
    now = time.monotonic() if now is None else now
    state = read_json(FOLDER/'radio.json')
    age = now-state.get('monotonic',0)
    return bool(state.get('ready') and 0 <= age < 3)


def select_uart(services):
    for service, tx_uuid, rx_uuid in UARTS:
        entry = next((s for s in services if s.uuid.lower()==service),None)
        if entry is None:continue
        tx = next((c for c in entry.characteristics if c.uuid.lower()==tx_uuid),None)
        rx = next((c for c in entry.characteristics if c.uuid.lower()==rx_uuid),None)
        if tx and rx and {'write','write-without-response'}.intersection(tx.properties) and {'notify','indicate'}.intersection(rx.properties):
            return tx,rx
    raise RuntimeError('Unsupported BLE serial layout; see OBD log for service UUIDs')


class Elm:
    def __init__(self, client, tx, rx):
        self.client,self.tx,self.rx = client,tx,rx
        self.buffer = bytearray()
        self.prompt = asyncio.Event()

    def notify(self, sender, data):
        if len(self.buffer)+len(data)>16384:
            self.buffer.clear()
            self.buffer.extend(b'BUFFER ERROR>')
            self.prompt.set()
            return
        self.buffer.extend(data)
        if b'>' in self.buffer:self.prompt.set()

    async def command(self, command, timeout=3):
        # Explicit allowlist: adapter setup + read-only current-data requests.
        if command not in ('ATI','ATE0','ATL0','ATS0','ATH0','ATSP0') and not re.fullmatch(r'01[0-9A-F]{2}',command):
            raise ValueError('OBD command not allowed')
        self.buffer.clear(); self.prompt.clear()
        payload=(command+'\r').encode('ascii')
        for offset in range(0,len(payload),20):
            await asyncio.wait_for(self.client.write_gatt_char(self.tx,payload[offset:offset+20],
                response='write' in self.tx.properties),2)
        await asyncio.wait_for(self.prompt.wait(),timeout)
        reply=self.buffer.decode('ascii','replace')
        log.debug('%s -> %s',command,repr(reply))
        return reply


class Service:
    def __init__(self):
        self.state = dict(state='disconnected',message='No OBD dongle connected',devices=[],readings={},supported=[])
        self.devices = {}
        self.names = {}
        self.operation = None
        self.ready_since = None
        self.last_command = 0
        self.retry_at = self.last_publish = 0
        self.target = read_json(FOLDER/'config.json').get('target')
        self.client = None
        self.scan_requested = False
        self.browsing = False

    def publish(self, **fields):
        if fields.get('state') and fields['state'] != self.state.get('state'):
            log.info('%s: %s',fields['state'],fields.get('message',''))
        self.state.update(fields)
        self.state['monotonic'] = time.monotonic()
        self.state['target'] = self.target
        atomic_json(FOLDER/'status.json',self.state)

    def save_target(self, target):
        atomic_json(FOLDER/'config.json',dict(target=target))
        self.target = target

    async def stop_operation(self):
        if self.operation:
            self.operation.cancel()
            try:await self.operation
            except (asyncio.CancelledError,Exception):pass
            self.operation = None

    async def scan(self):
        from bleak import BleakScanner
        self.publish(state='scanning',message='Scanning for BLE dongles…',readings={})
        radio_address=read_json(FOLDER/'radio.json').get('radio_address')
        def found(device, advertisement):
            if device.address.upper()==radio_address:return
            self.devices[device.address.upper()] = device
            self.names[device.address.upper()] = advertisement.local_name or device.name or 'Unnamed BLE device'
        scanner=BleakScanner(detection_callback=found,adapter='hci0')
        async with scanner:
            await asyncio.sleep(4)
        rows=[dict(address=d.address.upper(),name=self.names.get(d.address.upper()) or d.name or 'Unnamed BLE device') for d in self.devices.values()]
        rows.sort(key=lambda row:(not any(word in row['name'].lower() for word in ('obd','elm','vlink','veepeak')),row['name']))
        self.publish(state='disconnected',message='Select your ELM327 BLE dongle' if rows else 'No BLE devices found',devices=rows)
        log.info('Discovery complete: %d devices',len(rows))

    async def connect(self):
        from bleak import BleakClient, BleakScanner
        try:
            self.publish(state='connecting',message='Connecting to OBD dongle…',readings={},supported=[])
            device = self.devices.get(self.target)
            if device is None:
                # A bounded, LE-only rediscovery, only after the radio is healthy.
                device = await BleakScanner.find_device_by_address(self.target,timeout=4,adapter='hci0')
            if device is None:raise RuntimeError('Saved dongle not found')
            self.client=BleakClient(device,adapter='hci0',timeout=8)
            await asyncio.wait_for(self.client.connect(),10)
            services = self.client.services
            log.info('GATT services: %s',[(s.uuid,[(c.uuid,c.properties) for c in s.characteristics]) for s in services])
            tx,rx = select_uart(services)
            elm=Elm(self.client,tx,rx)
            await asyncio.wait_for(self.client.start_notify(rx,elm.notify),3)
            self.publish(state='initializing',message='Checking ELM327 and vehicle…',device_name=device.name or self.target)
            identity = await elm.command('ATI')
            if not any(x in identity.upper() for x in ('ELM','STN','OBD')):
                raise RuntimeError('Device did not identify as an ELM-compatible adapter')
            for command in ('ATE0','ATL0','ATS0','ATH0','ATSP0'):
                reply = await elm.command(command)
                if 'OK' not in reply.upper():raise RuntimeError('Adapter rejected '+command)
            support = set()
            for base in (0x00,0x20,0x40):
                if base and base not in support:break
                reply=await elm.command(f'01{base:02X}',timeout=12 if base==0 else 3)
                payload=response_bytes(reply,base)
                if payload is None:raise RuntimeError('No vehicle response; check ignition and OBD connection')
                support |= supported_pids(base,payload)
            names=[name for name,pid in PIDS.items() if pid in support]
            self.publish(state='connected',message=f'Connected to {device.name or self.target} · live data',supported=names,readings={},adapter_identity=identity.strip('>\r\n '))
            log.info('Connected; supported gauge PIDs: %s',names)
            readings={}
            failures=0
            while self.client.is_connected:
                for name in names:
                    pid=PIDS[name]
                    reply=await elm.command(f'01{pid:02X}')
                    value=decode_pid(pid,response_bytes(reply,pid))
                    if value is None:
                        readings.pop(name,None);failures+=1
                    else:
                        failures=0
                        readings[name]=dict(value=value,monotonic=time.monotonic())
                    self.publish(readings=dict(readings))
                    if failures>=4:raise RuntimeError('Vehicle stopped returning gauge data')
                    await asyncio.sleep(.15)
                await asyncio.sleep(.4 if names else 1)
            raise RuntimeError('OBD dongle disconnected')
        finally:
            if self.client:
                try:await asyncio.wait_for(self.client.disconnect(),2)
                except Exception:log.warning('BLE disconnect timed out or failed',exc_info=True)
                self.client=None

    async def run(self):
        self.publish()
        while True:
            now=time.monotonic()
            ready=radio_ready(now)
            if not ready:
                self.ready_since=None
                await self.stop_operation()
                self.scan_requested=False
                self.browsing=False
                self.publish(state='paused',message='Waiting for radio connection · radio has priority',readings={})
            elif self.ready_since is None:
                self.ready_since=now
            command=read_json(FOLDER/'command.json')
            if command.get('id',0)>self.last_command:
                self.last_command=command['id']
                if abs(time.time()-command.get('time',0))<15:
                    action=command.get('action')
                    if action=='disconnect':
                        self.save_target(None)
                        await self.stop_operation()
                        self.publish(state='disconnected',message='OBD dongle disconnected',readings={})
                    elif action=='scan' and ready:
                        await self.stop_operation()
                        self.devices.clear()
                        self.scan_requested=True
                        self.browsing=True
                    elif action=='connect' and ready:
                        address=command.get('address','').upper()
                        if re.fullmatch(r'(?:[0-9A-F]{2}:){5}[0-9A-F]{2}',address) and address != read_json(FOLDER/'radio.json').get('radio_address'):
                            self.save_target(address)
                            await self.stop_operation()
                            self.scan_requested=False
                            self.browsing=False
                            self.retry_at=0
            if self.operation and self.operation.done():
                try:self.operation.result()
                except asyncio.CancelledError:pass
                except Exception as exc:
                    log.exception('OBD operation failed')
                    self.publish(state='error',message=str(exc)[:140],readings={})
                    self.retry_at=now+30
                self.operation=None
            if ready and self.ready_since is not None and now-self.ready_since>=5 and self.operation is None:
                if self.scan_requested:
                    self.scan_requested=False
                    self.operation=asyncio.create_task(self.scan())
                elif self.target and not self.browsing and now>=self.retry_at:
                    self.operation=asyncio.create_task(self.connect())
                elif self.state['state']=='paused':
                    self.publish(state='disconnected',message='Ready · tap Scan')
            if now-self.last_publish>=1:
                self.publish();self.last_publish=now
            await asyncio.sleep(.2)


async def main():
    LOG_DIR.mkdir(parents=True,exist_ok=True)
    handler=RotatingFileHandler(LOG_DIR/'obd-ble.log',maxBytes=2*1024*1024,backupCount=2)
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    log.addHandler(handler);log.setLevel(logging.DEBUG)
    service=Service()
    task=asyncio.current_task()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM,task.cancel)
    try:
        import bleak
        await service.run()
    finally:
        await service.stop_operation()


if __name__=='__main__':
    try:asyncio.run(main())
    except asyncio.CancelledError:pass
