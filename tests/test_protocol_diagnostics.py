"""Persistent protocol evidence and call/mic state must survive UI navigation safely."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from hlauncher.protocol_diagnostics import ProtocolDiagnostics
from hlauncher.projection_voice import ProjectionVoice,read_voice
from hlauncher.control_protocols import HfpProjection
from hlauncher.protocol.session import StartProbe,packet
from hlauncher.config import Preferences
from hlauncher.launcher import Launcher
from test_architecture import Display

ROOT=Path(__file__).resolve().parents[1]


class ProtocolCapture(unittest.TestCase):
    def test_packets_markers_and_meters_persist_without_microphone_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            monitor=ProtocolDiagnostics(folder,min_free=0)
            monitor.start()
            monitor.observe(dict(state='connected',uuid='test-cafe'))
            monitor.observe(dict(state='iap_ea_protocol',name='jp.co.honda.rd.dispaudio.app.hondalink'))
            monitor.observe(dict(state='honda_frame',session=257,message=0xd0,payload='0001ff'))
            monitor.observe(dict(state='audio_meter_level',dbfs=-20,bytes=640,pcm=b'not-recorded'))
            monitor.marker('Incoming call test')
            monitor.stop();monitor.close()
            lines=[json.loads(line) for path in Path(folder).glob('protocol-*.jsonl') for line in path.read_text().splitlines()]
            self.assertTrue(any(e.get('payload')=='0001ff' for e in lines))
            self.assertTrue(any(e.get('label')=='Incoming call test' for e in lines))
            self.assertFalse(any('pcm' in e for e in lines))
            self.assertTrue(all('wall' in e and 'monotonic' in e for e in lines))
            self.assertEqual([e['capture_sequence'] for e in lines],sorted(e['capture_sequence'] for e in lines))
            snapshot=monitor.snapshot()
            self.assertEqual(snapshot['messages'][0]['name'],'Unmapped message')
            self.assertEqual(snapshot['messages'][0]['bytes'],3)
            self.assertEqual(snapshot['dropped'],0)

    def test_capture_rotation_is_bounded_and_storage_failure_is_visible(self):
        with tempfile.TemporaryDirectory() as folder:
            monitor=ProtocolDiagnostics(folder,file_limit=1500,total_limit=4500,min_free=0)
            monitor.start()
            for i in range(100):
                monitor.observe(dict(state='protocol_packet',hex='aa'*150,index=i))
            monitor.close()
            self.assertLessEqual(sum(p.stat().st_size for p in Path(folder).glob('protocol-*.jsonl')),4500)
            bad=ProtocolDiagnostics(folder,min_free=2**62)
            bad.start();bad.pending.join()
            self.assertFalse(bad.snapshot()['recording'])
            self.assertIn('storage',bad.snapshot()['status'])
            bad.close()

    def test_diagnostics_tabs_record_in_background_and_voice_output_is_separate(self):
        with tempfile.TemporaryDirectory() as folder:
            prefs=Preferences(Path(folder)/'settings.json')
            prefs.data['debug_mode']=True; prefs.save()
            ui=Launcher(framebuffer=Display(),preferences=prefs,manifests={})
            try:
                ui.protocol_tests()
                for page in range(4):
                    ui.protocol_tab(page)
                    self.assertGreaterEqual(len(ui.actions),8)
                ui.toggle_protocol_capture()
                ui.mark_protocol_step()
                ui.home()
                self.assertTrue(ui.protocols.snapshot()['recording'])
                ui.toggle_voice_output()
                self.assertEqual(ui.voice_audio.output,'hdmi')
                self.assertFalse(ui.audio_settings.values['pipewire'])
                self.assertEqual(ui.audio_settings.device(),'hlauncher_hdmi')
            finally:ui.close()


class ProjectionVoiceTests(unittest.TestCase):
    def test_real_audio_leases_expire_and_dead_launchers_are_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'voice.json';events=[]
            voice=ProjectionVoice(lambda **e:events.append(e),path)
            fields=dict(call_audio=True,siri=False,recording=True)
            voice.update('carplay',fields);voice.tick('carplay')
            self.assertTrue(read_voice(path)['call_audio'])
            voice.sources['carplay']['at']-=10;voice.tick('carplay',force=True)
            self.assertFalse(read_voice(path)['call_audio'])
            voice.update('carplay',fields);voice.tick('android-auto',force=True)
            self.assertFalse(read_voice(path)['call_audio'])
            with patch('hlauncher.projection_voice.os.kill',side_effect=ProcessLookupError):self.assertEqual(read_voice(path),{})
            for fields in ({'call_audio':True},dict(call_audio=1,siri=False,recording=False)):
                with self.assertRaises(ValueError):voice.update('carplay',fields)

    def test_hfp_mirrors_actual_call_and_siri_without_inventing_network_or_ringing(self):
        model=HfpProjection()
        self.assertEqual(model.update({}),['+CIEV:2,0'])
        self.assertEqual(model.update(dict(call_audio=True)),['+CIEV:2,1'])
        self.assertEqual(model.update(dict(call_audio=True,siri=True)),['+BVRA:1'])
        self.assertEqual(model.update(dict(call_audio=True,siri=False)),['+BVRA:0'])
        self.assertEqual(model.update({}),['+CIEV:2,0'])
        self.assertEqual(model.update({}),[])

    def test_closed_iap_session_drops_decoder_and_handshake_without_closing_other_channels(self):
        probe=StartProbe();probe.authenticated=True
        probe.sessions={257:(1,'generals'),258:(2,'hondalink')}
        probe.honda_decoders[257]=object();probe.honda_stage[257]='ready'
        probe.app_started_sessions={257,258};probe.ready_announced={257,258}
        probe.app_metadata_sent[257]={1,2,3};probe.honda_name_retry.add(257)
        probe.start_ack_pending={0x8001:257}
        events,replies=probe.feed(packet(bytes.fromhex('004000010101')))
        self.assertNotIn(257,probe.sessions);self.assertIn(258,probe.sessions)
        self.assertNotIn(257,probe.honda_decoders);self.assertNotIn(257,probe.app_started_sessions)
        self.assertFalse(probe.start_ack_pending)
        self.assertTrue(replies)

    def test_call_indicator_patch_is_idempotent_and_preserves_unrelated_indicators(self):
        spec=importlib.util.spec_from_file_location('patch_call_audio',ROOT/'scripts/patch_call_audio.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        fixture=module.ANCHOR+'struct ba_rfcomm *r) { '+module.OLD+' }\n'+module.WRITE
        patched=module.patch_source(fixture)
        self.assertEqual(module.patch_source(patched),patched)
        with self.assertRaises(ValueError):module.patch_source('unexpected source')
        if not shutil.which('cc'):self.skipTest('C compiler unavailable')
        source='''#include <stdio.h>
#include <assert.h>
#define BA_TRANSPORT_PROFILE_HFP_AG 1
#define HFP_IND_CALL 2
#define HFP_IND_CALLSETUP 3
#define HFP_IND_CALLHELD 4
struct transport { struct {int profile;} type;};
struct ba_rfcomm {struct transport *sco;unsigned char hfp_ind[8];};
'''+module.HELPER+'''
int main(void) {
 struct transport t={.type.profile=1};struct ba_rfcomm r={.sco=&t};
 r.hfp_ind[1]=1;r.hfp_ind[7]=4;
 hlauncher_update_call_indicators(&r,"\\r\\n+CIEV:2,1\\r\\n");assert(r.hfp_ind[2]==1);
 hlauncher_update_call_indicators(&r,"\\r\\n+CIEV:2,2\\r\\n");assert(r.hfp_ind[2]==1);
 hlauncher_update_call_indicators(&r,"\\r\\n+CIEV:3,3\\r\\n");assert(r.hfp_ind[3]==3);
 hlauncher_update_call_indicators(&r,"\\r\\n+CIEV:4,2\\r\\n");assert(r.hfp_ind[4]==2);
 hlauncher_update_call_indicators(&r,"\\r\\n+CIEV:1,0\\r\\n");assert(r.hfp_ind[1]==1);
 hlauncher_update_call_indicators(&r,"\\r\\n+CIEV:7,0\\r\\n");assert(r.hfp_ind[7]==4);
 t.type.profile=0;hlauncher_update_call_indicators(&r,"\\r\\n+CIEV:2,0\\r\\n");assert(r.hfp_ind[2]==1);
 return 0;
}'''
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'indicator.c';path.write_text(source)
            binary=Path(folder)/'indicator'
            subprocess.run(['cc','-Wall','-Wextra','-Werror',str(path),'-o',str(binary)],check=True,capture_output=True)
            subprocess.run([str(binary)],check=True)

    def test_stop_microphone_does_not_stop_hdmi_playback_and_source_handoff_is_enforced(self):
        from hlauncher.audio import AudioBroker
        broker=AudioBroker(lambda **e:None)
        broker.playback=SimpleNamespace(stop=lambda plugin:self.fail('Microphone stop interrupted playback'))
        worker=SimpleNamespace(manifest=SimpleNamespace(id='carplay',capabilities={'audio.capture'}),
                               background_enabled=True,send=lambda **m:True)
        broker.owner='carplay';broker.worker=worker
        stopped=[];broker.capture=SimpleNamespace(stop=lambda:stopped.append(True))
        broker.request(worker,dict(type='audio.capture.stop'),active=False)
        self.assertEqual(stopped,[True]);self.assertIsNone(broker.owner)
        broker.capture_source='android-auto'
        messages=[];worker.send=lambda **m:messages.append(m)
        broker.request(worker,dict(type='audio.capture.start',sample_rate=16000),active=False)
        self.assertEqual(messages[-1]['type'],'audio.error')
        self.assertIsNone(broker.capture)

    def test_microphone_queue_is_bounded_and_does_not_log_samples(self):
        import sys
        from io import BytesIO
        saved={name:sys.modules.get(name) for name in ('input','media')}
        def load(name,path):
            spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
        try:
            sys.modules['input']=load('car_input',ROOT/'plugins/carplay/input.py')
            sys.modules['media']=load('car_media',ROOT/'plugins/carplay/media.py')
            backend=load('car_backend_voice',ROOT/'plugins/carplay/backend.py').CarplayHDMI()
            events=[];backend.event=lambda **e:events.append(e)
            backend.proc=SimpleNamespace(poll=lambda:None)
            backend.voice=dict(call_audio=True,siri=False,recording=True)
            backend.last_bridge_message=time.monotonic()
            self.assertTrue(backend.voice_snapshot()['call_audio'])
            backend.last_bridge_message-=6
            self.assertFalse(backend.voice_snapshot()['call_audio'])
            self.assertFalse(backend.microphone(b'\x01\x00'))
            backend.mic_format=(16000,1)
            self.assertTrue(backend.microphone(b'\x01\x00'*6400))
            self.assertEqual(len(backend.mic_queue),10)
            self.assertEqual(backend.mic_dropped,6400)
            raw=base64.b64decode(backend.mic_queue[0]['pcm']);self.assertEqual(len(raw),640)
            output=BytesIO()
            class Input:
                def write(self,data):
                    output.write(data);backend.stop_event.set()
                def flush(self):pass
            backend.proc.stdin=Input()
            backend.send_inputs(backend.proc)
            self.assertIn(b'microphone',output.getvalue())
            self.assertFalse(events)  # No PCM/base64 payload in diagnostics.
        finally:
            for name,value in saved.items():
                if value is None:sys.modules.pop(name,None)
                else:sys.modules[name]=value

    def test_source_handoff_notifies_microphone_owner_so_it_can_resume_later(self):
        from hlauncher.audio import AudioBroker
        broker=AudioBroker(lambda **e:None)
        selected=[];stopped=[];messages=[]
        broker.playback=SimpleNamespace(select_source=lambda plugin:selected.append(plugin))
        broker.owner='carplay'
        broker.worker=SimpleNamespace(send=lambda **m:messages.append(m))
        broker.capture=SimpleNamespace(stop=lambda:stopped.append(True))
        generation=broker.generation
        broker.select_source('android-auto')
        self.assertEqual(selected,['android-auto'])
        self.assertEqual(stopped,[True])
        self.assertEqual(messages,[dict(type='audio.capture.stopped')])
        self.assertIsNone(broker.owner)
        self.assertGreater(broker.generation,generation)
