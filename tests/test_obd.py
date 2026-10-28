"""OBD protocol, freshness and radio-first lifecycle tests without hardware."""
import asyncio
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from hlauncher import obd_service as service
from sdk.hlauncher_sdk.obd import snapshot


class Protocol(unittest.TestCase):
    def test_fragmented_reply_headers_and_pid_units(self):
        self.assertEqual(service.decode_pid(5,service.response_bytes('0105\rSEARCHING...\r41 05 7B\r>',5)),181.4)
        self.assertEqual(service.decode_pid(0x5c,bytes([140])),212)
        self.assertEqual(service.decode_pid(7,bytes([128])),0)
        self.assertEqual(service.decode_pid(7,bytes([160])),25)
        self.assertEqual(service.decode_pid(0x10,bytes([1,244])),5)
        self.assertIsNone(service.decode_pid(0x10,bytes([1])))
        self.assertIsNone(service.response_bytes('NO DATA\r>',5))
        self.assertEqual(service.supported_pids(0,bytes.fromhex('08000001')),{5,32})

    def test_live_stale_unsupported_and_disconnected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'status.json'
            path.write_text(json.dumps(dict(state='connected',monotonic=100,
                readings={'coolant':dict(value=194,monotonic=100),'oil':dict(value=210,monotonic=90),
                          'ltft':dict(value=-1.5,monotonic=99)})))
            self.assertEqual(snapshot(path,101)['values'],[194,None,-1.5,None])
            self.assertFalse(snapshot(path,110)['connected'])
            path.write_text('{')
            self.assertEqual(snapshot(path,100)['values'],[None]*4)

    def test_radio_heartbeat_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(service,'FOLDER',Path(tmp)):
            path=Path(tmp)/'radio.json'
            self.assertFalse(service.radio_ready(100))
            path.write_text(json.dumps(dict(ready=True,monotonic=99)))
            self.assertTrue(service.radio_ready(100))
            self.assertFalse(service.radio_ready(103))
            path.write_text(json.dumps(dict(ready=False,monotonic=100)))
            self.assertFalse(service.radio_ready(100))


class Lifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_prompt_framing_and_command_allowlist(self):
        class Char:properties=['write']
        class Client:
            async def write_gatt_char(self,char,payload,response):
                elm.notify(None,b'41 10 01')
                elm.notify(None,b' F4\r>')
        elm=service.Elm(Client(),Char(),None)
        self.assertEqual(service.response_bytes(await elm.command('0110'),0x10),bytes([1,244]))
        with self.assertRaises(ValueError):await elm.command('04')
        with self.assertRaises(ValueError):await elm.command('AT SH 7E0')

    async def test_radio_loss_cancels_ble_job_and_clears_values(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(service,'FOLDER',Path(tmp)):
            s=service.Service()
            cancelled=asyncio.Event()
            async def connected():
                try:await asyncio.sleep(60)
                finally:cancelled.set()
            s.operation=asyncio.create_task(connected())
            await asyncio.sleep(0)
            s.state.update(state='connected',readings={'coolant':dict(value=194)})
            task=asyncio.create_task(s.run())
            await asyncio.wait_for(cancelled.wait(),1)
            await asyncio.sleep(.02)
            self.assertEqual(s.state['state'],'paused')
            self.assertEqual(s.state['readings'],{})
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task

    async def test_connect_request_targets_only_selected_device(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(service,'FOLDER',Path(tmp)):
            from hlauncher.obd import atomic_json
            folder=Path(tmp);s=service.Service();s.ready_since=time.monotonic()-6
            atomic_json(folder/'radio.json',dict(ready=True,monotonic=time.monotonic(),radio_address='AA:AA:AA:AA:AA:AA'))
            atomic_json(folder/'command.json',dict(id=1,time=time.time(),action='connect',address='11:22:33:44:55:66'))
            called=asyncio.Event()
            async def fake_connect():
                self.assertEqual(s.target,'11:22:33:44:55:66')
                called.set()
                await asyncio.sleep(60)
            s.connect=fake_connect
            task=asyncio.create_task(s.run())
            await asyncio.wait_for(called.wait(),1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
            await s.stop_operation()
            self.assertEqual(json.loads((folder/'config.json').read_text())['target'],'11:22:33:44:55:66')

    async def test_complete_ble_elm_initialization_and_live_readings(self):
        from types import SimpleNamespace
        uart,tx_id,rx_id=service.UARTS[0]
        char=SimpleNamespace(uuid=tx_id,properties=['write','notify'])
        calls=[]
        class Client:
            is_connected=True
            services=[SimpleNamespace(uuid=uart,characteristics=[char])]
            def __init__(self,*args,**kwargs):pass
            async def connect(self):pass
            async def disconnect(self):self.is_connected=False
            async def start_notify(self,c,callback):self.notify=callback
            async def write_gatt_char(self,c,data,response):
                command=data.decode().strip();calls.append(command)
                replies={'ATI':'ELM327 v1.5','0100':'41000A010000',
                         '0105':'41057B','0107':'410782','0110':'411001F4'}
                self.notify(None,(replies.get(command,'OK')+'\r>').encode())
        with tempfile.TemporaryDirectory() as tmp,patch.object(service,'FOLDER',Path(tmp)),patch.dict('sys.modules',bleak=SimpleNamespace(BleakClient=Client,BleakScanner=object)):
            s=service.Service();s.target='11:22:33:44:55:66'
            s.devices[s.target]=SimpleNamespace(name='OBDII',address=s.target)
            job=asyncio.create_task(s.connect())
            deadline=time.monotonic()+2
            while len(s.state['readings'])<3 and time.monotonic()<deadline:await asyncio.sleep(.01)
            self.assertEqual(s.state['state'],'connected')
            self.assertEqual(s.state['supported'],['coolant','ltft','maf'])
            self.assertEqual(s.state['readings']['maf']['value'],5)
            self.assertNotIn('015C',calls)  # Unsupported oil PID is not fabricated or polled.
            self.assertNotIn('04',calls)
            job.cancel()
            with self.assertRaises(asyncio.CancelledError):await job
            self.assertIsNone(s.client)
