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
    def test_view_demand_is_off_without_a_consumer_and_full_only_in_vehicle_tests(self):
        from types import SimpleNamespace
        from hlauncher.bootstrap import BootstrapLauncher
        b=BootstrapLauncher.__new__(BootstrapLauncher);b.ui=None
        self.assertEqual(b.vehicle_scope(),'off')
        b.ui=SimpleNamespace(mode='home',protocol_page=1,host=SimpleNamespace(active=None))
        self.assertEqual(b.vehicle_scope(),'off')
        b.ui.mode='plugin';b.ui.host.active='obd'
        self.assertEqual(b.vehicle_scope(),'gauges')
        b.ui.mode='protocol_tests';b.ui.protocol_page=0
        self.assertEqual(b.vehicle_scope(),'off')
        b.ui.protocol_page=1
        self.assertEqual(b.vehicle_scope(),'diagnostics')

    def test_hondalink_only_never_reads_or_falls_back_to_ble(self):
        with patch('pathlib.Path.read_text',side_effect=AssertionError('BLE status must not be read')):
            data=snapshot(vehicle={'connected':True,'monotonic':100,'readings':{
                'coolant_c':{'value':20,'monotonic':100},'rpm':{'value':0,'monotonic':100},
                'oil_life':{'value':75,'monotonic':100}}},now=100.2,allow_ble=False)
        self.assertEqual(data['values'],[0,68,None,None,None,None])

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
            self.assertEqual(snapshot(path,101)['values'],[None,194,None,None,None,None])
            self.assertFalse(snapshot(path,110)['connected'])
            path.write_text('{')
            self.assertEqual(snapshot(path,100)['values'],[None]*6)

    def test_hondalink_without_dongle_units_zero_and_per_value_expiry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'absent.json'
            vehicle=dict(connected=True,monotonic=100,readings={
                'coolant_c':dict(value=20,monotonic=100,interval_seconds=1),
                'rpm':dict(value=0,monotonic=100,interval_seconds=1),
                'oil_life':dict(value=75,monotonic=100,interval_seconds=1)})
            data=snapshot(path,100.25,vehicle=vehicle)
            self.assertEqual(data['values'][:5],[0,68,None,None,None])
            self.assertEqual(data['values'][5],None)
            self.assertEqual(data['sources'],['HondaLink','HondaLink','','','',''])
            self.assertEqual(data['ages'][0],.25)
            self.assertEqual(data['intervals'][0],1)
            self.assertEqual(snapshot(path,102,vehicle=vehicle)['values'],[None]*6)  # IPC heartbeat lost
            vehicle['monotonic']=106
            self.assertEqual(snapshot(path,106,vehicle=vehicle)['values'],[None]*6)  # individual samples stale
            vehicle['connected']=False
            self.assertFalse(snapshot(path,106,vehicle=vehicle)['connected'])

    def test_hondalink_preferred_with_explicit_ble_fallback_and_no_type_confusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'status.json'
            path.write_text(json.dumps(dict(state='connected',monotonic=100,
                readings={'coolant':dict(value=194,monotonic=100),'oil':dict(value=210,monotonic=100),
                          'rpm':dict(value=900,monotonic=100),'oil_life':dict(value=10,monotonic=100)})))
            vehicle=dict(connected=True,monotonic=100,readings={
                'coolant_c':dict(value=20,monotonic=100),'rpm':dict(value=0,monotonic=100),
                'oil_life':dict(value=True,monotonic=100)})
            data=snapshot(path,100.1,vehicle=vehicle)
            self.assertEqual(data['values'],[0,68,None,None,None,None])
            self.assertEqual(data['sources'],['HondaLink','HondaLink','','','',''])
            vehicle['readings']['coolant_c']['monotonic']=90
            self.assertEqual(snapshot(path,100.1,vehicle=vehicle)['values'][1],194)
        self.assertEqual(service.decode_pid(0x0c,bytes.fromhex('0c80')),800)

    def test_radio_cache_to_gauge_packet_works_without_capture_and_clears(self):
        from hlauncher.protocol_diagnostics import ProtocolDiagnostics
        from hlauncher.protocol.vehicle_can import decode_records
        from test_vehicle_can import can_data
        with tempfile.TemporaryDirectory() as tmp:
            monitor=ProtocolDiagnostics(tmp)
            monitor.observe(dict(state='connected',uuid='00000000-deca-fade-deca-deafdecacafe'))
            monitor.observe(dict(state='honda_can_data',session=257,data_type=0,
                records=decode_records(can_data([(0x320,bytes.fromhex('0040004600000000')),(0x17c,bytes.fromhex('ff00032000000000')),
                    (0x324,bytes.fromhex('3c46000000000000')),(0x454,bytes.fromhex('00f9000000000000'))]),api_ids=(44,40,167,1002,12,1003))))
            packet=monitor.gauge_snapshot()
            self.assertTrue(packet['connected'])
            self.assertEqual(packet['readings']['coolant_c']['value'],20)
            self.assertEqual(packet['readings']['rpm']['value'],800)
            self.assertAlmostEqual(packet['readings']['pedal_percent']['value'],100.000000065)
            self.assertEqual(packet['readings']['intake_c']['value'],30)
            self.assertAlmostEqual(packet['readings']['baro_native']['value'],759.965)
            self.assertIs(packet['readings']['vtec']['value'],True)
            self.assertFalse(monitor.recording)
            self.assertIsNone(monitor.thread)
            monitor.observe(dict(state='iap_data_session_closed',session=257))
            self.assertFalse(monitor.gauge_snapshot()['readings'])
            monitor.close()

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


