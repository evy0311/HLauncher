"""Resumable setup presented in the shared stock-radio theme."""
import math
from ..onboarding import REQUIREMENTS, STEPS
from ..config import TILE_COLORS
from .controls import Page, present


WELCOME_TITLE = 'Welcome to HLauncher'

def welcome(page):
    """One welcome panel for early HDMI boot and the setup wizard."""
    page.text((24,144),'First, connect HLauncher to your radio using Bluetooth',19)
    page.text((24,200),'On the radio: Settings > Phone > Connect a phone',18)
    page.text((24,232),'Select Add Bluetooth device, then HLauncher',18)
    page.text((24,296),'Next, choose your apps, startup screen and color theme',17)


def safety_notice_text(page):
    lines = (
        'The driver is responsible for operating the vehicle safely,',
        'staying attentive, and following applicable laws.',
        'Set up, adjust, or watch video only while safely parked.',
        'Use the vehicle’s instruments for safety-critical information.',
        'HLauncher is provided as is, without warranty, under the GPL.',
        'To the extent permitted by law, HLauncher’s authors and',
        'contributors are not liable for accidents, injuries, property',
        'damage, or other losses arising from use or misuse.',
    )
    for index, line in enumerate(lines):
        page.text((24, 140 + index * 24), line, 20)


def draw_safety_notice(launcher):
    page = Page('Safety notice', None, launcher.prefs.data['tile_color'],
                (launcher.fb.w, launcher.fb.h), launcher.pressed_box,
                heading_y=88, show_clock=launcher.prefs.data['show_clock'])
    safety_notice_text(page)
    page.text((24, 336), 'Cancel opens Wi-Fi for recovery.', 17)
    if launcher.banner:
        page.text((24, 370), launcher.banner, 17, fill='#efbd82')
    page.button((24, 408, 240, 460), 'Cancel', launcher.recovery_page, secondary=True)
    page.button((456, 408, 696, 460), 'I understand', launcher.accept_safety_notice, selected=True)
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
              detail='' if can_exit else f'{step+1} / {len(STEPS)}',heading_y=88,show_clock=launcher.prefs.data['show_clock'])
    if can_exit:
        page.text((548,104),f'{step+1} / {len(STEPS)}',16,anchor='rm')
        page.button((568,80,696,124),'Exit',launcher.exit_setup,size=20,secondary=True)
    if step==0:
        welcome(page)
    elif step in (1,2):
        choices=sorted(launcher.manifests.values(),key=lambda m:m.name)
        if step==2:choices=[None]+[m for m in choices if launcher.prefs.enabled(m)]
        per_page=3 if step==1 else 4
        total=max(1,math.ceil(len(choices)/per_page))
        launcher.setup_list_page=min(launcher.setup_list_page,total-1)
        for i,m in enumerate(choices[launcher.setup_list_page*per_page:launcher.setup_list_page*per_page+per_page]):
            pid=m.id if m else None
            selected=launcher.prefs.enabled(m) if step==1 else launcher.prefs.data['default_plugin']==pid
            callback=launcher.wizard.plugin if step==1 else launcher.wizard.default
            action=lambda pid=pid,callback=callback:launcher.setup_action(callback,pid)
            title=m.name if m else 'Home'
            if step==1:
                y=144+i*68
                page.button((24,y,696,y+56),'',action,selected)
                page.label((42,y+7),title,23)
                requirement=REQUIREMENTS.get(pid,'')
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
