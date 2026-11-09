"""Persistent password SSH, explicit managed-image enrollment and UI controls."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from hlauncher import ssh_access
from hlauncher.config import Preferences


class SSHAccess(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.folder=self.root/'state';self.system=self.root/'system'
        (self.system/'etc/ssh/sshd_config.d').mkdir(parents=True)
        (self.system/'etc/passwd').write_text('pi:x:1000:1000::/home/pi:/bin/bash\n')
        self.commands=[];self.fake_running=False
    def tearDown(self):self.temp.cleanup()
    def fake_run(self,args,**kwargs):
        self.commands.append((args,kwargs))
        if args[:2]==['systemctl','start']:self.fake_running=True
        if args[:2]==['systemctl','stop'] and args[-1]=='ssh.service':self.fake_running=False
        code=0 if self.fake_running else 3
        return SimpleNamespace(returncode=code if args[:2]==['systemctl','is-active'] else 0)
    def test_initialize_sets_password_once_only_for_managed_image(self):
        ssh_access.initialize(self.folder,self.fake_run,self.system);self.assertFalse(self.commands)
        (self.system/'etc/hlauncher-ssh-managed').write_text('1\n')
        old=self.system/'etc/ssh/sshd_config.d/00-hlauncher-local-test.conf';old.write_text('PasswordAuthentication no\n')
        ssh_access.initialize(self.folder,self.fake_run,self.system)
        self.assertEqual(next(kw['input'] for args,kw in self.commands if args==['chpasswd']),'pi:raspberry\n')
        self.assertFalse(old.exists())
        self.assertTrue((self.system/'run/sshd').is_dir())
        calls=[a for a,_ in self.commands]
        self.assertLess(calls.index(['ssh-keygen','-A']),calls.index(['/usr/sbin/sshd','-t']))
        config=(self.system/'etc/ssh/sshd_config.d/00-hlauncher.conf').read_text()
        self.assertIn('PasswordAuthentication yes',config)
        count=len(self.commands);ssh_access.initialize(self.folder,self.fake_run,self.system)
        self.assertEqual(len(self.commands),count)
    def test_toggle_persists_choice_and_boot_marker(self):
        self.folder.mkdir();(self.folder/'ssh-initialized.json').write_text('{}')
        with patch('hlauncher.ssh_access.shutil.which',return_value='/usr/sbin/sshd'):
            result=ssh_access.apply(True,self.folder,self.fake_run)
            self.assertTrue(result['enabled']);self.assertTrue(Preferences(self.folder/'settings.json').data['ssh_enabled'])
            result=ssh_access.apply(False,self.folder,self.fake_run)
            self.assertFalse(result['enabled']);self.assertTrue((self.folder/'ssh-disabled').exists())
            self.assertFalse(Preferences(self.folder/'settings.json').data['ssh_enabled'])
            ssh_access.apply(False,self.folder,self.fake_run,boot=True)
            self.assertIn((['systemctl','stop','--no-block','ssh.service'],{}),self.commands)
            ssh_access.apply(True,self.folder,self.fake_run)
            self.assertFalse((self.folder/'ssh-disabled').exists())
            self.assertEqual(ssh_access.status(self.folder)['username'],'pi')
    def test_missing_server_and_bad_values(self):
        with self.assertRaises(ValueError):ssh_access.apply('yes',self.folder,self.fake_run)
        with patch('hlauncher.ssh_access.shutil.which',return_value=None):
            with self.assertRaisesRegex(ValueError,'not installed'):ssh_access.apply(True,self.folder,self.fake_run)
        self.assertTrue(Preferences(self.folder/'settings.json').data['ssh_enabled'])
