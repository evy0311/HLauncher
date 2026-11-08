"""Resumable setup presented in the shared stock-radio theme."""
import math
from ..onboarding import STEPS
from ..config import TILE_COLORS
from ..setup_state import SetupState
from .controls import Page, present


def draw_launcher(launcher):
    step=launcher.wizard.step
    page=Page('Welcome' if step==0 else STEPS[step],
              (lambda:launcher.setup_next(-1)) if step else None,
              launcher.prefs.data['tile_color'],(launcher.fb.w,launcher.fb.h),
              launcher.pressed_box if launcher.press is not None else None,
              detail=f'{step+1} / {len(STEPS)}')
    if step==0:
        page.label((24,144),'Welcome to HLauncher',30)
        for y,text in ((208,'This initial setup helps you choose your apps,'),
                       (236,'startup screen and color theme.'),
                       (280,'You can also set up Wi-Fi and SD card protection.'),
                       (308,'These choices can be changed later in Settings.')):
            page.text((24,y),text,19)
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
                y=128+i*68
                page.button((24,y,696,y+56),'',action,selected)
                page.label((42,y+7),title,23)
                requirement={'carplay':'USB adapter','android-auto':'USB phone connection','obd':'BLE ELM327 adapter'}.get(pid,'')
                page.text((42,y+34),requirement,14)
                page.text((676,y+28),'Enabled' if selected else 'Disabled',17,anchor='rm')
            else:
                y=128+i*52
                page.button((24,y,696,y+44),'',action,selected)
                page.label((42,y+9),title,24)
                page.text((676,y+22),'Selected' if selected else '',17,anchor='rm')
        if not choices:page.text((24,168),'No apps installed. You can add them later.',18)
        if total>1:
            page.button((480,364,696,400),'More apps',lambda:launcher.setup_more(total),size=17)
    elif step==3:
        for i,name in enumerate(TILE_COLORS):
            x=24+(i%3)*228;y=128+(i//3)*92
            theme=page.theme;page.theme=name
            selected=name==launcher.prefs.data['tile_color']
            page.button((x,y,x+216,y+76),name,
                        lambda name=name:launcher.setup_action(launcher.wizard.theme,name),selected,size=24)
            page.theme=theme
    elif step==4:
        credentials=SetupState(launcher.prefs.path.parent).credentials()
        for i,text in enumerate(('Wi-Fi is optional. Use it for SSH access, debugging,',
                                 'programming new features and future updates.',
                                 'Use the setup page below to connect the Pi to your Wi-Fi.')):
            page.text((24,116+i*24),text,18)
        page.panel((24,196,696,336))
        for i,(label,value) in enumerate((('Network',credentials['ssid']),
                                         ('Password',credentials['password']),
                                         ('Open','http://192.168.4.1:8080'),
                                         ('Username','hlauncher'))):
            y=212+i*28
            page.text((42,y),label,16)
            page.text((248,y),page.fit(value,424,18),18,fill='#efedf6')
        page.button((24,352,696,396),'Enable setup Wi-Fi',lambda:launcher.maintenance('hotspot'),size=21)
    else:
        if launcher.storage_info['available']:
            page.label((24,136),'Protect the SD card?',28)
            for i,text in enumerate(('Reduces the risk of corruption after sudden power loss.',
                                     'System-file changes won’t be saved while it’s enabled.',
                                     'Turn it off in Settings and restart before updates,',
                                     'programming or system configuration changes.',
                                     'HLauncher settings and pairing still save normally.',
                                     'Enable it again and restart when you’re done.')):
                page.text((24,184+i*24),text,18)
            page.button((24,400,348,460),'Finish without protection',
                        lambda:launcher.setup_finish(),size=21,secondary=True)
            page.text((534,376),'Recommended',14,anchor='mt')
            page.button((372,400,696,460),'Enable protection and finish',
                        lambda:launcher.setup_finish(True),selected=True,size=21)
        else:
            page.label((24,144),'Setup complete',28)
            page.text((24,200),'Storage protection is unavailable on this SD card',17)
    if launcher.banner:
        page.text((24,352 if step==5 else (388 if step not in (1,4) else 400)),page.fit(launcher.banner,672,14),14,fill='#efbd82')
    if step!=5 or not launcher.storage_info['available']:
        page.button((480,416,696,460),'Finish' if step==5 else ('Skip' if step==4 else 'Next'),
                    launcher.setup_finish if step==5 else lambda:launcher.setup_next(1),size=23)
    present(launcher,page)
