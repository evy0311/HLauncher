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
              (launcher.fb.w,launcher.fb.h),launcher.pressed_box if launcher.press is not None else None,show_clock=launcher.prefs.data['show_clock'])
    if launcher.mode == 'update_confirm':
        action = 'Return to stable ' if launcher.confirm_stable_return else 'Install HLauncher '
        page.text((24, 120), action + (launcher.confirm_update_version or ''), 26)
        page.text((24, 190), 'Your plugins and their data will be kept.', 22)
        page.text((24, 230), 'Some plugins may stop working after this update.', 21)
        incompatible = launcher.update_incompatible_plugins
        if incompatible:
            text = f'{len(incompatible)} incompatible: ' + ', '.join(incompatible)
            page.text((24, 277), page.fit(text, 672, 18), 18, fill='#efbd82')
        page.button((24, 350, 340, 410), 'Back', launcher.updates_page, secondary=True)
        page.button((366, 350, 696, 410), 'Restart and install', launcher.confirm_update)
        present(launcher, page)
        return
    busy=info['phase'] in ('checking','downloading','installing')
    page.text((24,120),'Installed',18)
    installed_channel = info.get('current_channel')
    if installed_channel is None:
        installed_channel = read(ROOT/'build-info.json').get('channel')
    suffix = ' · Beta' if installed_channel == 'beta' else ''
    page.text((696,120),info.get('current',__version__)+suffix,20,fill='#efedf6',anchor='rt')
    previous=info.get('previous')
    page.text((24,156),'Previous',18)
    page.text((696,156),previous or 'None',20,fill='#efedf6',anchor='rt')
    for i,line in enumerate(wrap_status(launcher.banner or info.get('message','Ready'),page.draw,font(16),672)[:2]):
        page.text((24,233+i*20),line,16,fill='#dfdce7')
    if not busy and info['phase']!='unavailable':
        page.button((24,292,352 if info.get('notes_version') else 696,336),'Check for updates',lambda:launcher.update_request('check'))
        if info.get('notes_version'):
            page.button((368,292,696,336),'Release notes',launcher.release_notes_page)
        available = info.get('available')
        stable = info.get('stable_available')
        beta_enabled = launcher.prefs.data['include_beta_updates']
        if info.get('available_channel') == 'beta' and not beta_enabled:
            available = stable
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
            page.button((24,348,352 if alternate else 696,392),label,install,selected=True)
            if alternate:
                label = ('Return to stable ' if info.get('stable_return') else 'Install stable ') + alternate
                page.button((368,348,696,392),label,lambda: launcher.install_update(alternate),secondary=True)
        else:
            page.button((24,348,696,392),'Install local update file',launcher.recovery_page,secondary=True)
        if previous:
            page.button((24,404,696,448),'Restore version '+previous,
                        lambda:launcher.update_request('rollback'),secondary=True)
        page.button((24,181,696,222), 'Include beta builds', launcher.toggle_beta_updates, secondary=True)
        page.draw.rectangle((45,191,65,211), outline='#c2c0cc', width=2)
        if beta_enabled:
            page.draw.line(((49,201),(54,207),(62,195)),fill='#ffffff',width=3)
    if info['phase']!='unavailable':page.text((24,460),'Installing or restoring restarts HLauncher · settings are kept',14)
    present(launcher,page)
