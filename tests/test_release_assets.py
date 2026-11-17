"""Publication requires complete, authentic fresh-install and update artifacts."""
import json
import lzma
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from scripts.validate_release import assets,validate
from scripts.package_release import local_container
from hlauncher import updater


class ReleaseAssets(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.folder=Path(self.tmp.name);self.version='0.3.0'
        for name in assets(self.version):
            if name not in ('SHA256SUMS','SHA256SUMS.sig','hlauncher-release.sig','release.pub'):(self.folder/name).write_bytes(b'release fixture')
        self.key=self.folder/'private.pem'
        subprocess.run(['openssl','genpkey','-algorithm','ED25519','-out',str(self.key)],check=True,capture_output=True)
        subprocess.run(['openssl','pkey','-in',str(self.key),'-pubout','-out',str(self.folder/'release.pub')],check=True,capture_output=True)
        archive=self.folder/'HLauncher-0.3.0-pi4-arm64.tar.xz'
        self.info=dict(format=1,updater=1,state_schema=1,platform=updater.PLATFORM,system_contract='a'*64,commit='b'*40,
                       local_test=False,version=self.version,archive=archive.name,size=archive.stat().st_size,
                       unpacked_size=1024,sha256=updater.sha256(archive))
        (self.folder/assets(self.version)[0]).write_bytes(lzma.compress(b'\0'*510+b'\x55\xaa'))
        self.sign()
        local_container(self.folder,self.version,archive)
        self.sums()
    def tearDown(self):self.tmp.cleanup()
    def sums(self, sign=True):
        (self.folder/'SHA256SUMS').write_text(''.join(
            updater.sha256(self.folder/name)+'  '+name+'\n' for name in assets(self.version)
            if name not in ('SHA256SUMS', 'SHA256SUMS.sig')))
        if sign:
            subprocess.run(['openssl','pkeyutl','-sign','-rawin','-inkey',str(self.key),
                            '-in',str(self.folder/'SHA256SUMS'),'-out',str(self.folder/'SHA256SUMS.sig')],
                           check=True,capture_output=True)

    def sign(self):
        (self.folder/'hlauncher-release.json').write_text(json.dumps(self.info))
        subprocess.run(['openssl','pkeyutl','-sign','-rawin','-inkey',str(self.folder/'private.pem'),
                        '-in',str(self.folder/'hlauncher-release.json'),'-out',str(self.folder/'hlauncher-release.sig')],check=True,capture_output=True)
        self.sums()
    def test_complete_release_and_each_missing_asset(self):
        self.assertEqual(validate(self.folder,self.version),assets(self.version))
        for name in assets(self.version):
            path=self.folder/name;data=path.read_bytes();path.unlink()
            with self.assertRaisesRegex(ValueError,'Missing release asset'):validate(self.folder,self.version)
            path.write_bytes(data)

    def test_publisher_uploads_only_validated_assets(self):
        notes = self.folder/'RELEASE-NOTES.md'
        notes.write_text('Release notes for the GitHub description.\n')
        (self.folder/'os-packages.txt').write_text('Build inventory\n')
        gh = self.folder/'gh'
        gh.write_text('#!/usr/bin/env python3\nimport json, sys\nprint(json.dumps(sys.argv[1:]))\n')
        gh.chmod(0o755)
        script = Path(__file__).resolve().parents[1]/'scripts/publish_release.sh'
        env = dict(os.environ, PATH=str(self.folder) + os.pathsep + os.environ['PATH'])
        result = subprocess.run(['bash', str(script), self.version, str(self.folder)],
                                env=env, check=True, capture_output=True, text=True)
        command = json.loads(result.stdout.splitlines()[0])
        notes_arg = command.index('--notes-file')
        self.assertEqual(Path(command[notes_arg+1]).resolve(), notes.resolve())
        uploaded = [Path(path).name for path in command[notes_arg+2:]]
        self.assertEqual(uploaded, assets(self.version))
        self.assertNotIn(notes.name, uploaded)
        self.assertNotIn('os-packages.txt', uploaded)
        self.assertNotIn('--prerelease', command)

        self.info['channel'] = 'beta'
        self.sign()
        local_container(self.folder, self.version, self.folder/self.info['archive'])
        self.sums()
        git = self.folder/'git'
        git.write_text('#!/bin/sh\n[ "$1" = merge-base ] && [ "$2" = --is-ancestor ] && '
                       '[ "$4" = refs/remotes/origin/develop ]\n')
        git.chmod(0o755)
        result = subprocess.run(['bash', str(script), self.version, str(self.folder)],
                                env=env, check=True, capture_output=True, text=True)
        command = json.loads(result.stdout.splitlines()[0])
        self.assertIn('--draft', command)
        self.assertIn('--prerelease', command)
        self.assertIn('--latest=false', command)
    def test_local_image_and_missing_compatibility_are_rejected(self):
        for field,value in [('local_test',True),('local_test',None),('system_contract',None),('commit','')]:
            original=dict(self.info);self.info[field]=value;self.sign()
            with self.assertRaises(ValueError):validate(self.folder,self.version)
            self.info=original
    def test_changed_image_cannot_be_released_with_rewritten_unsigned_checksums(self):
        self.sums()
        (self.folder/assets(self.version)[0]).write_bytes(lzma.compress(b'x'*510+b'\x55\xaa'))
        self.sums(sign=False)
        with self.assertRaises(subprocess.CalledProcessError):
            validate(self.folder,self.version)

    def test_signed_checksums_cannot_substitute_another_manual_update(self):
        path = self.folder/assets(self.version)[2]
        local = path.read_bytes()
        start = local.index(b'release fixture')
        path.write_bytes(local[:start]+b'x'+local[start+1:])
        self.sums()
        with self.assertRaisesRegex(ValueError, 'Manual update package'):
            validate(self.folder,self.version)

    def test_updated_app_units_do_not_change_system_contract(self):
        from scripts.package_release import contract
        packaging = self.folder/'packaging'
        packaging.mkdir()
        initial = contract(self.folder)
        (packaging/'hlauncher.service').write_text('[Service]\nTimeoutStartSec=10\n')
        self.assertEqual(contract(self.folder), initial)
        (packaging/'hlauncher-updater.service').write_text('[Service]\nTimeoutStartSec=10\n')
        self.assertNotEqual(contract(self.folder), initial)
