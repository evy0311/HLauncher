"""Signed branch offers, explicit switching, recovery and opt-in enforcement."""
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
import test_updater as fixtures
from hlauncher import updater, update_client
from hlauncher.channel_updates import ChannelService, ChannelInstaller, RELEASES, ASSETS
from hlauncher.development_builds import branch_name, metadata, build_version


class DevelopmentUpdates(unittest.TestCase):
    setUp = fixtures.Updates.setUp
    tearDown = fixtures.Updates.tearDown
    manifest = fixtures.Updates.manifest
    bundle = fixtures.Updates.bundle

    def catalogue(self, *snapshots):
        downloads = {}
        def release(bundle, development=False):
            manifest, signature, archive = bundle
            info = updater.read(manifest)
            tag = ('dev-' if development else 'v')+info['version']
            assets=[]
            for name,path in [('hlauncher-release.json',manifest),('hlauncher-release.sig',signature),(info['archive'],archive)]:
                url=ASSETS+tag+'/'+name
                downloads[url]=path.read_bytes()
                assets.append(dict(name=name,browser_download_url=url))
            return dict(tag_name=tag,prerelease=development,draft=False,assets=assets)
        stable=release(self.bundle('1.1.0'))
        releases=[release(bundle, True) for bundle in snapshots]
        downloads[RELEASES+'/latest']=json.dumps(stable).encode()
        downloads[RELEASES+'?per_page=50']=json.dumps(releases).encode()
        def fetch(url,path,maximum,expected=None):
            value=downloads[url]
            self.assertLessEqual(len(value), maximum)
            if expected is not None:self.assertEqual(len(value),expected)
            path.write_bytes(value)
        installer=ChannelInstaller(self.config,run=self.installer.run,health=lambda *_:None)
        service=ChannelService(self.config,self.state,fetch=fetch,installer=installer)
        self.installer=installer
        return service,downloads

    def snapshot(self, version, branch='develop', **extra):
        return self.bundle(version,channel='development',branch=branch,commit='b'*40,
                           built_at='2026-11-20T15:00:00+00:00',build_id=version,**extra)

    def settings(self, branch='develop', enabled=True):
        updater.atomic(self.state/'settings.json',dict(include_beta_updates=enabled,development_branch=branch))

    def test_branch_switch_can_install_older_snapshot_and_restore_exact_previous(self):
        newer=self.snapshot('10000.0.2','feature/audio')
        older=self.snapshot('10000.0.1','develop')
        service,_=self.catalogue(newer,older)
        self.settings('feature/audio')
        service.check()
        status=update_client.status(self.state)
        self.assertEqual(status['available_branch'],'feature/audio')
        self.assertEqual({row['branch'] for row in status['branches']},{'feature/audio','develop'})
        service.install_version('10000.0.2')
        self.settings('develop');service.check();service.install_version('10000.0.1')
        self.assertEqual(self.installer.status(),dict(current='10000.0.1',previous='10000.0.2'))
        self.installer.rollback();self.assertEqual(self.installer.current(),'10000.0.2')
        self.settings('develop',False);service.check()
        self.assertTrue(update_client.status(self.state)['stable_return'])
        service.install_version('1.1.0')
        self.assertEqual(self.installer.current_channel(),'stable')
        self.assertEqual(updater.read(self.state/'settings.json')['development_branch'],'develop')

    def test_opt_in_and_branch_are_rechecked_before_install(self):
        service,_=self.catalogue(self.snapshot('10000.0.1'))
        self.settings(enabled=False);service.check()
        self.assertFalse(update_client.status(self.state)['branches'])
        self.settings();service.check()
        self.settings('feature/other')
        with self.assertRaisesRegex(ValueError,'selected branch changed'):service.install_version('10000.0.1')
        self.settings(enabled=False)
        with self.assertRaisesRegex(ValueError,'Enable beta'):service.install_version('10000.0.1')
        self.assertEqual(self.installer.current(),'1.0.0')

    def test_bad_signature_and_wrong_contract_are_not_offered(self):
        bad=self.snapshot('10000.0.1','feature/bad')
        incompatible=self.snapshot('10000.0.2','feature/wrong-os',system_contract='other')
        service,downloads=self.catalogue(bad,incompatible)
        downloads[ASSETS+'dev-10000.0.1/hlauncher-release.sig']=b'bad signature'
        self.settings('feature/bad');service.check()
        self.assertEqual(update_client.status(self.state)['branches'],[])
        self.assertEqual(update_client.status(self.state)['available'],'1.1.0')

    def test_exact_selected_commit_and_packaged_runtime_survive_install_and_failed_switch(self):
        service,_=self.catalogue(self.snapshot('10000.0.1'),self.snapshot('10000.0.2','feature/failed'))
        self.settings();service.check();service.install_version('10000.0.1')
        self.assertEqual((self.root/'current/runtime/library.so').read_text(),'native fixture')
        self.settings('feature/failed');service.check()
        self.installer.health=lambda *_:(_ for _ in ()).throw(RuntimeError('fixture startup failed'))
        with self.assertRaisesRegex(RuntimeError,'previous version was restored'):service.install_version('10000.0.2')
        self.assertEqual(self.installer.current(),'10000.0.1')
        self.assertNotIn('pending',updater.read(self.installer.state_path))

    def test_offer_metadata_is_reverified_before_install(self):
        service,_=self.catalogue(self.snapshot('10000.0.1'))
        self.settings();service.check()
        path=service.cache/'development-10000.0.1/manifest.json'
        value=updater.read(path);value['branch']='feature/substituted';updater.atomic(path,value)
        with self.assertRaises(subprocess.CalledProcessError):service.install_version('10000.0.1')
        self.assertEqual(self.installer.current(),'1.0.0')

    def test_branch_changed_during_download_does_not_stop_services(self):
        service,_=self.catalogue(self.snapshot('10000.0.1'))
        self.settings();service.check()
        original=service.fetch
        def fetch(url,path,maximum,expected=None):
            original(url,path,maximum,expected)
            if expected is not None:self.settings('feature/changed')
        service.fetch=fetch
        before=list(self.calls)
        with self.assertRaisesRegex(ValueError,'changed during download'):service.install_version('10000.0.1')
        self.assertEqual(self.calls,before)
        self.assertEqual(self.installer.current(),'1.0.0')

    def test_latest_per_branch_is_selected_by_build_identity(self):
        service,_=self.catalogue(self.snapshot('10000.0.1'),self.snapshot('10000.0.3'),self.snapshot('10000.0.2','feature/other'))
        self.settings();service.check()
        self.assertEqual(update_client.status(self.state)['available'],'10000.0.3')
        self.assertEqual(len(update_client.status(self.state)['branches']),2)


