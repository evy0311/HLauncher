"""Resumable setup presented in the shared stock-radio theme."""
import math
from PIL import ImageDraw
from sdk.hlauncher_sdk.fonts import font
from ..onboarding import REQUIREMENTS, STEPS
from ..config import TILE_COLORS
from .controls import Page, present
from .scroll_list import scrollbar, viewport


WELCOME_TITLE = 'Welcome to HLauncher'

def welcome(page):
    """One welcome panel for early HDMI boot and the setup wizard."""
    page.text((24,144),'First, connect HLauncher to your radio using Bluetooth',19)
    page.text((24,200),'On the radio: Settings > Phone > Connect a phone',18)
    page.text((24,232),'Select Add Bluetooth device, then HLauncher',18)
    page.text((24,296),'Next, choose your apps, startup screen and color theme',17)


SAFETY_NOTICE_LINES = (
    'Stay attentive, follow traffic laws, and keep control of the vehicle.',
    'Set up, change settings, or watch video only while safely parked',
    'with the parking brake engaged. Use the vehicle’s own instruments.',
    'Distraction can injure drivers, passengers, pedestrians, and others.',
)
SAFETY_AGREEMENT_LINES = (
    'I will follow this notice and explain it to other drivers.',
    'I will keep passengers from using HLauncher in ways that distract me.',
    'The driver is responsible for operating the vehicle safely, staying',
    'attentive, and exercising due care toward passengers, pedestrians,',
    'and other road users. The driver may be liable under applicable law',
    'for injury or damage caused by unsafe driving or distracted use of',
    'HLauncher. HLauncher is provided as is, without warranty, under GPLv3.',
    'The license’s liability limits apply to the extent permitted by law.',
)


def safety_notice_text(page):
    for index, line in enumerate(SAFETY_NOTICE_LINES):
        page.text((24, 132 + index * 21), line, 18)


def safety_agreement_text(launcher, page, *, top, bottom, include_notice=False):
    rows = []
    if include_notice:
        rows.extend((line, 18, 23) for line in SAFETY_NOTICE_LINES)
        rows.append(('Safety agreement', 22, 32))
    rows.extend((line, 18, 23) for line in SAFETY_AGREEMENT_LINES)

    # Use the same text width whether or not the scrollbar is visible.
    width = 612
    lines = []
    for text, size, height in rows:
        face = font(size)
        line = ''
        for word in text.split():
            candidate = f'{line} {word}' if line else word
            if line and page.draw.textlength(candidate, font=face) > width:
                lines.append((line, face, height))
                line = word
            else:
                line = candidate
        if line:
            lines.append((line, face, height))

    view = viewport(launcher, top, bottom, sum(height for _, _, height in lines), launcher.mode)
    clip = page.image.crop(view['bounds'])
    draw = ImageDraw.Draw(clip)
    y = -round(view['offset'])
    for line, face, height in lines:
        draw.text((0, y), line, font=face, fill='#e3e0ea', anchor='lt')
        y += height
    page.image.paste(clip, view['bounds'][:2])
    scrollbar(launcher, page, view, step=bottom - top - 24, draggable=False)
    return view['offset'] >= view['maximum']


def draw_safety_notice(launcher):
    page = Page('Safety notice', None, launcher.prefs.data['tile_color'],
                (launcher.fb.w, launcher.fb.h), launcher.pressed_box,
                heading_y=88, show_clock=launcher.prefs.data['show_clock'], layout_theme=getattr(launcher, 'layout_theme', None))
    page.button((24, 408, 240, 460), 'Cancel', launcher.recovery_page, secondary=True)
    reviewed = safety_agreement_text(launcher, page, top=128, bottom=378, include_notice=True)
    if launcher.banner:
        page.notice(launcher.banner, 392)
    if reviewed:
        page.button((416, 408, 696, 460), 'I acknowledge and agree',
                    launcher.accept_safety_notice, selected=True, size=20)
    else:
        page.text((556, 434), 'Scroll to the end to agree', 18, anchor='mm')
    present(launcher, page)


