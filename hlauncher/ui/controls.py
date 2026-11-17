"""Shared OEM and palette-themed surfaces for launcher-owned pages."""
from datetime import datetime
from PIL import Image, ImageDraw
from sdk.hlauncher_sdk.fonts import font
from sdk.hlauncher_sdk.theme import dither_rgb565
from . import home_art as art
from .chrome import render as chrome, scale_bounds, BACK_BOUNDS
from .home import caption, Frame


class Page:
    def __init__(self, title, back, theme, size, pressed=None, clock=None, detail='', heading_y=72, show_clock=False, layout_theme=None):
        self.theme,self.size,self.pressed=theme,size,pressed
        from .theme_menu import resolved_colors
        self.colors = (resolved_colors(layout_theme, 'menu', theme)
                       if layout_theme and layout_theme.colors else {})
        self.accent = self.colors.get('accent', art.blend(art.accent(theme), (245, 243, 255), .65))
        self.edge = art.blend(self.colors['panel'], self.colors['text'], .15) if self.colors else '#39333f'
        box=scale_bounds(BACK_BOUNDS,size)
        self.image=chrome(theme,child=back is not None,clock=clock,pressed=pressed==box,show_clock=show_clock,colors=self.colors)
        self.draw=ImageDraw.Draw(self.image)
        self.actions=[(box,back)] if back is not None else []
        self.label((24,heading_y),title,28)
        self.text((696,heading_y+16),detail,16,anchor='rm')

    @classmethod
    def for_launcher(cls, ui, title, back, *, color=None, **options):
        return cls(title, back, color or ui.prefs.data['tile_color'], (ui.fb.w, ui.fb.h),
                   ui.pressed_box if ui.press is not None else None,
                   show_clock=ui.prefs.data['show_clock'],
                   layout_theme=getattr(ui, 'layout_theme', None), **options)

    def label(self,xy,text,size=24):
        if self.colors:
            self.draw.text(xy, str(text), font=font(size, 500), fill=self.colors['text'], anchor='lt')
            return
        label=caption(str(text),size)
        self.image.paste(label,tuple(round(v) for v in xy),label)

    def text(self,xy,text,size=16,fill='#c2c0cc',anchor='lt'):
        if self.colors:
            if fill in ('#ffffff', '#efedf6', '#f4f4f7'):
                fill = self.colors['text']
            elif fill == '#c2c0cc':
                fill = self.colors['muted']
            elif fill == '#efbd82':
                fill = self.accent
        self.draw.text(xy,str(text),font=font(size),fill=fill,anchor=anchor)

    def fit(self,text,width,size=16):
        text=str(text)
        if self.draw.textlength(text,font=font(size))<=width:return text
        while text and self.draw.textlength(text+'…',font=font(size))>width:text=text[:-1]
        return text+'…'

    def panel(self,box):
        x,y,r,b=box
        if self.colors:
            self.draw.rounded_rectangle(box, radius=8, fill=self.colors['panel'], outline=self.edge)
            return
        tile=art.tile(self.theme,r-x,b-y,radius=6,control=True)
        self.image.paste(tile,(x,y),tile)

    def button(self,box,title,action,selected=False,size=20,secondary=False):
        x,y,r,b=box;actual=scale_bounds(box,self.size)
        if self.colors:
            self.draw.rounded_rectangle((x,y,r-1,b-1), radius=8,
                fill=self.colors['background' if secondary else 'panel'],
                outline=self.accent if selected or self.pressed == actual else self.edge)
            self.text(((x+r)//2,(y+b)//2), self.fit(title,r-x-16,size), size, '#ffffff', 'mm')
            self.actions.append((actual,action))
            return
        if secondary:
            self.draw.rounded_rectangle((x,y,r-1,b-1),radius=6,
                fill='#38363e' if self.pressed==actual else '#27262d',
                outline='#93909b' if self.pressed==actual else '#64616d',width=1)
        else:self.panel(box)
        if not secondary and (selected or self.pressed==actual):
            overlay=Image.new('RGBA',(r-x,b-y))
            ImageDraw.Draw(overlay).rounded_rectangle((0,0,r-x-1,b-y-1),radius=6,
                fill=(255,255,255,26 if self.pressed==actual else 12),
                outline=(*art.blend(art.accent(self.theme),(245,243,255),.72),220),width=2)
            self.image.paste(overlay,(x,y),overlay)
        label=caption(title,size)
        self.image.paste(label,(round((x+r-label.width)/2),round((y+b-label.height)/2)),label)
        self.actions.append((actual,action))

    def bar(self,box,title,action,value='',toggle=None,size=24):
        x,y,r,b=box;actual=scale_bounds(box,self.size)
        if self.colors:
            self.panel(box)
            if self.pressed == actual:
                self.draw.rounded_rectangle(box, radius=8, outline=self.accent, width=2)
            tail = ('On' if toggle else 'Off') if toggle is not None else str(value or '›')
            self.text((x+16,(y+b)//2),self.fit(title,r-x-232 if value else r-x-118,min(size,23)),
                      min(size,23),'#ffffff','lm')
            self.text((r-16,(y+b)//2), self.fit(tail,192,18),18,anchor='rm',
                      fill=self.accent if toggle else '#c2c0cc')
            self.actions.append((actual,action))
            return
        surface=art.settings_bar(self.theme,r-x,b-y)
        self.image.paste(surface,(x,y))
        if self.pressed==actual:
            overlay=Image.new('RGBA',(r-x,b-y),(255,255,255,25))
            self.image.paste(overlay,(x,y),overlay)
        available=(r-x)-224 if value or toggle is not None else r-x-48
        label=caption(title,size)
        while label.width>available and title:
            title=title[:-1];label=caption(title+'…',size)
        self.image.paste(label,(x+16,y+(b-y-label.height)//2),label)
        if toggle is not None:
            left=r-176;mid=r-96
            for a,z,label,selected in ((left,mid,'Off',not toggle),(mid,r-16,'On',toggle)):
                self.draw.rectangle((a,y+7,z-1,b-8),fill=art.blend(art.accent(self.theme),(210,198,204),.20) if selected else '#201b22',outline='#76616c' if selected else '#382a32')
                self.text(((a+z)//2,(y+b)//2),label,min(23,size-5),anchor='mm',fill='#faf5f7' if selected else '#a69aa3')
        elif value:
            self.draw.rectangle((r-216,y+7,r-16,b-8),fill='#231b23')
            for value_size in range(min(26,size),15,-1):
                text=caption(str(value),value_size)
                if text.width<=184:break
            if text.width>184:text=caption(self.fit(value,184,16),16)
            self.image.paste(text,(r-116-text.width//2,(y+b-text.height)//2),text)
        else:
            self.draw.line([(r-28,(y+b)//2-7),(r-22,(y+b)//2),(r-28,(y+b)//2+7)],fill='#d7cbd2',width=2)
        if toggle is None:self.actions.append((actual,action))
        else:
            # Each segment selects its value; pressing On again leaves it on.
            self.actions.append((scale_bounds((x,y,r-176,b),self.size),action))
            self.actions.append((scale_bounds((r-176,y,r-96,b),self.size),lambda:action() if toggle else None))
            self.actions.append((scale_bounds((r-96,y,r,b),self.size),lambda:action() if not toggle else None))

    def row(self,y,title,detail,action):
        self.bar((24,y,696,y+44),title,action,value=detail)

    def toggle_row(self,y,title,enabled,action):
        self.bar((24,y,696,y+44),title,action,toggle=enabled)

    def info(self,y,title,value):
        self.text((24,y),title,16)
        self.text((252,y),self.fit(value,444,17),17,fill='#efedf6')
        self.draw.line((24,y+28,696,y+28),fill=self.edge)

    def notice(self,text,y=452):
        if text:self.text((24,y),self.fit(text,672,14),14,fill='#efbd82')

    def frame(self):
        image=self.image if self.size==(720,480) else self.image.resize(self.size,Image.Resampling.LANCZOS)
        return Frame(image,self.actions,0)


def present(launcher,page, *, dither=True, exact=False, calibration=False):
    frame=page.frame()
    launcher.actions=frame.actions
    launcher.home_clock=datetime.now().strftime('%Y-%m-%d %H:%M')
    if not dither:
        height=round(52*launcher.fb.h/480)
        frame.image.paste(dither_rgb565(frame.image.crop((0,0,launcher.fb.w,height))),(0,0))
    if calibration and hasattr(launcher.fb,'image_test'):launcher.fb.image_test(frame.image,exact=exact)
    elif exact and hasattr(launcher.fb,'image_exact'):launcher.fb.image_exact(frame.image)
    else:launcher.fb.image(dither_rgb565(frame.image) if dither else frame.image)
