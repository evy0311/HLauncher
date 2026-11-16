"""Render a menu from its layout and core-owned actions."""

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from PIL import Image, ImageDraw
from sdk.hlauncher_sdk.fonts import font
from sdk.hlauncher_sdk.theme import dither_rgb565

from .chrome import scale_bounds
from .home import Frame
from .home_art import glyph


SLOTS = 6


@dataclass(frozen=True)
class Item:
    label: str
    action: Callable
    value: str = ''
    icon: object = None


def home_items(pages):
    return [[Item(entry.label, entry.action, icon=entry.icon) if entry else None for entry in page]
            for page in pages]


def slot_box(layout, index):
    if layout == 'grid':
        x, y = 24 + (index % 3) * 228, 124 + (index // 3) * 153
        return x, y, x + 216, y + 140
    y = 86 + index * 59
    return (250 if layout == 'rail' else 24), y, 696, y + 51


def render(theme, layout, title, pages, *, size=(720, 480), page=0, back=None,
           change_page=None, pressed=None, clock=None, footer='', slide=0.0):
    page = min(max(page, 0), len(pages) - 1)
    colors = theme.colors
    image = Image.new('RGB', (720, 480), colors['background'])
    draw = ImageDraw.Draw(image)
    actions = []

    def text(x, y, label, size, color='text', *, width=650, weight=400, anchor='lm'):
        face = font(size, weight)
        label = str(label)
        if draw.textlength(label, font=face) > width:
            while label and draw.textlength(label + '…', font=face) > width:
                label = label[:-1]
            label += '…'
        draw.text((x, y), label, font=face, fill=colors[color], anchor=anchor)

    def button(box, label, callback, *, value='', icon=None, card=False):
        x, y, right, bottom = box
        actual = scale_bounds(box, size)
        selected = pressed == actual and not slide
        outline = colors['accent'] if selected else None if card else colors['muted']
        draw.rounded_rectangle(box, radius=8, fill=colors['panel'],
                               outline=outline, width=2 if selected else 1)
        middle = (y + bottom) // 2
        if card and layout == 'grid':
            if icon:
                artwork = glyph(icon, 48)
                image.paste(artwork, (x + 18, y + 17), artwork)
            text(x + 16, bottom - (52 if value else 31), label, 22,
                 width=right - x - 30, weight=700)
            if value:
                text(x + 16, bottom - 22, value, 16, 'muted', width=right - x - 30)
        else:
            left = x + 16
            if icon:
                artwork = glyph(icon, 32)
                image.paste(artwork, (left, middle - 16), artwork)
                left += 46
            text(left, middle, label, 22 if card else 17,
                 width=right - left - (135 if value else 14), weight=700 if card else 400)
            if value:
                text(right - 16, middle, value, 16, 'accent', width=114, anchor='rm')
        if callback is not None and not slide:
            actions.append((actual, callback))

    offset = round(slide * 720)
    neighbor = page + (-1 if offset > 0 else 1)
    visible = (page, neighbor) if offset and 0 <= neighbor < len(pages) else (page,)
    for index in visible:
        shift = offset + (index - page) * 720
        for slot, item in enumerate(pages[index]):
            if item is None:
                continue
            x, y, right, bottom = slot_box(layout, slot)
            button((x + shift, y, right + shift, bottom), item.label, item.action,
                   value=item.value, icon=item.icon, card=True)

    if layout == 'rail':
        draw.rectangle((0, 0, 232, 479), fill=colors['panel'])
        draw.line((232, 0, 232, 479), fill=colors['accent'], width=2)
        text(24, 112, 'HLauncher', 17, 'muted')
        title_size = 35
        while title_size > 24 and draw.textlength(title, font=font(title_size, 700)) > 184:
            title_size -= 1
        text(24, 160, title, title_size, width=184, weight=700)
        if clock:
            text(24, 220, clock, 30, 'accent')
        if back:
            button((24, 24, 152, 70), 'Back', back)
    else:
        draw.rectangle((0, 0, 719, 72), fill=colors['panel'])
        draw.line((0, 72, 719, 72), fill=colors['accent'], width=2)
        if back:
            button((24, 12, 112, 59), 'Back', back)
        text(136 if back else 24, 36, title, 34, width=450, weight=700)
        if clock:
            text(696, 36, clock, 25, 'accent', anchor='rm')

    if len(pages) > 1 and change_page:
        x = 250 if layout == 'rail' else 24
        if page:
            button((x, 439, x + 100, 478), 'Previous', lambda: change_page(-1))
        text((x + 696) // 2, 458, f'{page + 1} / {len(pages)}', 17, 'muted', anchor='mm')
        if page + 1 < len(pages):
            button((596, 439, 696, 478), 'Next', lambda: change_page(1))
    elif footer:
        text(250 if layout == 'rail' else 24, 455, footer, 16, 'muted', width=438)

    if image.size != size:
        image = image.resize(size, Image.Resampling.LANCZOS)
    return Frame(image, actions, page)


def present(ui, frame):
    ui.actions = frame.actions
    ui.home_clock = datetime.now().strftime('%Y-%m-%d %H:%M')
    ui.fb.image(dither_rgb565(frame.image))


def settings_menu(ui, title, back, items, *, footer=''):
    theme = ui.layout_theme
    layout = theme.layouts.get(ui.mode)
    if layout is None:
        return False
    items = list(items)
    pages = [items[i:i + SLOTS] for i in range(0, len(items), SLOTS)] or [[]]
    key = ui.mode

    def change_page(delta):
        ui.theme_menu_pages[key] = frame.page + delta
        ui.draw()

    frame = render(theme, layout, title, pages, size=(ui.fb.w, ui.fb.h),
                   page=ui.theme_menu_pages.get(key, 0), back=back, change_page=change_page,
                   pressed=ui.pressed_box if ui.press is not None else None,
                   clock=datetime.now().strftime('%-I:%M') if ui.prefs.data['show_clock'] else None,
                   footer=ui.banner or footer)
    present(ui, frame)
    return True