def draw_launcher(launcher):
    step=launcher.wizard.step
    can_exit=getattr(launcher,'setup_can_exit',False)
    title=STEPS[step]
    if step==0:title=WELCOME_TITLE
    elif step==5:title='Protect the SD card?' if launcher.storage_info['available'] else 'Setup complete'
    page=Page(title,
              (lambda:launcher.setup_next(-1)) if step else (launcher.exit_setup if can_exit else None),
              launcher.prefs.data['tile_color'],(launcher.fb.w,launcher.fb.h),
              launcher.pressed_box if launcher.press is not None else None,
              detail='' if can_exit else f'{step+1} / {len(STEPS)}',heading_y=88,show_clock=launcher.prefs.data['show_clock'], layout_theme=getattr(launcher, 'layout_theme', None))
    if can_exit:
        page.text((548,104),f'{step+1} / {len(STEPS)}',16,anchor='rm')
        page.button((568,80,696,124),'Exit',launcher.exit_setup,size=20,secondary=True)
    if step==0:
        welcome(page)
    elif step in (1,2):
        from dataclasses import replace
        choices=sorted(launcher.manifests.values(),key=lambda m:m.id != 'carplay')
        grouped=[]
        projection=False
        for manifest in choices:
            if manifest.id in ('carplay', 'android-auto'):
                if projection:continue
                projection=True
                manifest=replace(manifest,name='Phone Projection')
            grouped.append(manifest)
        choices=grouped
        if step==2:choices=[None]+launcher.home_manifests()
        per_page=3 if step==1 else 4
        total=max(1,math.ceil(len(choices)/per_page))
        launcher.setup_list_page=min(launcher.setup_list_page,total-1)
        for i,m in enumerate(choices[launcher.setup_list_page*per_page:launcher.setup_list_page*per_page+per_page]):
            pid=m.id if m else None
            selected=launcher.prefs.enabled(m) if step==1 else launcher.prefs.data['default_plugin']==pid
            callback=launcher.wizard.plugin if step==1 else launcher.wizard.default
            if step == 1 and pid in ('carplay', 'android-auto'):
                selected=any(launcher.prefs.enabled(launcher.manifests[ident]) for ident in ('carplay','android-auto') if ident in launcher.manifests)
                def action(selected=selected):
                    for ident in ('carplay','android-auto'):
                        if ident in launcher.manifests and launcher.prefs.enabled(launcher.manifests[ident]) == selected:
                            launcher.setup_action(launcher.wizard.plugin, ident)
            else:
                action=lambda pid=pid,callback=callback:launcher.setup_action(callback,pid)
            if step == 2 and pid in ('carplay','android-auto'):
                selected=launcher.prefs.data['default_plugin'] in ('carplay','android-auto')
            title=m.name if m else 'Home'
            if step==1:
                y=144+i*68
                page.button((24,y,696,y+56),'',action,selected)
                page.label((42,y+7),title,23)
                requirement='CarPlay / Android Auto dongle, or direct USB Android Auto' if pid in ('carplay','android-auto') else REQUIREMENTS.get(pid,'')
                page.text((42,y+34),requirement,14)
                page.text((676,y+28),'Enabled' if selected else 'Disabled',17,anchor='rm')
            else:
                y=144+i*52
                page.button((24,y,696,y+44),'',action,selected)
                page.label((42,y+9),title,24)
                page.text((676,y+22),'Selected' if selected else '',17,anchor='rm')
        if not choices:page.text((24,168),'No apps installed. You can add them later.',18)
        if total>1:
            page.button((480,364,696,400),'More apps',lambda:launcher.setup_more(total),size=17)
    elif step == 3 and not launcher.layout_theme.supports_color_selection:
        page.text((24, 144), 'This theme uses a fixed color palette.', 19)
    elif step==3:
        for i,name in enumerate(TILE_COLORS):
            x=24+(i%3)*228;y=144+(i//3)*92
            theme=page.theme;page.theme=name
            selected=name==launcher.prefs.data['tile_color']
            page.button((x,y,x+216,y+76),name,
                        lambda name=name:launcher.setup_action(launcher.wizard.theme,name),selected,size=24)
            page.theme=theme
        page.button((24,332,696,384),'Custom color',launcher.custom_color,selected=launcher.prefs.data['tile_color'].startswith('#'),size=23)
    elif step==4:
        for i,text in enumerate(('Wi-Fi starts off. Set it up for software updates,',
                                 'SSH access or troubleshooting.')):
            page.text((24,136+i*28),text,19)
        page.button((24,224,696,284),'Set up Wi-Fi',launcher.recovery_page,size=24)
        page.text((24,324),'You can also set it up later in System > Wi-Fi',17)
    else:
        if launcher.storage_info['available']:
            for i,text in enumerate(('Reduces the risk of corruption after sudden power loss.',
                                     'System-file changes won’t be saved while it’s enabled.',
                                     'HLauncher updates work while protection is enabled.',
                                     'Turn it off and restart for OS or system-file changes.',
                                     'HLauncher settings and pairing still save normally.',
                                     'Enable it again and restart when you’re done.')):
                page.text((24,144+i*24),text,18)
            page.button((24,400,348,460),'Finish without protection',
                        lambda:launcher.setup_finish(),size=21,secondary=True)
            page.text((534,376),'Recommended',14,anchor='mt')
            page.button((372,400,696,460),'Enable protection and finish',
                        lambda:launcher.setup_finish(True),selected=True,size=21)
        else:
            page.text((24,144),'Storage protection is unavailable on this SD card',17)
    if launcher.banner:
        page.text((24,352 if step==5 else (388 if step not in (1,4) else 400)),page.fit(launcher.banner,672,14),14,fill='#efbd82')
    if step!=5 or not launcher.storage_info['available']:
        page.button((480,416,696,460),'Finish' if step==5 else ('Skip' if step==4 else 'Next'),
                    launcher.setup_finish if step==5 else lambda:launcher.setup_next(1),size=23)
    present(launcher,page)
