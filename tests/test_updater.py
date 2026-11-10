"""Signed updates, explicit restore, power-loss recovery and hostile packages."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from hlauncher import updater, update_client
from hlauncher.update_service import Service

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('package_release',ROOT/'scripts/package_release.py')
package_release=importlib.util.module_from_spec(spec);spec.loader.exec_module(package_release)


class Updates(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        self.root=self.folder/'installed';self.root.mkdir()
        self.key=self.folder/'key.pem';self.public=self.folder/'release.pub'
        subprocess.run(['openssl','genpkey','-algorithm','ED25519','-out',str(self.key)],check=True,capture_output=True)
        package_release.public_key(self.key,self.public)
        self.config=dict(root=str(self.root),public_key=str(self.public),platform=updater.PLATFORM,system_contract='baseline')
        self.calls=[]
        def run(args,**kwargs):
            self.calls.append(args)
            return SimpleNamespace(returncode=0)
        self.installer=updater.Installer(self.config,run=run,health=lambda v,u:None)
        initial=self.root/'releases/1.0.0';initial.mkdir()
        updater.atomic(initial/'release.json',self.manifest('1.0.0'))
        updater.switch(self.root,'1.0.0');updater.atomic(self.installer.state_path,dict(current='1.0.0',previous=None))
        self.state=self.folder/'state';self.state.mkdir()
        (self.state/'settings.json').write_text('{"tile_color":"Red","enabled":{"carplay":true}}')

    def test_release_units_reload_for_update_rollback_and_interruption(self):
        self.config.update(release_units=True,unit_root=str(self.folder/'system'))
        for release in ('1.0.0',):
            folder=self.root/'releases'/release/'app/packaging';folder.mkdir(parents=True)
            for name in (*updater.UNITS,'hlauncher-firstboot.service','hlauncher-pipewire.service','hlauncher-grow.service'):
                (folder/name).write_text('[Unit]\nDescription=old\n')
        self.installer.install(*self.bundle(boot_units=True))
        self.assertIn(['systemctl','daemon-reload'],self.calls)
        self.assertIn('new',(self.folder/'system/etc/systemd/system/hlauncher.service').read_text())
        self.calls.clear();self.installer.rollback()
        self.assertIn(['systemctl','daemon-reload'],self.calls)
        self.assertIn('old',(self.folder/'system/etc/systemd/system/hlauncher.service').read_text())
        self.calls.clear()
        updater.atomic(self.installer.state_path,dict(current='1.0.0',previous=None,pending={'from':'1.0.0','to':'1.1.0'}))
        self.installer.recover()
        self.assertIn(['systemctl','daemon-reload'],self.calls)

    def test_boot_update_rejects_overlay_before_stopping_or_switching(self):
        self.config['release_units']=True
        self.installer.run=lambda args,**kw:SimpleNamespace(returncode=0,stdout='overlay\n')
        with self.assertRaisesRegex(ValueError,'SD card protection'):
            self.installer.install(*self.bundle(boot_units=True))
        self.assertEqual(self.installer.current(),'1.0.0')
        self.assertNotIn('pending',updater.read(self.installer.state_path))

    def tearDown(self):self.temp.cleanup()

    def manifest(self, version, **changes):
        return dict(dict(format=1,updater=1,state_schema=1,platform=updater.PLATFORM,system_contract='baseline',
                         version=version,archive=f'HLauncher-{version}-pi4-arm64.tar.xz',size=1,
                         unpacked_size=1,sha256='a'*64),**changes)

    def bundle(self, version='1.1.0', **changes):
        boot_units=changes.pop('boot_units',False)
        folder=self.folder/('bundle-'+version);folder.mkdir(exist_ok=True)
        app=folder/'app';(app/'hlauncher').mkdir(parents=True,exist_ok=True)
        (app/'hlauncher/__init__.py').write_text('__version__ = '+repr(version))
        if boot_units:
            (app/'packaging').mkdir()
            for name in (*updater.UNITS,'hlauncher-firstboot.service','hlauncher-pipewire.service','hlauncher-grow.service'):
                (app/'packaging'/name).write_text('[Unit]\nDescription=new\n')
        runtime=folder/'runtime';runtime.mkdir(exist_ok=True)
        (runtime/'library.so').write_text('native fixture')
        archive=folder/f'HLauncher-{version}-pi4-arm64.tar.xz'
        unpacked=package_release.archive_tree(archive,[('app',app),('runtime',runtime)])
        info=self.manifest(version,size=archive.stat().st_size,unpacked_size=unpacked,sha256=updater.sha256(archive),**changes)
        manifest=folder/'manifest.json';signature=folder/'manifest.sig'
        updater.atomic(manifest,info)
        subprocess.run(['openssl','pkeyutl','-sign','-rawin','-inkey',str(self.key),'-in',str(manifest),
                        '-out',str(signature)],check=True,capture_output=True)
        return manifest,signature,archive

    def test_install_and_manual_restore_preserve_user_state(self):
        before=(self.state/'settings.json').read_bytes()
        self.installer.install(*self.bundle())
        self.assertEqual(self.installer.status(),dict(current='1.1.0',previous='1.0.0'))
        self.assertFalse(updater.read(self.installer.state_path).get('pending'))
        self.installer.rollback()
        self.assertEqual(self.installer.status(),dict(current='1.0.0',previous='1.1.0'))
        self.assertEqual((self.state/'settings.json').read_bytes(),before)
        self.installer.rollback();self.assertEqual(self.installer.current(),'1.1.0')
        self.assertTrue(any(c[:2]==['systemctl','stop'] for c in self.calls))
        self.assertFalse(any('hlauncher-updater.service' in c for c in self.calls))

    def test_failed_health_restores_exact_previous_install(self):
        self.installer.health=lambda v,u:(_ for _ in ()).throw(RuntimeError('unhealthy'))
        with self.assertRaisesRegex(RuntimeError,'previous version was restored'):
            self.installer.install(*self.bundle())
        self.assertEqual(self.installer.current(),'1.0.0')
        self.assertIsNone(self.installer.status()['previous'])
        self.assertFalse(updater.read(self.installer.state_path).get('pending'))

    def test_power_loss_before_and_after_pointer_switch_is_recovered(self):
        for changed in (False,True):
            target=self.root/'releases/1.1.0';target.mkdir(exist_ok=True)
            updater.atomic(target/'release.json',self.manifest('1.1.0'))
            updater.atomic(self.installer.state_path,dict(current='1.0.0',previous=None,
                pending={'from':'1.0.0','to':'1.1.0'},units=['hlauncher.service']))
            if changed:updater.switch(self.root,'1.1.0')
            self.installer.recover()
            self.assertEqual(self.installer.current(),'1.0.0')
            self.assertEqual(updater.read(self.installer.state_path)['resume_units'],['hlauncher.service'])
            self.assertTrue(updater.read(self.installer.state_path)['recovered'])

    def test_tampered_manifest_signature_or_archive_never_stops_app(self):
        manifest,signature,archive=self.bundle()
        original=manifest.read_bytes();manifest.write_bytes(original+b' ')
        with self.assertRaises(subprocess.CalledProcessError):self.installer.install(manifest,signature,archive)
        manifest.write_bytes(original);archive.write_bytes(archive.read_bytes()+b'corruption')
        with self.assertRaisesRegex(ValueError,'verification'):self.installer.install(manifest,signature,archive)
        self.assertEqual(self.calls,[])
        self.assertEqual(self.installer.current(),'1.0.0')

    def test_failed_restore_leaves_durable_recovery_for_daemon_restart(self):
        self.installer.health=lambda v,u:(_ for _ in ()).throw(RuntimeError('unhealthy'))
        with patch.object(self.installer,'stop',side_effect=[None,OSError('systemctl unavailable')]):
            with self.assertRaises(updater.RecoveryRequired):self.installer.install(*self.bundle())
        self.assertTrue(updater.read(self.installer.state_path).get('pending'))
        self.installer.recover()
        self.assertEqual(self.installer.current(),'1.0.0')
        self.assertIn('hlauncher.service',updater.read(self.installer.state_path)['resume_units'])

    def test_native_self_test_failure_rolls_back_before_commit(self):
        original=self.installer.run
        def run(command,**kwargs):
            if 'scripts/check.py' in command:raise subprocess.CalledProcessError(1,command)
            return original(command,**kwargs)
        self.installer.run=run
        with self.assertRaises(RuntimeError):self.installer.install(*self.bundle())
        self.assertEqual(self.installer.current(),'1.0.0')
        self.assertFalse(updater.read(self.installer.state_path).get('pending'))

    def test_staging_left_by_power_loss_is_removed_without_touching_versions(self):
        staging=self.root/'.staging-1.1.0';staging.mkdir();(staging/'partial').write_text('partial')
        self.installer.recover()
        self.assertFalse(staging.exists())
        self.assertEqual(self.installer.current(),'1.0.0')

    def test_platform_schema_and_system_changes_require_new_image(self):
        for changes in ({'platform':'other'},{'system_contract':'other'},{'state_schema':2},{'updater':2}):
            with self.assertRaises(ValueError):updater.validate_manifest(self.manifest('1.1.0',**changes),self.config)
        with self.assertRaises(ValueError):self.installer.install(*self.bundle('0.9.0'))
        self.assertFalse(self.calls)

    def test_disk_full_does_not_stop_existing_version(self):
        files=self.bundle()
        with patch('hlauncher.updater.shutil.disk_usage',return_value=SimpleNamespace(free=1)):
            with self.assertRaisesRegex(ValueError,'space'):self.installer.install(*files)
        self.assertEqual(self.installer.current(),'1.0.0');self.assertFalse(self.calls)

    def test_only_running_and_previous_versions_retained(self):
        self.installer.install(*self.bundle('1.1.0'))
        self.installer.install(*self.bundle('1.2.0'))
        self.assertEqual(self.installer.status(),dict(current='1.2.0',previous='1.1.0'))
        self.assertFalse((self.root/'releases/1.0.0').exists())

    def test_request_queue_never_overwrites_pending_work(self):
        update_client.request('check',self.state)
        with self.assertRaises(FileExistsError):update_client.request('rollback',self.state)
        self.assertEqual(updater.read(self.state/'update-request.json'),dict(operation='check'))
        self.assertFalse(list(self.state.glob('.update-request-*')))
        with self.assertRaises(ValueError):update_client.request('shell',self.state)

    def test_release_check_downloads_signed_assets_and_install(self):
        manifest,signature,archive=self.bundle()
        prefix='https://github.com/evy0311/HLauncher/releases/download/v1.1.0/'
        names={'hlauncher-release.json':manifest,'hlauncher-release.sig':signature,archive.name:archive}
        release=dict(tag_name='v1.1.0',draft=False,prerelease=False,body='Improved audio',
                     assets=[dict(name=n,browser_download_url=prefix+n) for n in names])
        def fetch(url,path,maximum,expected=None):
            if url.endswith('/latest'):Path(path).write_text(json.dumps(release))
            else:Path(path).write_bytes(names[url.rsplit('/',1)[1]].read_bytes())
        service=Service(self.config,self.state,fetch,self.installer)
        service.perform('check')
        self.assertEqual(update_client.status(self.state)['available'],'1.1.0')
        self.assertEqual(update_client.status(self.state)['notes'],'Improved audio')
        self.assertEqual(update_client.status(self.state)['notes_version'],'1.1.0')
        service.perform('install')
        self.assertEqual(self.installer.current(),'1.1.0')
        self.assertEqual(update_client.status(self.state)['message'],'Update installed')
        service.perform('rollback');self.assertEqual(self.installer.current(),'1.0.0')

    def test_non_github_release_and_tampered_offer_are_rejected(self):
        self.assertFalse(updater.allowed_url('http://github.com/a'))
        self.assertFalse(updater.allowed_url('https://github.com.evil.example/a'))
        self.assertFalse(updater.allowed_url('https://user:pw@github.com/a'))
        self.assertTrue(updater.allowed_url('https://release-assets.githubusercontent.com/a'))
        service=Service(self.config,self.state,lambda *a:None,self.installer)
        updater.atomic(service.cache/'offer.json',dict(url='https://evil.example/package'))
        service.perform('install')
        self.assertEqual(update_client.status(self.state)['phase'],'error')
        self.assertEqual(self.installer.current(),'1.0.0')

    def test_untrusted_redirect_and_oversized_download_are_rejected(self):
        from urllib.request import Request
        handler=updater.ReleaseRedirect()
        with self.assertRaises(ValueError):handler.redirect_request(Request('https://github.com/a'),None,302,'',{},'http://localhost/file')
        class Response(io.BytesIO):
            def geturl(self):return 'https://github.com/example'
        opener=SimpleNamespace(open=lambda *a,**kw:Response(b'oversized'))
        with patch('hlauncher.updater.build_opener',return_value=opener):
            with self.assertRaisesRegex(ValueError,'limit'):
                updater.download('https://github.com/example',self.folder/'download',3)

    def test_tar_traversal_links_devices_and_size_bombs_rejected(self):
        for i,(name,kind,target) in enumerate((('../escape',tarfile.REGTYPE,''),
                ('app/link',tarfile.SYMTYPE,'../../escape'),('runtime/device',tarfile.CHRTYPE,''),
                ('app/hard',tarfile.LNKTYPE,'/etc/passwd'))):
            path=self.folder/f'evil-{i}.xz'
            with tarfile.open(path,'w:xz') as archive:
                info=tarfile.TarInfo(name);info.type=kind;info.linkname=target
                if kind==tarfile.REGTYPE:info.size=1
                archive.addfile(info,io.BytesIO(b'x') if info.size else None)
            with self.assertRaises(ValueError):updater.unpack(path,self.folder/f'extract-{i}',1)
        self.assertFalse((self.folder/'escape').exists())

    def test_crash_during_activation_is_recovered_on_next_start(self):
        self.installer.health=lambda v,u:(_ for _ in ()).throw(KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):self.installer.install(*self.bundle())
        self.assertEqual(self.installer.current(),'1.1.0')
        fresh=updater.Installer(self.config,run=self.installer.run,health=lambda v,u:None)
        fresh.recover()
        self.assertEqual(fresh.current(),'1.0.0')
        self.assertFalse(updater.read(fresh.state_path).get('pending'))

    def test_signed_local_container_installs_without_github(self):
        manifest,signature,archive=self.bundle()
        output=archive.parent
        (output/'hlauncher-release.json').write_bytes(manifest.read_bytes())
        (output/'hlauncher-release.sig').write_bytes(signature.read_bytes())
        local=package_release.local_container(output,'1.1.0',archive)
        inbox=self.root/'inbox';inbox.mkdir()
        (inbox/'local-update.hlu').write_bytes(local.read_bytes())
        service=Service(self.config,self.state,lambda *a:(_ for _ in ()).throw(AssertionError('network used')),self.installer)
        service.perform('import')
        self.assertEqual(self.installer.current(),'1.1.0')
        self.assertEqual(update_client.status(self.state)['message'],'Local update installed')
        self.assertFalse((inbox/'local-update.hlu').exists())
        self.installer.rollback();self.assertEqual(self.installer.current(),'1.0.0')

    def test_local_import_rejects_unexpected_container_members(self):
        inbox=self.root/'inbox';inbox.mkdir()
        with tarfile.open(inbox/'local-update.hlu','w') as archive:
            member=tarfile.TarInfo('../escaped');member.size=1
            archive.addfile(member,io.BytesIO(b'x'))
        service=Service(self.config,self.state,installer=self.installer)
        service.perform('import')
        self.assertEqual(update_client.status(self.state)['phase'],'error')
        self.assertEqual(self.installer.current(),'1.0.0')
        self.assertFalse((self.root/'escaped').exists())

    def test_local_network_upload_queues_signed_import(self):
        import base64,http.client,threading
        from http.server import ThreadingHTTPServer
        from hlauncher import recovery
        from hlauncher.setup_state import SetupState
        state=SetupState(self.state)
        config_path=self.folder/'updater-config.json';updater.atomic(config_path,self.config)
        server=ThreadingHTTPServer(('127.0.0.1',0),recovery.handler_for(state,recovery.Maintenance(state)))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        connection=http.client.HTTPConnection(*server.server_address,timeout=3)
        try:
            with patch.object(recovery,'UPDATER_CONFIG',config_path):
                connection.request('POST','/api/update-file',b'file',{'Content-Type':'application/octet-stream','Origin':'http://unrelated.invalid'})
                response=connection.getresponse();self.assertEqual(response.status,403);response.read()
                auth='Basic '+base64.b64encode(('hlauncher:'+state.credentials()['password']).encode()).decode()
                headers={'Content-Type':'application/octet-stream'}
                connection.request('POST','/api/update-file',b'container bytes',headers)
                response=connection.getresponse();self.assertEqual(response.status,202);response.read()
                self.assertEqual((self.root/'inbox/local-update.hlu').read_bytes(),b'container bytes')
                self.assertEqual(updater.read(self.state/'update-request.json'),dict(operation='import'))
                connection.request('POST','/api/update-file',b'overwrite',headers)
                response=connection.getresponse();self.assertEqual(response.status,409);response.read()
                self.assertEqual((self.root/'inbox/local-update.hlu').read_bytes(),b'container bytes')
        finally:
            connection.close();server.shutdown();server.server_close();thread.join(3)

    def test_confined_symlinks_round_trip(self):
        manifest,signature,archive=self.bundle()
        # Package an npm-style relative executable link.
        app=archive.parent/'app';(app/'bin').mkdir();(app/'bin/run').symlink_to('../hlauncher/__init__.py')
        target=self.folder/'links.tar.xz'
        size=package_release.archive_tree(target,[('app',app)])
        updater.unpack(target,self.folder/'links',size)
        self.assertEqual((self.folder/'links/app/bin/run').read_bytes(),(app/'hlauncher/__init__.py').read_bytes())


class ContractCompatibility(unittest.TestCase):
    def test_only_trusted_device_config_can_allow_older_contract(self):
        item=dict(format=1,updater=1,state_schema=1,platform=updater.PLATFORM,
                  system_contract='a'*64,version='0.2.4',archive='HLauncher-0.2.4-pi4-arm64.tar.xz',
                  size=10,unpacked_size=20,sha256='b'*64)
        config=dict(platform=updater.PLATFORM,system_contract='c'*64)
        with self.assertRaises(ValueError):updater.validate_manifest(item,config)
        item['compatible_contracts']=['a'*64]
        with self.assertRaises(ValueError):updater.validate_manifest(item,config)
        config['compatible_contracts']=['a'*64]
        self.assertEqual(updater.validate_manifest(item,config),item)
        item['platform']='different-platform'
        with self.assertRaises(ValueError):updater.validate_manifest(item,config)


class ReleaseImage(unittest.TestCase):
    def test_packaged_image_and_update_are_identical_and_exclude_user_state(self):
        import shutil
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);root=folder/'image';persist=folder/'persist';out=folder/'release'
            (root/'etc').mkdir(parents=True);persist.mkdir()
            (root/'etc/os-release').write_text('VERSION_CODENAME=bookworm\n')
            app=root/'opt/hlauncher';(app/'hlauncher').mkdir(parents=True)
            for name in ('updater.py','update_service.py'):shutil.copy2(ROOT/'hlauncher'/name,app/'hlauncher'/name)
            (app/'hlauncher/__init__.py').write_text('__version__="0.1.0-dev"')
            for name in ('plugins/carplay/runtime/usb/node_modules/usb/package.json',
                         'plugins/carplay/runtime/usb/vendor/node-carplay/CarPlay.js','build/hlauncher-pw-input'):
                path=app/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('fixture')
            deps=root/'opt/hlauncher-deps'
            for name in ('bin/hlauncher-android-auto','bluealsa-buttons/bin/bluealsa','src/engine/source.cpp'):
                path=deps/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('runtime/source fixture')
            (root/'var/lib/dpkg').mkdir(parents=True);(root/'var/lib/dpkg/status').write_text('OS package inventory')
            (root/'var/lib/hlauncher').mkdir();(root/'var/lib/hlauncher/settings.json').write_text('PRIVATE_USER_DATA')
            key=folder/'private.pem'
            subprocess.run(['openssl','genpkey','-algorithm','ED25519','-out',str(key)],check=True,capture_output=True)
            with patch.object(package_release,'verify_storage_image') as verify_boot:
                item=package_release.package(root,persist,'1.0.0',key,out,'a'*40)
            verify_boot.assert_called_once_with(root.resolve())
            config=updater.read(root/'etc/hlauncher-updater/config.json')
            self.assertEqual(updater.validate_manifest(item,config),item)
            self.assertEqual(updater.read(persist/'hlauncher/releases/1.0.0/release.json'),item)
            updater.verify_signature(out/'hlauncher-release.json',out/'hlauncher-release.sig',root/'etc/hlauncher-updater/release.pub')
            extracted=folder/'unpacked';updater.unpack(out/item['archive'],extracted,item['unpacked_size'])
            self.assertEqual((extracted/'app/hlauncher/__init__.py').read_bytes(),
                             (persist/'hlauncher/releases/1.0.0/app/hlauncher/__init__.py').read_bytes())
            self.assertIn("'1.0.0'",(extracted/'app/hlauncher/__init__.py').read_text())
            self.assertEqual(str((root/'opt/hlauncher').readlink()),'/persist/hlauncher/current/app')
            self.assertTrue((root/'usr/lib/hlauncher-updater/update_service.py').is_file())
            for name in (item['archive'],'HLauncher-1.0.0-sources.tar.xz'):
                with tarfile.open(out/name) as archive:
                    names=archive.getnames()
                    self.assertFalse(any('settings.json' in n or 'private.pem' in n for n in names))
            self.assertFalse((out/'private.pem').exists())

    def test_preferences_preserve_future_keys_after_rollback(self):
        from hlauncher.config import Preferences
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings.json'
            path.write_text(json.dumps(dict(enabled={},future_setting={'level':7})))
            prefs=Preferences(path);prefs.set_tile_color('Red')
            self.assertEqual(json.loads(path.read_text())['future_setting'],{'level':7})

    def test_updater_ui_requests_operations_without_running_installer(self):
        from hlauncher.launcher import Launcher
        from hlauncher.config import Preferences
        from test_architecture import Display
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            updater.atomic(folder/'update-status.json',dict(phase='available',current='1.0.0',previous='0.9.0',
                                                          available='1.1.0',size=1048576,message='Update available'))
            ui=Launcher(framebuffer=Display(),preferences=Preferences(folder/'settings.json'),manifests={})
            try:
                ui.updates_page()
                for index,operation in ((1,'check'),(2,'install'),(3,'rollback')):
                    ui.actions[index][1]()
                    self.assertEqual(updater.read(folder/'update-request.json'),dict(operation=operation))
                    (folder/'update-request.json').unlink()
                self.assertEqual(ui.mode,'updates')
                ui.actions[0][1]();self.assertEqual(ui.mode,'system_settings')
            finally:ui.close()


class ReleaseNotes(unittest.TestCase):
    def test_notes_are_readable_wrapped_and_not_truncated_to_the_first_page(self):
        from hlauncher.ui.release_notes import lines
        from sdk.hlauncher_sdk.fonts import font
        from PIL import Image,ImageDraw
        notes="# What's new\n\n- **Audio** improvements\n"+'\n'.join('Change '+str(i) for i in range(60))+'\nLASTNOTE\n'+'x'*500
        rendered=lines(notes)
        self.assertIn("What's new",rendered)
        self.assertIn('• Audio improvements',rendered)
        self.assertIn('LASTNOTE',rendered)
        draw=ImageDraw.Draw(Image.new('RGB',(1,1)))
        self.assertTrue(all(draw.textlength(row,font=font(18))<=672 for row in rendered))
        self.assertIn('No release notes',lines('')[0])

    def test_ui_opens_pages_notes_and_installs_the_version_being_read(self):
        from hlauncher.launcher import Launcher
        from hlauncher.config import Preferences
        from test_architecture import Display
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            info=dict(phase='available',current='1.0.0',previous='0.9.0',available='1.1.0',size=1024,
                      message='Update available',notes_version='1.1.0',notes='\n'.join('Change '+str(i) for i in range(40)))
            updater.atomic(folder/'update-status.json',info)
            ui=Launcher(framebuffer=Display(),preferences=Preferences(folder/'settings.json'),manifests={})
            try:
                ui.updates_page();ui.actions[2][1]()
                self.assertEqual(ui.mode,'update_notes')
                self.assertEqual(ui.release_notes_info['notes_version'],'1.1.0')
                ui.actions[1][1]();self.assertEqual(ui.update_notes_index,1)
                self.assertTrue(any(callback==ui.install_update for _,callback in ui.actions))
                updater.atomic(folder/'update-status.json',dict(info,available='1.2.0'))
                ui.draw()
                self.assertFalse(any(callback==ui.install_update for _,callback in ui.actions))
                updater.atomic(folder/'update-status.json',info);ui.draw()
                next(callback for _,callback in ui.actions if callback==ui.install_update)()
                self.assertEqual(ui.mode,'updates')
                self.assertEqual(updater.read(folder/'update-request.json'),dict(operation='install'))
            finally:ui.close()


class PristineBase(unittest.TestCase):
    def test_official_locked_skeleton_is_allowed_but_personal_data_is_not(self):
        spec=importlib.util.spec_from_file_location('check_base_image',ROOT/'scripts/check_base_image.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'etc/skel').mkdir(parents=True);(root/'home/pi').mkdir(parents=True)
            (root/'etc/os-release').write_text('VERSION_CODENAME=bookworm')
            (root/'etc/machine-id').write_text('')
            (root/'etc/passwd').write_text('root:x:0:0:root:/root:/bin/bash\npi:x:1000:1000:pi:/home/pi:/bin/bash\n')
            (root/'etc/shadow').write_text('pi:!:0:0:99999:7:::\n')
            for name in ('.profile','.bashrc','.bash_logout'):
                (root/'etc/skel'/name).write_text('default');(root/'home/pi'/name).write_text('default')
            module.check(root)
            (root/'home/pi/private.txt').write_text('personal')
            with self.assertRaises(ValueError):module.check(root)
            (root/'home/pi/private.txt').unlink();(root/'etc/machine-id').write_text('booted-machine')
            with self.assertRaises(ValueError):module.check(root)
