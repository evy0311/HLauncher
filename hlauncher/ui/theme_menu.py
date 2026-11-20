"""Render a menu from its layout and core-owned actions."""

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from PIL import Image, ImageColor, ImageDraw
from sdk.hlauncher_sdk.fonts import font
from sdk.hlauncher_sdk.palette import PALETTE
from sdk.hlauncher_sdk.theme import dither_rgb565

from .chrome import scale_bounds, draw_wifi
from .home import Frame
from .home_art import blend, glyph


SLOTS = 6
BOTTOM_NAV = ('dock', 'console')
MODERN = ('tiles', 'featured', 'categories', 'menu') + BOTTOM_NAV


@dataclass(frozen=True)
class Item:
    label: str
    action: Callable
    value: str = ''
    icon: object = None
    toggle: bool | None = None


def home_items(pages):
    return [[Item(entry.label, entry.action, icon=entry.icon) if entry else None for entry in page]
            for page in pages]


def row_items(rows):
    for row in rows:
        value = row.value
        if row.toggle is not None:
            value = 'On' if row.toggle else 'Off'
        yield Item(row.title, row.action, value, toggle=row.toggle)


def occupied_slots(page):
    return max((index + 1 for index, item in enumerate(page) if item is not None), default=0)


def slot_box(layout, index, slots=SLOTS):
    if layout == 'dock':
        if index == 0:
            return 24, 84, 696, 240
        shortcuts = slots - 1
        columns = max(1, min(3, shortcuts))
        width = (672 - 12 * (columns - 1)) // columns
        x = 24 + ((index - 1) % columns) * (width + 12)
        y = 264 + ((index - 1) // columns) * 76
        return x, y, x + width, y + (64 if shortcuts > 3 else 128)
    if layout == 'console':
        y = 20 + index * 64
        return 232, y, 696, y + 60
    if layout == 'featured':
        if index == 0:
            return 24, 96, 368, 432
        rows = max(1, slots - 1)
        span = min(84, rows * 28)
        top = 96 + ((index - 1) * span // rows) * 4
        bottom = 96 + (index * span // rows) * 4 - (12 if index < rows else 0)
        return 384, top, 696, bottom
    if layout == 'tiles':
        columns = 2 if slots <= 4 else 3
        width = 328 if columns == 2 else 216
        x = 24 + (index % columns) * (width + (16 if columns == 2 else 12))
        y = 96 + (index // columns) * 176
        return x, y, x + width, y + 160
    if layout == 'categories':
        x, y = 24 + (index % 2) * 344, 96 + (index // 2) * 116
        return x, y, x + 328, y + 104
    if layout == 'menu':
        y = 88 + index * 60
        return 24, y, 696, y + 52
    if layout == 'grid':
        x, y = 24 + (index % 3) * 228, 124 + (index // 3) * 153
        return x, y, x + 216, y + 140
    y = 86 + index * 59
    return (250 if layout == 'rail' else 24), y, 696, y + 51


def resolved_colors(theme, layout, color):
    colors = {key: ImageColor.getrgb(value) for key, value in theme.colors.items()}
    if theme.supports_color_selection and color is not None:
        tint = ImageColor.getrgb(PALETTE.get(color, color))
        if layout in MODERN:
            colors['accent'] = blend(tint, colors['text'], .62)
        else:
            colors['accent'] = blend(tint, colors['text'], .55)
            colors['panel'] = blend(colors['panel'], tint, .35)
    return colors


def render(theme, layout, title, pages, *, size=(720, 480), page=0, back=None,
           change_page=None, pressed=None, clock=None, footer='', slide=0.0, color=None, edit_empty=None):
    page = min(max(page, 0), len(pages) - 1)
    colors = resolved_colors(theme, layout, color)
    image = Image.new('RGB', (720, 480), colors['background'])
    draw = ImageDraw.Draw(image)
    actions = []
    modern = layout in MODERN
    bottom_nav = layout in BOTTOM_NAV
    edge = blend(colors['panel'], colors['text'], .13)
    wifi_right = 696
    if clock and not bottom_nav and layout != 'rail':
        wifi_right -= draw.textlength(clock, font=font(28 if modern else 25)) + 14
    title_right = wifi_right - 52

    def text(x, y, label, size, color='text', *, width=650, weight=400, anchor='lm'):
        face = font(size, weight)
        label = str(label)
        if draw.textlength(label, font=face) > width:
            while label and draw.textlength(label + '…', font=face) > width:
                label = label[:-1]
            label += '…'
        draw.text((x, y), label, font=face, fill=colors[color], anchor=anchor)

    def chevron(x, y, direction=1):
        draw.line([(x - direction * 3, y - 6), (x + direction * 3, y),
                   (x - direction * 3, y + 6)], fill=colors['muted'], width=2)

    def button(box, label, callback, *, value='', icon=None, card=False, featured=False, toggle=None):
        x, y, right, bottom = box
        actual = scale_bounds(box, size)
        selected = pressed == actual and not slide
        outline = colors['accent'] if selected else edge if modern else None if card else colors['muted']
        fill = (blend(colors['panel'], colors['text'], .10)
                if modern and (selected or featured) else colors['panel'])
        if card and layout == 'console':
            if selected:
                draw.rounded_rectangle(box, radius=6, fill=fill, outline=outline, width=2)
            draw.line((x, bottom, right, bottom), fill=edge)
        else:
            radius = 6 if bottom_nav else 12 if card and modern else 8
            draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=2 if selected else 1)
        middle = (y + bottom) // 2
        if modern and not card:
            if label == 'Back':
                chevron(x + 20, middle, direction=-1)
                text(x + 34, middle, label, 18, width=right - x - 46, weight=500)
            else:
                text((x + right) // 2, middle, label, 18, width=right - x - 16, weight=500, anchor='mm')
        elif featured and layout == 'dock':
            draw.rectangle((x + 24, middle - 28, x + 28, middle + 28), fill=colors['accent'])
            left = x + 52
            if icon:
                artwork = glyph(icon, 64)
                image.paste(artwork, (left, middle - 32), artwork)
                left += 88
            text(left, middle - (12 if value else 0), label, 40, width=right - left - 72, weight=600)
            if value:
                text(left, middle + 24, value, 18, 'muted', width=right - left - 72)
            if callback:
                chevron(right - 40, middle)
        elif featured:
            draw.rounded_rectangle((x + 24, y + 24, x + 64, y + 28), radius=2, fill=colors['accent'])
            if icon:
                artwork = glyph(icon, 72)
                image.paste(artwork, (x + 24, middle - 64), artwork)
            text(x + 24, middle + 48, label, 31, width=right - x - 84, weight=600)
            if value:
                text(x + 24, middle + 80, value, 17, 'muted', width=right - x - 48)
            if callback:
                chevron(right - 32, middle + 48)
        elif card and layout == 'dock':
            left = x + 16
            if icon:
                artwork = glyph(icon, 32)
                image.paste(artwork, (left, middle - 16), artwork)
                left += 44
            width = right - left - 12
            text(left, middle - (10 if value else 0), label, 21, width=width, weight=500)
            if value:
                text(left, middle + 14, value, 16, 'muted', width=width)
        elif card and layout == 'tiles':
            if icon:
                artwork = glyph(icon, 50)
                image.paste(artwork, ((x + right - artwork.width) // 2, y + 36), artwork)
            text((x + right) // 2, bottom - 44, label, 24, width=right - x - 32, weight=600, anchor='mm')
            if value:
                text((x + right) // 2, bottom - 19, value, 17, 'muted', width=right - x - 32, anchor='mm')
        elif card and layout == 'grid':
            if icon:
                artwork = glyph(icon, 48)
                image.paste(artwork, (x + 18, y + 17), artwork)
            text(x + 16, bottom - (52 if value else 31), label, 22,
                 width=right - x - 30, weight=700)
            if value:
                text(x + 16, bottom - 22, value, 16, 'muted', width=right - x - 30)
        else:
            left = x + (8 if layout == 'console' else 16)
            if icon:
                artwork = glyph(icon, 32)
                image.paste(artwork, (left, middle - 16), artwork)
                left += 46
            if modern:
                label_size = 25 if layout == 'categories' else 22
                trailing = min(224, (right - left) // 3) if value else 32
                if toggle is not None:
                    trailing = max(120, trailing)
                text(left, middle, label, label_size, width=right - left - trailing - 12, weight=500)
                if toggle is not None:
                    text(right - 76, middle, value, 17, width=trailing - 80, anchor='rm')
                    draw.rounded_rectangle((right - 64, middle - 12, right - 16, middle + 12),
                                           radius=12, fill=colors['accent'] if toggle else edge)
                    center = right - (29 if toggle else 51)
                    draw.ellipse((center - 8, middle - 8, center + 8, middle + 8), fill=colors['background'])
                elif value:
                    text(right - 16, middle, value, 17, 'muted', width=trailing - 16, anchor='rm')
                elif card and callback:
                    chevron(right - 20, middle)
            else:
                text(left, middle, label, 22 if card else 17,
                     width=right - left - (135 if value else 14), weight=700 if card else 400)
            if value and not modern:
                text(right - 16, middle, value, 16, 'accent', width=114, anchor='rm')
        if callback is not None and not slide:
            actions.append((actual, callback))

    offset = round(slide * 720)
    neighbor = page + (-1 if offset > 0 else 1)
    visible = (page, neighbor) if offset and 0 <= neighbor < len(pages) else (page,)
    for index in visible:
        shift = offset + (index - page) * 720
        slots = occupied_slots(pages[index])
        for slot, item in enumerate(pages[index]):
            if item is None:
                continue
            x, y, right, bottom = slot_box(layout, slot, slots)
            button((x + shift, y, right + shift, bottom), item.label, item.action,
                   value=item.value, icon=item.icon, card=True,
                   featured=layout in ('featured', 'dock') and slot == 0,
                   toggle=item.toggle)

    if bottom_nav:
        if layout == 'console':
            text(24, 64, title, 30, width=184, weight=600)
            draw.line((208, 24, 208, 392), fill=edge)
            if footer:
                from .projection import wrap_status

                for line_number, line in enumerate(wrap_status(footer, draw, font(16), 168)):
                    text(24, 116 + 24 * line_number, line, 16, 'muted', width=168)
        else:
            text(24, 36, title, 30, width=title_right-24, weight=600)
        draw.rectangle((0, 420, 719, 479), fill=colors['panel'])
        draw.line((0, 420, 719, 420), fill=edge)
        if back:
            button((24, 428, 128, 476), 'Back', back)
        elif layout == 'dock':
            text(24, 452, 'HLauncher', 18, 'muted')
        if clock:
            text(696, 452, clock, 28, anchor='rm')
    elif layout == 'rail':
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
    elif modern:
        draw.line((24, 72, 696, 72), fill=edge)
        if back:
            button((24, 12, 120, 60), 'Back', back)
        text(144 if back else 24, 36, title, 30, width=title_right-(144 if back else 24), weight=600)
        if clock:
            text(696, 36, clock, 28, anchor='rm')
    else:
        draw.rectangle((0, 0, 719, 72), fill=colors['panel'])
        draw.line((0, 72, 719, 72), fill=colors['accent'], width=2)
        if back:
            button((24, 12, 112, 59), 'Back', back)
        text(136 if back else 24, 36, title, 34, width=title_right-(136 if back else 24), weight=700)
        if clock:
            text(696, 36, clock, 25, 'accent', anchor='rm')

    draw_wifi(image, wifi_right, center_y=36, color=colors['text'], muted=colors['muted'])

    if len(pages) > 1 and change_page:
        if bottom_nav:
            previous_box, next_box, center = (192, 428, 300, 476), (420, 428, 528, 476), (360, 452)
        else:
            x = 250 if layout == 'rail' else 24
            previous_box, next_box, center = (x, 439, x + 100, 478), (596, 439, 696, 478), ((x + 696) // 2, 458)
        if page:
            button(previous_box, 'Previous', lambda: change_page(-1))
        text(*center, f'{page + 1} / {len(pages)}', 17, 'muted', anchor='mm')
        if page + 1 < len(pages):
            button(next_box, 'Next', lambda: change_page(1))
    elif footer and not bottom_nav:
        text(250 if layout == 'rail' else 24, 455, footer, 16, 'muted', width=438)

    if edit_empty and not slide and not any(pages[page]):
        left = 352 if layout == 'rail' else 240
        button((left, 204, left + 240, 268), 'Edit Home', edit_empty)

    if image.size != size:
        image = image.resize(size, Image.Resampling.LANCZOS)
    return Frame(image, actions, page)


def present(ui, frame):
    ui.actions = frame.actions
    ui.home_clock = datetime.now().strftime('%Y-%m-%d %H:%M')
    ui.fb.image(dither_rgb565(frame.image))


def settings_menu(ui, title, back, items, *, footer='', key=None):
    theme = ui.layout_theme
    layout = theme.layouts.get(ui.mode, 'menu' if theme.colors else None)
    if layout is None:
        return False
    items = list(items)
    pages = [items[i:i + SLOTS] for i in range(0, len(items), SLOTS)] or [[]]
    key = key or ui.mode

    def change_page(delta):
        ui.theme_menu_pages[key] = frame.page + delta
        ui.draw()

    frame = render(theme, layout, title, pages, size=(ui.fb.w, ui.fb.h),
                   page=ui.theme_menu_pages.get(key, 0), back=back, change_page=change_page,
                   pressed=ui.pressed_box if ui.press is not None else None,
                   clock=datetime.now().strftime('%-I:%M') if ui.prefs.data['show_clock'] else None,
                   footer=ui.banner or footer, color=ui.prefs.data['tile_color'])
    present(ui, frame)
    return True
