"""The wizard welcome screen, shown while the radio connects at boot."""
from .controls import Page
from .onboarding import welcome, WELCOME_TITLE
from . import home_art as art


def render(credentials=None, paired=False, theme='Red',size=(720,480),show_clock=False,layout_theme=None):
    p=Page(WELCOME_TITLE,None,theme,size,heading_y=88,show_clock=show_clock,layout_theme=layout_theme)
    welcome(p)
    if p.colors:
        p.panel((24,408,696,452))
    else:
        p.image.paste(art.settings_bar(theme,672,44),(24,408))
    p.text((360,430),'Waiting for radio connection…' if paired else 'Waiting for Bluetooth pairing…',18,anchor='mm',fill='#efedf6')
    return p.frame().image
