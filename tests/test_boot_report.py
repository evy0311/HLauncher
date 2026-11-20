import json
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from scripts.boot_report import command, milestones, report, summarize


class BootReport(unittest.TestCase):
    def test_missing_tools_and_timeouts_are_not_successful_zero_measurements(self):
        for failure in (FileNotFoundError(),subprocess.TimeoutExpired(['fixture'],8)):
            def run(*args,**kwargs):raise failure
            result=command(['fixture'],run)
            self.assertFalse(result['ok'])
            self.assertIn('error',result)

    def test_journal_parsing_separates_process_restarts_and_ignores_other_messages(self):
        def line(pid,phase,time):
            return json.dumps(dict(MESSAGE=json.dumps(dict(state='boot_milestone',pid=pid,phase=phase,boot_ms=time))))
        records=milestones('\n'.join((line(1,'python_entry',100),line(1,'ui_first_frame_submitted',500),
                                      line(2,'python_entry',800),'malformed',json.dumps({'MESSAGE':'private traffic'}))))
        runs=summarize(records)
        self.assertEqual(len(runs),2)
        self.assertEqual(runs[0]['python_entry_to_ui_frame_ms'],400)
        self.assertNotIn('python_entry_to_ui_frame_ms',runs[1])

    def test_collector_only_reads_and_omits_raw_peer_and_bootloader_data(self):
        calls=[]
        def run(args,**kwargs):
            calls.append(args)
            value=''
            if args[0]=='vcgencmd':value='BOOT_ORDER=0xf14\nDISABLE_HDMI=0\nWIFI_PASSWORD=private\n'
            if args[0]=='journalctl':value=json.dumps(dict(MESSAGE=json.dumps(dict(state='audio_packet',phone='private'))))
            return SimpleNamespace(returncode=0,stdout=value,stderr='')
        with patch('scripts.boot_report.read',return_value=None):result=report(run)
        self.assertNotIn('private',json.dumps(result))
        self.assertEqual(result['captures']['bootloader']['settings']['BOOT_ORDER'],'0xf14')
        self.assertFalse(result['firmware_and_screen_wake_measured'])
        self.assertTrue(all(args[0] in ('systemd-analyze','systemctl','findmnt','journalctl','vcgencmd') for args in calls))
        self.assertTrue(all(args[1]=='show' for args in calls if args[0]=='systemctl'))
