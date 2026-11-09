"""First-boot growth must preserve identity and recover interrupted filesystem growth."""
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from hlauncher.grow_storage import expand


class StorageGrowth(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.mount=Path(self.temp.name)
        self.before=dict(disk='/dev/mmcblk0',source='/dev/mmcblk0p3',number=3,uuid='unique',start=100,
                         disk_bytes=32*1024**3,partition_bytes=512*1024**2)
        self.after=dict(self.before,partition_bytes=30*1024**3)
        self.commands=[]
    def tearDown(self):self.temp.cleanup()
    def fake_run(self,args,**kwargs):
        self.commands.append(args);return SimpleNamespace(returncode=0,stdout='CHANGED: partition=3')

    def test_growth_then_second_boot_skips_work(self):
        values=iter((self.before,self.after))
        self.assertEqual(expand(self.mount,self.fake_run,lambda *a:next(values)),'expanded')
        self.assertEqual(self.commands[-1],['resize2fs','/dev/mmcblk0p3'])
        self.commands.clear()
        self.assertEqual(expand(self.mount,self.fake_run,lambda *a:self.after),'already expanded')
        self.assertFalse(self.commands)
        # Moving this card image to a larger disk must grow again.
        larger=dict(self.after,disk_bytes=64*1024**3)
        values=iter((larger,dict(larger,partition_bytes=62*1024**3)))
        self.assertEqual(expand(self.mount,self.fake_run,lambda *a:next(values)),'expanded')

    def test_partition_already_grown_retries_filesystem_and_does_not_mark_failure_complete(self):
        def run(args,**kwargs):
            if args[0]=='growpart':return SimpleNamespace(returncode=1,stdout='NOCHANGE: already grown')
            raise subprocess.CalledProcessError(1,args)
        with self.assertRaises(subprocess.CalledProcessError):expand(self.mount,run,lambda *a:self.after)
        self.assertFalse((self.mount/'state/storage-expanded.json').exists())
        def retry(args,**kwargs):
            self.commands.append(args)
            return SimpleNamespace(returncode=1 if args[0]=='growpart' else 0,stdout='NOCHANGE: already grown')
        self.assertEqual(expand(self.mount,retry,lambda *a:self.after),'expanded')
        self.assertEqual(json.loads((self.mount/'state/storage-expanded.json').read_text())['uuid'],'unique')

    def test_changed_identity_or_failed_partition_growth_never_resizes_filesystem(self):
        for change in (dict(uuid='different'),dict(start=101),dict(partition_bytes=1)):
            self.commands.clear();values=iter((self.before,dict(self.after,**change)))
            with self.assertRaises(RuntimeError):expand(self.mount,self.fake_run,lambda *a:next(values))
            self.assertFalse(any(c[0]=='resize2fs' for c in self.commands))
        def failed(args,**kwargs):return SimpleNamespace(returncode=2,stdout='FAILED: cannot change table')
        with self.assertRaises(RuntimeError):expand(self.mount,failed,lambda *a:self.before)
        self.assertFalse((self.mount/'state/storage-expanded.json').exists())

    def test_invalid_mount_is_rejected_before_any_mutation(self):
        def reject(*a):raise ValueError('Not an image data partition')
        with self.assertRaises(ValueError):expand(self.mount,self.fake_run,reject)
        self.assertFalse(self.commands)
