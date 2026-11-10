"""Boot protection must really be present and must preserve the data partition."""
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from hlauncher import storage


class Storage(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.boot=self.root/'boot/firmware';self.boot.mkdir(parents=True)
        self.state=self.root/'state';self.state.mkdir()
        (self.root/'etc').mkdir()
        (self.boot/'config.txt').write_text('auto_initramfs=1\n')
        self.original='console=tty1 root=PARTUUID=abc-02 rootwait video=HDMI-A-1:720x480@60D\n'
        (self.boot/'cmdline.txt').write_text(self.original)
        self.kernel='6.12.1+rpt-rpi-v8'
        (self.root/'lib/modules'/self.kernel).mkdir(parents=True)
        (self.boot/'initramfs8').write_bytes(b'boot support')
        (self.root/'boot'/('initrd.img-'+self.kernel)).write_bytes(b'boot support')
        (self.root/'etc/fstab').write_text('# keep comment\nUUID=boot /boot/firmware vfat defaults 0 2\nUUID=root / ext4 defaults,noatime 0 1\nUUID=data /persist ext4 defaults,noatime 0 2\n')
        self.before_fstab=(self.root/'etc/fstab').read_text()
        self.commands=[];self.readonly=False;self.installed=True
        self.members='scripts/init-bottom/overlayroot\nusr/lib/modules/'+self.kernel+'/kernel/fs/overlayfs/overlay.ko\n'
    def tearDown(self):self.temp.cleanup()
    def command(self,args,**kwargs):
        self.commands.append(args)
        if args[0]=='dpkg-query':return SimpleNamespace(stdout='installed' if self.installed else 'not-installed')
        if args[0]=='uname':return SimpleNamespace(stdout=self.kernel)
        if args[0]=='lsinitramfs':return SimpleNamespace(stdout=self.members)
        if args[0]=='findmnt':return SimpleNamespace(stdout=json.dumps({'filesystems':[dict(options='ro' if self.readonly else 'rw')]}))
        if args[0]=='mount':self.readonly='remount,ro' in args
        return SimpleNamespace(stdout='')
    def configure(self,enabled,protected=False):
        with patch.object(storage,'status',return_value=dict(available=True,protected=protected)):
            return storage.configure(enabled,self.command,self.state,system=self.root)
    def transition(self):return json.loads((self.state/'storage-transition.json').read_text())

    def test_enable_protects_only_root_and_keeps_other_boot_arguments(self):
        self.configure(True)
        words=(self.boot/'cmdline.txt').read_text().split()
        self.assertEqual(words,[storage.OVERLAY,*self.original.split()])
        self.assertIn('recurse=0',words[0])
        text=(self.root/'etc/fstab').read_text()
        self.assertIn('defaults,ro',text)
        self.assertIn('UUID=data /persist ext4 defaults,noatime 0 2',text)
        self.assertIn('UUID=root / ext4 defaults,noatime 0 1',text)
        self.assertTrue(self.readonly)
        self.assertEqual(self.transition()['target'],'protected')
        self.assertFalse(any(command[0] in ('apt-get','/usr/bin/raspi-config') for command in self.commands))

    def test_disable_overlay_completes_real_fstab_on_following_boot(self):
        self.configure(True)
        protected_fstab=(self.root/'etc/fstab').read_text()
        self.configure(False,protected=True)
        self.assertEqual((self.boot/'cmdline.txt').read_text(),self.original)
        self.assertEqual((self.root/'etc/fstab').read_text(),protected_fstab)
        self.assertEqual(self.transition()['target'],'writable')
        with patch.object(storage,'status',return_value=dict(available=True,protected=False)):
            storage.finish_transition(self.command,self.state,system=self.root)
        self.assertEqual(self.transition()['target'],'complete')
        self.assertNotIn('defaults,ro',(self.root/'etc/fstab').read_text())
        self.assertFalse(self.readonly)

    def test_missing_package_or_incomplete_boot_image_cannot_report_ready(self):
        self.installed=False
        with self.assertRaisesRegex(ValueError,'missing'):self.configure(True)
        self.installed=True;self.members='scripts/init-top/udev\n'
        with self.assertRaisesRegex(ValueError,'initramfs'):self.configure(True)
        self.members='scripts/init-bottom/overlayroot\nlib/modules/other/kernel/fs/overlayfs/overlay.ko\n'
        with self.assertRaisesRegex(ValueError,'kernel'):self.configure(True)
        self.assertEqual((self.boot/'cmdline.txt').read_text(),self.original)
        self.assertFalse((self.state/'storage-transition.json').exists())

    def test_stale_firmware_copy_and_disabled_autoload_are_rejected(self):
        (self.boot/'initramfs8').write_bytes(b'stale')
        with self.assertRaisesRegex(ValueError,'out of date'):self.configure(True)
        (self.boot/'config.txt').write_text('auto_initramfs=0\n')
        with self.assertRaisesRegex(ValueError,'loading'):self.configure(True)

    def test_failed_configuration_restores_boot_files(self):
        def fail_once(args,**kwargs):
            if args[0]=='sync':raise subprocess.CalledProcessError(1,args)
            return self.command(args,**kwargs)
        with patch.object(storage,'status',return_value=dict(available=True,protected=False)):
            with self.assertRaises(subprocess.CalledProcessError):
                storage.configure(True,fail_once,self.state,system=self.root)
        self.assertEqual((self.boot/'cmdline.txt').read_text(),self.original)
        self.assertEqual((self.root/'etc/fstab').read_text(),self.before_fstab)
        self.assertEqual(self.transition()['target'],'failed')

    def test_reboot_reports_failure_instead_of_leaving_pending_forever(self):
        self.configure(True)
        with patch.object(storage,'status',return_value=dict(available=True,protected=False)):
            storage.finish_transition(self.command,self.state,system=self.root)
        self.assertEqual(self.transition()['target'],'failed')
        self.assertIn('did not activate',self.transition()['message'])
        self.assertEqual(json.loads((self.state/'maintenance-status.json').read_text())['status'],'Failed')

    def test_success_requires_writable_persistent_state_and_an_overlay_root(self):
        self.configure(True)
        with patch.object(storage,'status',return_value=dict(available=True,protected=True)):
            storage.finish_transition(self.command,self.state,system=self.root)
        self.assertEqual(self.transition()['target'],'complete')

    def test_writable_repair_removes_previously_ignored_overlay_flag(self):
        (self.boot/'cmdline.txt').write_text('overlayroot=tmpfs '+self.original)
        self.configure(False,protected=False)
        self.assertEqual((self.boot/'cmdline.txt').read_text(),self.original)
        self.assertFalse(self.readonly)
