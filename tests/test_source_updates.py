"""Unsigned source remains opt-in, bounded, runtime-compatible and reversible."""
import io
import json
from pathlib import Path
import shutil
import tarfile
from types import SimpleNamespace
import unittest
import test_updater as fixtures
from hlauncher import updater,source_updates as source
from hlauncher.channel_updates import ChannelService,ChannelInstaller

ROOT=Path(__file__).resolve().parents[1]


class SourceUpdates(unittest.TestCase):
    setUp=fixtures.Updates.setUp
    tearDown=fixtures.Updates.tearDown
    manifest=fixtures.Updates.manifest

    def prepare(self):
        self.installer=ChannelInstaller(self.config,run=self.installer.run,health=lambda *_:None)
        self.service=ChannelService(self.config,self.state,installer=self.installer)
        updater.atomic(self.state/'settings.json',dict(include_beta_updates=True,source_updates=True,development_branch='feature/test',owner_data='keep'))
        app=self.root/'releases/1.0.0/app';app.mkdir()
        for name in ['hlauncher/launcher.py','hlauncher/config.py',*['hlauncher/'+n for n in source.OVERLAY_FILES]]:
            path=app/name;path.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,path)
        for name,data in {'hlauncher/__init__.py':b'__version__="1.0.0"\n','scripts/check.py':b'pass\n','native.c':b'int fixture;\n'}.items():
            path=app/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        for name in (*updater.UNITS,'hlauncher-firstboot.service','hlauncher-pipewire.service','hlauncher-grow.service'):
            path=app/'packaging'/name;path.parent.mkdir(exist_ok=True);path.write_text('[Unit]\nDescription=fixture\n')
        for name in ('build/fixture','plugins/carplay/runtime/usb/node_modules/fixture','plugins/carplay/runtime/usb/vendor/fixture'):
            path=app/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('installed native dependency')
        runtime=app.parent/'runtime/bin';runtime.mkdir(parents=True);(runtime/'hlauncher-android-auto').write_text('fixture')
        checkout=self.folder/'source';shutil.copytree(app,checkout)
        for name in ('build','plugins/carplay/runtime/usb/node_modules','plugins/carplay/runtime/usb/vendor'):
            shutil.rmtree(checkout/name)
        for name in source.OVERLAY_FILES:(checkout/'hlauncher'/name).unlink()
        self.checkout=checkout
        return self.offer()

    def offer(self,version='10000.0.1'):
        return dict(version=version,branch='feature/test',commit='a'*40,unsigned=True)

    def fetch(self,commit,destination):
        self.assertEqual(commit,'a'*40)
        with tarfile.open(destination,'w:gz') as archive:
            archive.add(self.checkout,arcname='HLauncher-'+commit)

    def test_stage_switch_another_branch_then_rollback_retains_updater_and_settings(self):
        offer=self.prepare();source.install(self.service,offer,fetch=self.fetch)
        self.assertEqual(self.installer.current(),'10000.0.1')
        installed=self.root/'releases/10000.0.1'
        self.assertTrue(updater.read(installed/'release.json')['unsigned'])
        generated=installed/'app/hlauncher/source_updater_overlay.py'
        compile(generated.read_text(),str(generated),'exec')
        self.assertTrue((installed/'app/build/fixture').is_file())
        source.install(self.service,self.offer('10000.0.2'),fetch=self.fetch)
        self.installer.rollback()
        self.assertEqual(self.installer.current(),'10000.0.1')
        self.assertEqual(updater.read(self.state/'settings.json')['owner_data'],'keep')

    def test_bad_native_inputs_rejected_before_activation(self):
        offer=self.prepare();(self.checkout/'native.c').write_text('changed native code')
        with self.assertRaisesRegex(ValueError,'native dependencies'):source.install(self.service,offer,fetch=self.fetch)
        self.assertEqual(self.installer.current(),'1.0.0')
        self.assertNotIn('pending',updater.read(self.installer.state_path))

    def test_opt_out_during_download_and_failed_health_leave_old_app(self):
        offer=self.prepare()
        def fetch(commit,path):
            self.fetch(commit,path)
            settings=updater.read(self.state/'settings.json');settings['source_updates']=False
            updater.atomic(self.state/'settings.json',settings)
        with self.assertRaisesRegex(ValueError,'selection changed'):source.install(self.service,offer,fetch=fetch)
        self.assertEqual(self.installer.current(),'1.0.0')
        settings=updater.read(self.state/'settings.json');settings['source_updates']=True
        updater.atomic(self.state/'settings.json',settings)
        def fail(*args):raise RuntimeError('fixture unhealthy')
        self.installer.health=fail
        with self.assertRaisesRegex(RuntimeError,'previous version was restored'):source.install(self.service,offer,fetch=self.fetch)
        self.assertEqual(self.installer.current(),'1.0.0')

    def test_source_catalogue_lists_raw_branches_without_a_release_build(self):
        self.prepare()
        def fetch(url,path,*args):
            if '/branches?' not in url:raise ValueError('No stable fixture')
            path.write_text(json.dumps([{'name':'feature/test','commit':{'sha':'a'*40}}]))
        self.service.fetch=fetch;self.service.check()
        status=updater.read(self.state/'update-status.json')
        self.assertEqual(status['available_channel'],'source')
        self.assertEqual(status['available_commit'],'a'*40)
        self.assertEqual(status['branches'][0]['branch'],'feature/test')

    def test_unsafe_source_archives_never_escape_staging(self):
        for name,kind,target in [('root/../../escape',tarfile.REGTYPE,''),('root/link',tarfile.SYMTYPE,'../../escape'),('root/device',tarfile.CHRTYPE,'')]:
            archive=self.folder/'hostile.tar.gz'
            with tarfile.open(archive,'w:gz') as out:
                item=tarfile.TarInfo(name);item.type=kind;item.linkname=target
                out.addfile(item,io.BytesIO())
            with self.assertRaises(ValueError):source.unpack(archive,self.folder/('stage'+str(len(name))))
            self.assertFalse((self.folder/'escape').exists())
