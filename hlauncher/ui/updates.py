"""Manual release checks, installation and previous-version restore."""
from .. import __version__
from ..config import ROOT
from ..update_client import status
from ..updater import read
from .controls import Page, present
from .projection import wrap_status
from sdk.hlauncher_sdk.fonts import font


def draw_launcher(launcher):
    info=status(launcher.prefs.path.parent)
    page=Page('Software updates',(launcher.updates_page if launcher.mode == 'update_confirm' else launcher.system_settings),launcher.prefs.data['tile_color'],
              (launcher.fb.w,launcher.fb.h),launcher.pressed_box if launcher.press is not None else None,show_clock=launcher.prefs.data['show_clock'], layout_theme=getattr(launcher, 'layout_theme', None))
    if launcher.mode == 'update_confirm':
        action = 'Return to stable' if launcher.confirm_stable_return else 'Install HLauncher'
        page.text((24,120),action,20)
        page.text((24,152),page.fit(launcher.confirm_update_version or '',672,32),32,fill='#efedf6')
        page.text((24,216),'Your plugins and their data will be kept',20,fill='#efedf6')
        page.text((24,252),'Some plugins may stop working after this update',18)
        incompatible = launcher.update_incompatible_plugins
        if incompatible:
            text = f'{len(incompatible)} incompatible: ' + ', '.join(incompatible)
            for i,line in enumerate(wrap_status(text,page.draw,font(18),672)[:2]):
                page.text((24,292+i*24),line,18,fill='#efbd82')
        page.button((24,368,352,424),'Back',launcher.updates_page,secondary=True,size=22)
        page.button((368,368,696,424),'Restart and install',launcher.confirm_update,selected=True,size=22)
        page.text((24,448),'HLauncher restarts to finish the update',16)
        present(launcher, page)
        return
    busy=info['phase'] in ('checking','downloading','installing')
    page.text((24,120),'Installed',18)
    installed_channel = info.get('current_channel')
    if installed_channel is None:
        installed_channel = read(ROOT/'build-info.json').get('channel')
    suffix = ' · Beta' if installed_channel == 'beta' else ''
    page.text((184,112),page.fit(info.get('current',__version__)+suffix,512,28),28,fill='#efedf6')
    previous=info.get('previous')
    page.text((24,156),'Previous',18)
    page.text((184,156),page.fit(previous or 'None',512,20),20,fill='#efedf6')
    page.draw.line((24,180,696,180),fill=page.edge,width=1)
    message=launcher.banner or info.get('message','Ready')
    if busy or info['phase']=='unavailable':
        heading={'checking':'Checking for updates','downloading':'Downloading update',
                 'installing':'Installing update','unavailable':'Updates unavailable'}[info['phase']]
        page.draw.line((24,208,72,208),fill=page.accent,width=2)
        page.text((24,228),heading,28,fill='#efedf6')
        for i,line in enumerate(wrap_status(message,page.draw,font(22),672)[:4]):
            page.text((24,276+i*28),line,22)
    else:
        for i,line in enumerate(wrap_status(message,page.draw,font(18),672)[:2]):
            page.text((24,244+i*24),line,18,fill='#efedf6')
    if not busy and info['phase']!='unavailable':
        available = info.get('available')
        stable = info.get('stable_available')
        beta_enabled = launcher.prefs.data['include_beta_updates']
        if info.get('available_channel') == 'beta' and not beta_enabled:
            available = stable
        page.button((24,300,352 if info.get('notes_version') else 696,344),'Check for updates',
                    lambda:launcher.update_request('check'),secondary=bool(available),size=22)
        if info.get('notes_version'):
            page.button((368,300,696,344),'Release notes',launcher.release_notes_page,secondary=True,size=22)
        if available:
            alternate = stable if stable != available else None
            if available == stable and info.get('stable_return'):
                label = 'Return to stable ' + available
            elif info.get('available_channel') == 'beta' and available != stable:
                label = 'Install beta ' + available
            else:
                label = 'Install ' + available
            install = launcher.install_update if available == info.get('available') else (
                lambda: launcher.install_update(available))
            page.button((24,356,352 if alternate else 696,400),label,install,selected=True)
            if alternate:
                label = ('Return to stable ' if info.get('stable_return') else 'Install stable ') + alternate
                page.button((368,356,696,400),label,lambda: launcher.install_update(alternate),secondary=True)
        else:
            page.button((24,356,696,400),'Install local update file',launcher.recovery_page,secondary=True)
        if previous:
            page.button((24,412,696,456),'Restore version '+previous,
                        lambda:launcher.update_request('rollback'),secondary=True)
        page.button((24,184,696,228),'',launcher.toggle_beta_updates,secondary=True)
        page.text((80,206),'Include beta builds',20,anchor='lm')
        page.draw.rectangle((44,196,64,216), outline=page.colors.get('muted','#c2c0cc'), width=2)
        if beta_enabled:
            page.draw.line(((48,206),(53,212),(61,200)),fill=page.colors.get('text','#ffffff'),width=3)
    if info['phase']!='unavailable':page.text((24,464),'Installing or restoring restarts HLauncher · settings are kept',14)
    present(launcher,page)
