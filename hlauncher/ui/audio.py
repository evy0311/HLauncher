"""A conventional twelve-band equalizer within the stock-radio shell."""
from ..audio_settings import EQ_BANDS
from .controls import Page, present
from .home import caption
from .chrome import scale_bounds
from . import home_art as art


def draw_launcher(launcher):
    values=launcher.audio_settings.values
    page=Page('Audio & EQ',launcher.home,launcher.prefs.data['tile_color'],
              (launcher.fb.w,launcher.fb.h),
              launcher.pressed_box if launcher.press is not None else None)
    controls=[('PipeWire '+('On' if values['pipewire'] else 'Off'),
               lambda:launcher.change_audio(pipewire=not values['pipewire']),values['pipewire']),
              ('EQ '+('On' if values['eq'] else 'Off'),
               lambda:launcher.change_audio(eq=not values['eq']),values['eq']),
              ('Reset EQ',lambda:launcher.change_audio(**launcher.audio_settings.preset_changes('Flat')),False)]
    for i,(title,action,selected) in enumerate(controls):
        x=24+i*228
        page.button((x,112,x+216,156),title,action,selected,size=21)

    # One uninterrupted bank, rather than twelve nested cards and 24 shiny tiles.
    accent=art.blend(art.accent(page.theme),(230,227,243),.6)
    page.draw.line((24,176,696,176),fill='#3e3744',width=1)
    for i,(key,freq) in enumerate(EQ_BANDS.items()):
        cx=52+i*56;gain=values['bands'][key]
        frequency=f'{freq/1000:g}k' if freq>=1000 else f'{freq:g}'
        page.text((cx,192),frequency,16,fill='#dedce6',anchor='mt')
        for y,title,delta in ((220,'+',1),(388,'−',-1)):
            box=(cx-22,y,cx+22,y+40);actual=scale_bounds(box,page.size)
            page.draw.rounded_rectangle(box,radius=5,fill='#29232f' if page.pressed==actual else '#17141e',
                                        outline=accent if page.pressed==actual else '#4d4356',width=1)
            label=caption(title,24)
            page.image.paste(label,(round(cx-label.width/2),round(y+(40-label.height)/2)),label)
            page.actions.append((actual,lambda key=key,delta=delta:launcher.adjust_eq(key,delta)))
        top,bottom=276,348;zero=(top+bottom)/2;point=zero-gain/12*(bottom-top)/2
        page.draw.line((cx,top,cx,bottom),fill='#514957',width=3)
        page.draw.line((cx-5,zero,cx+5,zero),fill='#a099ac',width=1)
        page.draw.line((cx,zero,cx,point),fill=accent,width=3)
        page.draw.rounded_rectangle((cx-10,point-4,cx+10,point+4),radius=2,fill='#e2dfe9',outline=accent)
        page.text((cx,360),f'{gain:+d}',18,fill='#f4f4f7',anchor='mt')
    # Errors still need to be visible; routine "Saved" and preset prose add noise.
    if launcher.audio_notice and launcher.audio_notice!='Saved':
        page.text((360,448),page.fit(launcher.audio_notice,540,14),14,fill='#efbd82',anchor='mt')
    present(launcher,page)
