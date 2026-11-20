"""Manual release checks, installation and previous-version restore."""
from .. import __version__
from ..config import ROOT
from ..update_client import status
from ..updater import read
from .controls import Page, present
from .projection import wrap_status
from sdk.hlauncher_sdk.fonts import font


def page_for(launcher,title,back):
    if hasattr(Page,'for_launcher'):
        return Page.for_launcher(launcher,title,back)
    # Source testing can run branches from before themed Page constructors.
    return Page(title,back,launcher.prefs.data['tile_color'],(launcher.fb.w,launcher.fb.h),
                launcher.pressed_box if launcher.press is not None else None,
                show_clock=launcher.prefs.data['show_clock'])


def draw_launcher(launcher):
    info=status(launcher.prefs.path.parent)
    if launcher.mode == 'development_branches':
        return branches(launcher, info)
    page=page_for(launcher,'Software updates',launcher.updates_page if launcher.mode=='update_confirm' else launcher.system_settings)
    if launcher.mode == 'update_confirm':
        source=getattr(launcher,'confirm_update_source',False)
        action = 'Test source ' if source else 'Return to stable ' if launcher.confirm_stable_return else 'Install HLauncher '
        page.text((24, 120), action + (launcher.confirm_update_version or ''), 26)
        branch = getattr(launcher, 'confirm_update_branch', None)
        if branch:
            page.text((24, 160), page.fit(branch+' · '+str(launcher.confirm_update_commit or '')[:8], 672, 20), 20)
        page.text((24, 190), 'Unsigned code from evy0311/HLauncher' if source else 'Your plugins and their data will be kept.', 22)
        page.text((24, 230), 'Previous installation remains available to restore.' if source else 'Some plugins may stop working after this update.', 21)
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
    suffix = ' · Source test' if installed_channel=='source' else ' · Development' if installed_channel == 'development' else ' · Beta' if installed_channel == 'beta' else ''
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
        if (info.get('available_channel') in ('beta', 'development','source') and not beta_enabled
                or info.get('available_channel') in ('development','source') and info.get('available_branch') != launcher.prefs.data['development_branch']
                or info.get('available_channel')=='source' and not launcher.prefs.data.get('source_updates',False)):
            available = stable
        if available:
            alternate = stable if stable != available else None
            if available == stable and info.get('stable_return'):
                label = 'Return to stable ' + available
            elif info.get('available_channel')=='source' and available!=stable:
                label='Install unsigned source'
            elif info.get('available_channel') == 'development' and available != stable:
                label = 'Install branch build'
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
        page.button((24,181,352 if beta_enabled else 696,222), 'Development builds', launcher.toggle_beta_updates, secondary=True)
        if beta_enabled:
            page.button((368,181,696,222), 'Branch: '+launcher.prefs.data['development_branch'], launcher.development_branches_page, size=16, secondary=True)
        branch = info.get('available_branch') or info.get('current_branch')
        commit = info.get('available_commit') or info.get('current_commit')
        if branch:
            detail = str(branch)+' · '+str(commit or '')[:8]
            if info.get('available_built_at'):
                detail += ' · '+str(info['available_built_at'])[:16].replace('T', ' ')+' UTC'
            page.text((24,270), page.fit(detail,672,15), 15)
        page.draw.rectangle((45,191,65,211), outline='#c2c0cc', width=2)
        if beta_enabled:
            page.draw.line(((49,201),(54,207),(62,195)),fill='#ffffff',width=3)
    if info['phase']!='unavailable':page.text((24,460),'Installing or restoring restarts HLauncher · settings are kept',14)
    present(launcher,page)


def branches(launcher, info):
    from .controls import Page, present
    from .scroll_list import Row, draw
    from .theme_menu import settings_menu, row_items
    from ..development_builds import branch_name
    source=launcher.prefs.data.get('source_updates',False)
    rows=[Row('Unsigned source testing',launcher.toggle_source_updates,value='On' if source else 'Off')]
    if launcher.prefs.data['include_beta_updates']:
        for item in info.get('branches', [])[:128]:
            try:name=branch_name(item.get('branch'))
            except (ValueError, AttributeError):continue
            commit=str(item.get('commit', ''))[:8]
            label=('Selected · ' if name == launcher.prefs.data['development_branch'] else '')+name
            rows.append(Row(label,lambda name=name:launcher.select_development_branch(name),value=commit))
    footer=('Select a GitHub branch to test its source' if source else 'Select a branch to check its latest signed build') if len(rows)>1 else 'Check for branches or builds first'
    rows.append(Row('Check for builds',lambda:launcher.update_request('check')))
    if settings_menu(launcher,'Development branch',launcher.updates_page,row_items(rows),footer=footer):return
    page=page_for(launcher,'Development branch',launcher.updates_page)
    draw(launcher,page,rows,bottom=422,key='development-branches',size=22)
    page.notice(launcher.banner or footer)
    present(launcher,page)
