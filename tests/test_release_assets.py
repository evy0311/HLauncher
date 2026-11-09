"""Publication requires complete, authentic fresh-install and update artifacts."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from scripts.validate_release import assets,validate
from hlauncher import updater


class ReleaseAssets(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.folder=Path(self.tmp.name);self.version='0.3.0'
        for name in assets(self.version):
            if name not in ('SHA256SUMS','hlauncher-release.sig','release.pub'):(self.folder/name).write_bytes(b'release fixture')
        key=self.folder/'private.pem'
        subprocess.run(['openssl','genpkey','-algorithm','ED25519','-out',str(key)],check=True,capture_output=True)
        subprocess.run(['openssl','pkey','-in',str(key),'-pubout','-out',str(self.folder/'release.pub')],check=True,capture_output=True)
        archive=self.folder/'HLauncher-0.3.0-pi4-arm64.tar.xz'
        self.info=dict(format=1,updater=1,state_schema=1,platform=updater.PLATFORM,system_contract='a'*64,commit='b'*40,
                       local_test=False,version=self.version,archive=archive.name,size=archive.stat().st_size,
                       unpacked_size=1024,sha256=updater.sha256(archive))
        self.sign()
    def tearDown(self):self.tmp.cleanup()
    def sums(self):
        (self.folder/'SHA256SUMS').write_text(''.join(updater.sha256(self.folder/name)+'  '+name+'\n' for name in assets(self.version) if name!='SHA256SUMS'))
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
    def test_local_image_and_missing_compatibility_are_rejected(self):
        for field,value in [('local_test',True),('local_test',None),('system_contract',None),('commit','')]:
            original=dict(self.info);self.info[field]=value;self.sign()
            with self.assertRaises(ValueError):validate(self.folder,self.version)
            self.info=original
    def test_tampered_asset_even_if_checksums_rewritten_is_rejected(self):
        (self.folder/self.info['archive']).write_bytes(b'modified updater')
        with self.assertRaisesRegex(ValueError,'checksum'):validate(self.folder,self.version)
        self.sums()
        with self.assertRaisesRegex(ValueError,'signed metadata'):validate(self.folder,self.version)
        self.info['sha256']=updater.sha256(self.folder/self.info['archive'])
        self.info['size']=(self.folder/self.info['archive']).stat().st_size
        (self.folder/'hlauncher-release.json').write_text(json.dumps(self.info));self.sums()
        with self.assertRaises(subprocess.CalledProcessError):validate(self.folder,self.version)