class DevelopmentIdentity(unittest.TestCase):
    def test_ref_names_and_legacy_compatible_unique_versions(self):
        self.assertEqual(branch_name('feature/audio-fix'),'feature/audio-fix')
        for name in ('../escape','-flag','a//b','a.lock','a@{b','a b','a\\b','a..b','a/.hidden'):
            with self.assertRaises(ValueError):branch_name(name)
        numbers=(0,99999,100000,100000**2,123456789012)
        versions=[build_version(number) for number in numbers]
        self.assertEqual(len(set(versions)),len(numbers))
        for version in versions:updater.version(version)
        for number in (-1,True,90000*100000**2):
            with self.assertRaises(ValueError):build_version(number)

    def test_metadata_requires_commit_date_and_reserved_version(self):
        item=dict(version='10000.0.1',branch='develop',commit='a'*40,built_at='2026-11-20T15:00:00Z',build_id='run-1')
        metadata(item)
        for key,value in (('version','1.0.0'),('commit','develop'),('built_at','yesterday'),('built_at','2026-11-20T15:00:00'),('build_id','')):
            with self.assertRaises(ValueError):metadata(dict(item,**{key:value}))

class DevelopmentUI(unittest.TestCase):
    import test_radio_ui as _fixtures
    setUp = _fixtures.RadioUI.setUp
    tearDown = _fixtures.RadioUI.tearDown

    def test_branch_picker_selection_persists_and_requests_a_fresh_check(self):
        from hlauncher.config import Preferences
        ui=self.ui
        ui.toggle_beta_updates()
        updater.atomic(ui.prefs.path.parent/'update-status.json',dict(
            phase='available',current='1.0.0',available='10000.0.1',available_channel='development',
            available_branch='feature/audio',available_commit='a'*40,available_built_at='2026-11-20T15:00:00Z',
            branches=[dict(branch='feature/audio',version='10000.0.1',commit='a'*40)]))
        ui.updates_page()
        self.assertIn(ui.development_branches_page,[action for _,action in ui.actions])
        ui.development_branches_page()
        with patch.object(ui,'update_request') as request:
            next(action for box,action in ui.actions if box[:2]==(24,128))()
            request.assert_called_once_with('check')
        self.assertEqual(Preferences(ui.prefs.path).data['development_branch'],'feature/audio')
        self.assertEqual(ui.mode,'updates')
        ui.install_update()
        self.assertEqual(ui.confirm_update_branch,'feature/audio')
        self.assertEqual(ui.confirm_update_commit,'a'*40)
        ui.toggle_beta_updates()
        ui.updates_page()
        self.assertNotIn(ui.development_branches_page,[action for _,action in ui.actions])


