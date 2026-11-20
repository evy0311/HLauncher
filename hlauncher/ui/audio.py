"""Touch-sized EQ controls within the current radio theme."""
from ..audio_settings import BANDS, EQ_BANDS, LEGACY_EQ_BANDS, LOW_BANDS, EQ_GAIN_LIMIT, PRESETS
from .controls import Page, present
from .chrome import scale_bounds

# Preserve the existing six-control banks and add a small deep-bass bank.
BANKS=(('Low',tuple(LEGACY_EQ_BANDS)[:6]),('High',tuple(LEGACY_EQ_BANDS)[6:]),('Deep bass',tuple(LOW_BANDS)))
PRESET_DETAILS={
    'Flat':'All bands and previous tone gains at 0 dB',
    'Bass lift':'Low-bass weight with less upper-bass emphasis',
    'Deep bass':'Gentle 25–80 Hz lift for deeper bass',
    'Warm':'More bass body with a softer top end',
    'Vocal clarity':'More vocal presence with less low-mid weight',
    'Acoustic':'Light presence and detail for acoustic recordings',
    'Rock':'Bass punch with a little extra presence',
    'Softer treble':'A gentler balance in the upper frequencies',
}


def draw_launcher(launcher):
    settings=launcher.audio_settings;values=settings.values
    def view(*,bank=None,presets=False,users=False):
        if bank is not None:launcher.audio_bank=bank
        launcher.audio_presets_open=presets
        launcher.audio_user_presets=users
        launcher.audio_confirm_save=None
        launcher.press=None;launcher.draw()
    presets=getattr(launcher,'audio_presets_open',False)
    users=presets and getattr(launcher,'audio_user_presets',False)
    page=Page.for_launcher(launcher,'User presets' if users else 'Audio presets' if presets else 'Audio & EQ',
        (lambda:view()) if presets else getattr(launcher,'audio_return',launcher.home),detail=settings.preset_name())

    def apply(name):
        try:changes=settings.preset_changes(name)
        except (OSError,ValueError) as exc:
            launcher.audio_notice=str(exc)[:72];launcher.draw();return
        launcher.audio_presets_open=False
        launcher.change_audio(**changes)

    if presets:
        if users:
            confirm=getattr(launcher,'audio_confirm_save',None)
            def save(name):
                if name in settings.user_presets and getattr(launcher,'audio_confirm_save',None)!=name:
                    launcher.audio_confirm_save=name;launcher.press=None;launcher.draw();return
                try:
                    settings.save_user_preset(name);launcher.audio_notice='Saved '+name
                except (OSError,ValueError) as exc:launcher.audio_notice=str(exc)[:72]
                launcher.audio_confirm_save=None;launcher.press=None;launcher.draw()
            if confirm:
                page.text((24,144),'Replace '+confirm+'?',28)
                page.text((24,192),'Your current EQ curve will replace this saved preset',20)
                page.text((24,232),'The other user preset will stay as saved',20)
                page.button((24,360,352,416),'Cancel',lambda:view(presets=True,users=True),secondary=True,size=22)
                page.button((368,360,696,416),'Save '+confirm,lambda:save(confirm),size=22)
            else:
                for i,name in enumerate(('User 1','User 2')):
                    y=120+i*120;saved=name in settings.user_presets
                    page.button((24,y,352,y+52),name,lambda name=name:apply(name) if name in settings.user_presets else None,
                                settings.preset_name()==name,secondary=settings.preset_name()!=name,size=24)
                    page.button((368,y,696,y+52),'Save current',lambda name=name:save(name),secondary=True,size=22)
                    page.text((24,y+64),'Saved curve · tap to load' if saved else 'Empty · save your current curve',18)
                notice=launcher.audio_notice if launcher.audio_notice not in ('','Saved') else 'Saved presets survive updates and reboots'
                page.text((24,380),page.fit(notice,672,18),18)
                page.button((24,432,696,476),'Factory presets',lambda:view(presets=True),secondary=True,size=22)
        else:
            index=min(1,max(0,getattr(launcher,'audio_presets_page',0)))
            names=list(PRESETS)[index*4:index*4+4]
            def move(delta):
                launcher.audio_presets_page=max(0,min(1,index+delta));launcher.press=None;launcher.draw()
            for i,name in enumerate(names):
                y=112+i*72;selected=settings.preset_name()==name
                page.button((24,y,696,y+44),name,lambda name=name:apply(name),selected,secondary=not selected,size=24)
                page.text((40,y+52),PRESET_DETAILS[name],18)
            page.text((24,408),f'Factory presets  {index+1} / 2 · EQ power stays as selected',16)
            page.button((24,432,184,476),'Previous',lambda:move(-1),secondary=True,size=20)
            page.button((200,432,520,476),'User presets',lambda:view(presets=True,users=True),secondary=True,size=22)
            page.button((536,432,696,476),'Next',lambda:move(1),secondary=True,size=20)
        present(launcher,page);return

    active=values['pipewire'] and values['eq']
    legacy_bypass=values['pipewire'] and not values['eq']
    page.button((24,112,352,160),'EQ bypassed' if legacy_bypass else 'PipeWire '+('On' if active else 'Off'),
                lambda:launcher.change_audio(pipewire=not active,eq=True),active,secondary=not active,size=22)
    page.button((368,112,696,160),'Presets',lambda:view(presets=True),secondary=True,size=22)
    status=('EQ bypassed · your curve is saved' if not active else 'Tap a band, then adjust below')
    if active and any(values[key] for key in BANDS):status='EQ on · includes previous tone gains'
    error=launcher.audio_notice and not launcher.audio_notice.startswith('Saved')
    page.text((24,176),page.fit(launcher.audio_notice if error else status,672,16),16,fill='#efbd82' if error else '#c2c0cc')
    bank=min(2,max(0,getattr(launcher,'audio_bank',0)));keys=BANKS[bank][1]
    selections=getattr(launcher,'audio_selected_bands',{0:'b50',1:'b1k',2:'b25'})
    selected_key=selections.get(bank)
    if selected_key not in keys:selected_key=keys[0]
    def select(key):
        launcher.audio_selected_bands=dict(selections);launcher.audio_selected_bands[bank]=key
        launcher.press=None;launcher.draw()
    limit=12 if any(abs(values['bands'][key])>EQ_GAIN_LIMIT for key in keys) else EQ_GAIN_LIMIT
    ink=page.colors.get('text','#f4f4f7');muted=page.colors.get('muted','#a7a4ae')
    top,bottom=236,356;zero=(top+bottom)//2
    for gain in (limit,0,-limit):
        y=zero-gain/limit*(bottom-top)/2
        page.text((24,y),f'{gain:+d}' if gain else '0',16,anchor='lm')
        page.draw.line((60,y,688,y),fill=page.edge,width=1)
    for i,key in enumerate(keys):
        cx=80+i*112 if len(keys)==6 else 248+i*224
        frequency=EQ_BANDS[key];gain=values['bands'][key];selected=key==selected_key
        label=f'{frequency/1000:g} kHz' if frequency>=1000 else f'{frequency:g} Hz'
        page.text((cx,204),label,20,fill=page.accent if selected else '#c2c0cc',anchor='mt')
        if selected:page.draw.line((cx-28,228,cx+28,228),fill=page.accent,width=2)
        point=zero-gain/limit*(bottom-top)/2
        page.draw.line((cx,top,cx,bottom),fill=page.edge,width=3)
        page.draw.line((cx,zero,cx,point),fill=page.accent if selected else muted,width=3)
        page.draw.rounded_rectangle((cx-16,point-4,cx+16,point+4),radius=2,fill=page.accent if selected else muted)
        page.actions.append((scale_bounds((cx-48,196,cx+48,372),page.size),lambda key=key:select(key)))
    frequency=EQ_BANDS[selected_key];gain=values['bands'][selected_key]
    label=f'{frequency/1000:g} kHz' if frequency>=1000 else f'{frequency:g} Hz'
    gain_label=f'{gain:+d} dB' if gain else '0 dB'
    page.button((24,376,144,424),'−',lambda:launcher.adjust_eq(selected_key,-1),size=32,secondary=True)
    page.text((360,400),f'{label}  ·  {gain_label}',28,fill=ink,anchor='mm')
    page.button((576,376,696,424),'+',lambda:launcher.adjust_eq(selected_key,1),size=32,secondary=True)
    for i,(title,_) in enumerate(BANKS):
        x=24+i*228
        page.button((x,432,x+216,476),title,lambda i=i:view(bank=i),bank==i,size=21,secondary=bank!=i)
    present(launcher,page)