class DashboardUI(unittest.TestCase):
    def test_needle_eases_quickly_while_numbers_remain_received_values(self):
        from hlauncher.ui.obd_dashboard import Dashboard
        d=Dashboard(720,480)
        d.render([0,68,None,None,None,None],now=1)
        d.render([2000,168,None,None,None,None],now=1.05)
        self.assertTrue(0<d.needle_values[0]<2000)
        self.assertGreater(d.needle_values[0],1600)
        self.assertLess((d.needle_values[1]-68)/100,d.needle_values[0]/2000)
        for i in range(1,7):d.render([2000,68,None,None,None,None],now=1.05+i*.05)
        self.assertGreater(d.needle_values[0],1950)
        d.render([None]*6,now=1.5)
        self.assertEqual(d.needle_values,[None]*6)

    def test_fullscreen_tap_reveals_exit_and_minimize_restores_header(self):
        from hlauncher.ui.obd_dashboard import Dashboard
        from PIL import ImageChops
        d=Dashboard(720,480)
        normal=d.render([0,68,None,None,None,None],now=10)
        self.assertGreater(d.centers[0][2],54)
        d.touch('down',(680,25),10)
        self.assertEqual(d.touch('up',(680,25),10.1),'expand')
        self.assertTrue(d.fullscreen)
        self.assertGreater(d.fullscreen_centers[0][2],d.centers[0][2])
        hidden=d.render([0,68,None,None,None,None],now=11)
        self.assertEqual(hidden.getpixel((10,10)),(9,9,13))
        d.touch('down',(360,240),11);d.touch('up',(360,240),11.1)
        revealed=d.render([0,68,None,None,None,None],now=12)
        self.assertIsNotNone(ImageChops.difference(hidden,revealed).getbbox())
        self.assertIsNone(ImageChops.difference(revealed,d.render([0,68,None,None,None,None],now=16)).getbbox())
        d.touch('down',(360,240),16);d.touch('up',(360,240),16.1)
        self.assertIsNone(ImageChops.difference(hidden,d.render([0,68,None,None,None,None],now=16.2)).getbbox())
        d.touch('down',(20,25),17)
        self.assertEqual(d.touch('up',(20,25),17.1),'reveal')  # hidden Back cannot exit the plugin
        d.touch('down',(680,25),18)
        self.assertEqual(d.touch('up',(680,25),18.1),'minimize')
        self.assertFalse(d.fullscreen)
        with patch('hlauncher.ui.obd_dashboard.time.strftime',return_value='fixed'):
            a=d.render([0,68,None,None,None,None],now=19)
            b=d.render([0,68,None,None,None,None],now=19,sources=['HondaLink']*6,ages=[1]*6,intervals=[1]*6)
            self.assertIsNone(ImageChops.difference(a,b).getbbox())  # removed text stays removed

    def test_scaled_fullscreen_hit_boxes_and_cancelled_drag(self):
        from hlauncher.ui.obd_dashboard import Dashboard
        d=Dashboard(800,480)
        x=(d.fullscreen_box[0]+d.fullscreen_box[2])/2
        d.touch('down',(x,25),1);d.touch('move',(300,200),1.1);d.touch('up',(300,200),1.2)
        self.assertFalse(d.fullscreen)
        d.touch('down',(x,25),2);d.touch('cancel',None,2.1);d.touch('up',(x,25),2.2)
        self.assertFalse(d.fullscreen)
        d.touch('down',(x,25),3);d.touch('up',(x,25),3.1)
        self.assertTrue(d.fullscreen)

    def test_gauge_handoff_is_limited_to_the_active_bundled_obd_worker(self):
        from types import SimpleNamespace
        from hlauncher.plugin_host import PluginHost
        host=PluginHost.__new__(PluginHost);sent=[]
        worker=SimpleNamespace(manifest=SimpleNamespace(bundled=True),send=lambda **m:sent.append(m) or True)
        host.workers={'obd':worker};host.active='obd'
        self.assertTrue(host.vehicle_gauges({'connected':True}))
        self.assertEqual(sent[-1]['type'],'vehicle.gauges')
        worker.manifest.bundled=False
        self.assertFalse(host.vehicle_gauges({}))
        worker.manifest.bundled=True;host.active='carplay'
        self.assertFalse(host.vehicle_gauges({}))
        self.assertEqual(len(sent),1)

    def test_disconnected_values_are_never_displayed_and_header_scales(self):
        from hlauncher.ui.obd_dashboard import Dashboard
        from PIL import ImageChops
        dashboard=Dashboard(800,480)
        with patch('hlauncher.ui.obd_dashboard.time.strftime',return_value='2026-11-07 12:00'):
            stale=dashboard.render([200,210,2,4],connected=False)
            empty=dashboard.render([None]*4,connected=False)
            self.assertIsNone(ImageChops.difference(stale,empty).getbbox())
            live=dashboard.render([200,210,2,4],connected=True)
            self.assertIsNotNone(ImageChops.difference(empty,live).getbbox())
            self.assertEqual(live.size,(800,480))
            self.assertEqual(dashboard.home_box,(0,0,89,52))
            self.assertIsNotNone(ImageChops.difference(live,dashboard.render([200,210,2,4],pressed=True)).getbbox())
