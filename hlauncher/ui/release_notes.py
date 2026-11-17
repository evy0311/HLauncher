"""Paged GitHub release notes, rendered as text without HTML or web content."""
from functools import lru_cache
from html import unescape
import re
from PIL import Image, ImageDraw
from sdk.hlauncher_sdk.fonts import font
from ..update_client import status
from .controls import Page, present

PER_PAGE=11


@lru_cache(maxsize=4)
def lines(text):
    text=unescape(str(text)[:128000]).replace('\r','')
    text=re.sub(r'!\[([^\]]*)\]\([^)]*\)',r'[Image: \1]',text)
    text=re.sub(r'\[([^\]]+)\]\([^)]*\)',r'\1',text)
    text=re.sub(r'<[^>]*>','',text)
    draw=ImageDraw.Draw(Image.new('RGB',(1,1)));face=font(18)
    result=[]
    for raw in text.split('\n'):
        if raw.lstrip().startswith('```'):continue
        raw=re.sub(r'^\s{0,3}#{1,6}\s*','',raw).replace('**','').replace('__','').replace('`','').strip()
        raw=''.join(c for c in raw if c.isprintable() or c=='\t')
        if re.fullmatch(r'[-*_]{3,}',raw):raw=''
        if not raw:
            if result and result[-1]:result.append('')
            continue
        if raw.startswith(('- ','* ')):raw='• '+raw[2:]
        line=''
        for word in raw.split():
            # Split long identifiers/URLs so none can extend past the display.
            while draw.textlength(word,font=face)>672:
                if line:result.append(line);line=''
                cut=1
                while cut<len(word) and draw.textlength(word[:cut+1],font=face)<=672:cut+=1
                result.append(word[:cut]);word=word[cut:]
            candidate=(line+' '+word).strip()
            if line and draw.textlength(candidate,font=face)>672:result.append(line);line=word
            else:line=candidate
        if line:result.append(line)
    while result and not result[-1]:result.pop()
    return tuple(result or ['No release notes were provided for this version'])


def draw_launcher(launcher):
    info=launcher.release_notes_info
    text=lines(info.get('notes',''))
    pages=max(1,(len(text)+PER_PAGE-1)//PER_PAGE)
    index=min(launcher.update_notes_index,pages-1);launcher.update_notes_index=index
    page=Page('Release notes',launcher.updates_page,launcher.prefs.data['tile_color'],
              (launcher.fb.w,launcher.fb.h),launcher.pressed_box if launcher.press is not None else None,
              detail=f"{info.get('notes_version','')} · {index+1} / {pages}",show_clock=launcher.prefs.data['show_clock'], layout_theme=getattr(launcher, 'layout_theme', None))
    for i,line in enumerate(text[index*PER_PAGE:(index+1)*PER_PAGE]):
        page.text((24,128+i*24),line,18,fill='#e3e0ea')
    if index>0:page.button((24,416,184,460),'Previous',lambda:launcher.release_notes_move(-1),size=20,secondary=True)
    if index<pages-1:page.button((200,416,360,460),'Next',lambda:launcher.release_notes_move(1),size=20,secondary=True)
    current=status(launcher.prefs.path.parent)
    if (info.get('notes_version') and current.get('available')==info['notes_version'] and
            (current.get('available_channel') != 'beta' or launcher.prefs.data['include_beta_updates']) and
            current.get('phase') not in ('checking','downloading','installing')):
        page.button((392,416,696,460),'Restart and install',launcher.install_update,size=21,selected=True)
    present(launcher,page)
