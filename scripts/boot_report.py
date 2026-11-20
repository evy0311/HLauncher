#!/usr/bin/env python3
"""Read-only boot evidence. Pipe stdout to a dated report on the research share."""
import json
import platform
from pathlib import Path
import subprocess

LIMIT = 128 * 1024
UNITS = ('hlauncher.service', 'hlauncher-updater.service', 'hlauncher-audio.service',
         'hlauncher-pairing.service', 'hlauncher-connect.service', 'hlauncher-recovery.service',
         'NetworkManager-wait-online.service', 'rpi-eeprom-update.service', 'e2scrub_reap.service')
PROPERTIES = ('Id', 'Type', 'After', 'Wants', 'Requires', 'ActiveState', 'SubState',
              'ExecMainStartTimestampMonotonic', 'ActiveEnterTimestampMonotonic', 'NRestarts')


def command(args, run=subprocess.run):
    try:
        result = run(args, capture_output=True, text=True, timeout=8, check=False)
        return dict(ok=result.returncode == 0, returncode=result.returncode,
                    stdout=result.stdout[:LIMIT], stderr=result.stderr[:4096])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return dict(ok=False, error=type(exc).__name__)


def read(path):
    try:
        with Path(path).open() as source:
            return source.read(65536).replace('\0', '').strip()
    except OSError:
        return None


def milestones(lines):
    records = []
    for line in lines.splitlines():
        try:
            event = json.loads(json.loads(line)['MESSAGE'])
            if (event.get('state') != 'boot_milestone' or type(event.get('pid')) is not int
                    or not isinstance(event.get('phase'), str)
                    or type(event.get('boot_ms')) not in (float, int)):
                continue
            records.append({key: event[key] for key in ('phase', 'pid', 'boot_ms', 'process_ms') if key in event})
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    return records


def summarize(records):
    runs = {}
    for record in records:
        phases = runs.setdefault(record['pid'], {})
        phases.setdefault(record['phase'], record['boot_ms'])
    result = []
    for pid, phases in runs.items():
        item = dict(pid=pid, phases_ms_after_kernel_start=phases)
        if 'python_entry' in phases and 'ui_first_frame_submitted' in phases:
            item['python_entry_to_ui_frame_ms'] = round(phases['ui_first_frame_submitted']-phases['python_entry'], 3)
        result.append(item)
    return result


def report(run=subprocess.run):
    captures = dict(
        system_time=command(['systemd-analyze', 'time'], run),
        launcher_chain=command(['systemd-analyze', 'critical-chain', 'hlauncher.service'], run),
        reconnect_chain=command(['systemd-analyze', 'critical-chain', 'hlauncher-connect.service'], run),
        blame=command(['systemd-analyze', 'blame', '--no-pager'], run),
        units=command(['systemctl', 'show', *UNITS, '--no-pager', '--property='+','.join(PROPERTIES)], run),
        root_mount=command(['findmnt', '--json', '--target', '/', '--output', 'TARGET,FSTYPE'], run),
    )
    journal = command(['journalctl', '-b', '-u', 'hlauncher.service', '-o', 'json',
                       '--no-pager', '--grep=boot_milestone', '-n', '128'], run)
    records = milestones(journal.pop('stdout', ''))
    captures['milestone_journal'] = journal
    eeprom = command(['vcgencmd', 'bootloader_config'], run)
    allowed = {'BOOT_ORDER', 'BOOT_UART', 'DISABLE_HDMI', 'HDMI_DELAY', 'POWER_OFF_ON_HALT', 'WAKE_ON_GPIO'}
    settings = {}
    for line in eeprom.pop('stdout', '').splitlines():
        key, separator, value = line.partition('=')
        if separator and key in allowed:
            settings[key] = value[:128]
    eeprom['settings'] = settings
    captures['bootloader'] = eeprom
    config = read('/boot/firmware/config.txt') or read('/boot/config.txt') or ''
    boot_lines = [line for line in config.splitlines() if line.strip().startswith(
        ('auto_initramfs=', 'initramfs ', 'boot_delay=', 'disable_splash=', 'dtoverlay=vc4', 'hdmi_force_hotplug='))]
    return dict(format=1, model=read('/proc/device-tree/model'), kernel=platform.release(),
                boot_id=read('/proc/sys/kernel/random/boot_id'), uptime=read('/proc/uptime'),
                firmware_and_screen_wake_measured=False, selected_boot_config=boot_lines,
                milestones=records, processes=summarize(records), captures=captures,
                interpretation=['Milestone times start at the kernel clock, not ignition/power-on.',
                    'Frame submission does not prove the Honda radio has displayed HDMI yet.',
                    'Missing markers require the instrumented app and journal access; they are not zero timings.'])


if __name__ == '__main__':
    print(json.dumps(report(), indent=2))