class DevelopmentPackaging(unittest.TestCase):
    def test_signed_metadata_reaches_both_image_and_update(self):
        import shutil
        import tempfile
        package=fixtures.package_release
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary);root=folder/'image';persist=folder/'persist';output=folder/'release'
            (root/'etc').mkdir(parents=True);persist.mkdir()
            (root/'etc/os-release').write_text('VERSION_CODENAME=bookworm\n')
            app=root/'opt/hlauncher';(app/'hlauncher').mkdir(parents=True)
            for name in ('updater.py','update_service.py'):
                shutil.copy2(fixtures.ROOT/'hlauncher'/name,app/'hlauncher'/name)
            for name in ('plugins/carplay/runtime/usb/node_modules/usb/package.json',
                         'plugins/carplay/runtime/usb/vendor/node-carplay/CarPlay.js','build/hlauncher-pw-input'):
                path=app/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('fixture')
            for name in ('bin/hlauncher-android-auto','bluealsa-buttons/bin/bluealsa'):
                path=root/'opt/hlauncher-deps'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('fixture')
            (root/'var/lib/dpkg').mkdir(parents=True);(root/'var/lib/dpkg/status').write_text('fixture')
            key=folder/'key.pem'
            subprocess.run(['openssl','genpkey','-algorithm','ED25519','-out',str(key)],check=True,capture_output=True)
            with patch.object(package,'verify_storage_image'),patch.dict('os.environ',HLAUNCHER_RELEASE_BRANCH='feature/test',HLAUNCHER_RELEASE_BUILD_ID='run-123'):
                item=package.package(root,persist,'10000.0.1',key,output,'a'*40,channel='development')
            metadata(item)
            updater.verify_signature(output/'hlauncher-release.json',output/'hlauncher-release.sig',output/'release.pub')
            updater.unpack(output/item['archive'],folder/'unpacked',item['unpacked_size'])
            info=updater.read(folder/'unpacked/app/build-info.json')
            self.assertEqual(info['branch'],'feature/test')
            self.assertEqual(info['commit'],item['commit'])
            self.assertEqual(info['build_id'],'run-123')

class DevelopmentPublication(unittest.TestCase):
    import test_release_assets as _fixtures
    setUp = _fixtures.ReleaseAssets.setUp
    tearDown = _fixtures.ReleaseAssets.tearDown
    sums = _fixtures.ReleaseAssets.sums
    sign = _fixtures.ReleaseAssets.sign

    def test_development_publication_requires_complete_signed_assets_and_uses_prerelease_tag(self):
        import os
        from scripts.validate_release import assets,validate
        from scripts.package_release import local_container
        old=self.version;self.version='10000.0.1'
        for name in assets(old):
            if old in name:(self.folder/name).rename(self.folder/name.replace(old,self.version))
        archive=self.folder/f'HLauncher-{self.version}-pi4-arm64.tar.xz'
        self.info.update(version=self.version,archive=archive.name,channel='development',branch='feature/test',
                         build_id='run-123',built_at='2026-11-20T15:00:00Z')
        self.sign();local_container(self.folder,self.version,archive);self.sums()
        self.assertEqual(validate(self.folder,self.version),assets(self.version))
        (self.folder/'RELEASE-NOTES.md').write_text('Development test build.\n')
        gh=self.folder/'gh'
        gh.write_text('#!/usr/bin/env python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n');gh.chmod(0o755)
        script=fixtures.ROOT/'scripts/publish_release.sh'
        result=subprocess.run(['bash',str(script),'--publish-development',self.version,str(self.folder)],
                              env=dict(os.environ,PATH=str(self.folder)+os.pathsep+os.environ['PATH']),
                              check=True,capture_output=True,text=True)
        command=json.loads(result.stdout.splitlines()[0])
        self.assertEqual(command[:3],['release','create','dev-'+self.version])
        self.assertIn('--prerelease',command);self.assertIn('--latest=false',command)
        self.assertNotIn('--draft',command)
        (self.folder/assets(self.version)[0]).unlink()
        with self.assertRaisesRegex(ValueError,'Missing release asset'):validate(self.folder,self.version)
