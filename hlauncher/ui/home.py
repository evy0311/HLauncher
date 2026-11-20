"""Stock-era home screen only; no dependency on Bluetooth, plugins or framebuffer."""
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Callable
from PIL import Image, ImageDraw, ImageFont
from sdk.hlauncher_sdk.fonts import font as interface_font
from . import home_art as art
from .chrome import render as render_chrome

FONT = Path(__file__).parent/'assets/fonts/NotoSansJP.ttf'
LABEL_SIZE = 26
LABEL_WIDTH = .84


@lru_cache(maxsize=48)
def label_font(size):
    face=ImageFont.truetype(str(FONT),size)
    face.set_variation_by_axes([700])
    return face


@lru_cache(maxsize=128)
def caption(text, size):
    """Match the factory's compact proportions with antialiased label artwork."""
    scale=3;face=label_font(size*scale);left,top,right,bottom=face.getbbox(text)
    image=Image.new('RGBA',(right-left+6,bottom-top+6))
    ImageDraw.Draw(image).text((3-left,3-top),text,font=face,fill='#f5f4fb')
    return image.resize((round(image.width/scale*LABEL_WIDTH),round(image.height/scale)),Image.Resampling.LANCZOS)


@dataclass(frozen=True)
class Entry:
    label: str
    icon: str | Path
    action: Callable
    id: str | None = None


@dataclass
class Frame:
    image: Image.Image
    actions: list
    page: int


def slot_box(slot):
    tw, th = art.TILE_SIZE
    x, y = 46 + (slot % 3) * (tw + 20), 80 + (slot // 3) * (th + 20)
    return x, y, x + tw, y + th


def remove_button_box(right, top):
    center_x, center_y = right - 9, top + 9
    return center_x - 24, center_y - 24, center_x + 24, center_y + 24


@lru_cache(maxsize=128)
def tile_label(text):
    width = art.TILE_SIZE[0] - 20
    size = LABEL_SIZE
    while size > 18 and caption(text, size).width > width:
        size -= 1
    if caption(text, size).width > width:
        while text and caption(text + '…', size).width > width:
            text = text[:-1]
        text += '…'
    return caption(text, size)


@lru_cache(maxsize=128)
def tile_image(theme, text, icon_name, corner, active):
    width, height = art.TILE_SIZE
    tile = art.tile(theme).copy()
    icon = art.glyph(icon_name, 80)
    icon_x = (width - icon.width) // 2
    caption_y = height - 40
    mirror_y = 20 + 2 * icon.getbbox()[3] - icon.height + 3
    reflected = art.reflection(icon_name, icon.width, max(1, caption_y - 6 - mirror_y))
    label = tile_label(text)
    tile.alpha_composite(icon, (icon_x, 20))
    tile.alpha_composite(reflected, (icon_x, mirror_y))
    tile.alpha_composite(label, ((width - label.width) // 2, caption_y - 1))

    draw = ImageDraw.Draw(tile)
    if active:
        tint = art.blend(art.accent(theme), (245, 243, 255), .65)
        draw.rounded_rectangle((2, 2, width - 3, height - 3), radius=8, outline=tint, width=2)
        wash = Image.new('RGBA', tile.size)
        ImageDraw.Draw(wash).rounded_rectangle((2, 2, width - 3, height - 3), radius=8,
                                               fill=(255, 255, 255, 20))
        tile.alpha_composite(wash)
    if corner:
        # Leave room for the button to overhang the tile.
        padding = 12
        padded = Image.new('RGBA', (width + 2 * padding, height + 2 * padding))
        padded.alpha_composite(tile, (padding, padding))
        left, top, right, bottom = remove_button_box(width + padding, padding)
        x, y = (left + right) // 2, (top + bottom) // 2
        draw = ImageDraw.Draw(padded)
        draw.ellipse((x - 18, y - 18, x + 18, y + 18), fill='#27232b', outline='#e3d7e0', width=2)
        draw.line((x - 8, y, x + 8, y), fill='#f4eef2', width=3)
        tile = padded
    return tile


def render(layout, *, theme='Red', size=(720,480), page=0, clock=None,
           message='', dismiss=None, change_page=None, pressed=None, show_clock=False,
           editor=None, confirmation=None, slide=0.0, edit_empty=None, layout_theme=None):
    """Render from a canonical 720×480 layout and return matching touch regions.

    The ordinary three-plugin setup matches the approved five-tile mockup.
    """
    editing = editor is not None
    pages = len(layout)
    page = max(0, min(page, pages - 1))
    from .theme_menu import resolved_colors
    colors = resolved_colors(layout_theme, 'menu', theme) if layout_theme and layout_theme.colors else {}
    image=render_chrome(theme,clock=clock,show_clock=show_clock and not editing,colors=colors)
    d=ImageDraw.Draw(image)
    sx,sy=size[0]/720,size[1]/480
    def bounds(box):return tuple(round(v*(sx if i%2==0 else sy)) for i,v in enumerate(box))
    actions=[]
    tw,th=art.TILE_SIZE
    def draw_tile(entry, x, y, active=False, corner=False):
        if colors:
            edge = colors['accent'] if active else art.blend(colors['panel'], colors['text'], .15)
            d.rounded_rectangle((x, y, x+tw-1, y+th-1), radius=10, fill=colors['panel'], outline=edge)
            icon = art.glyph(entry.icon, 56)
            image.paste(icon, (x+(tw-icon.width)//2,y+22), icon)
            face = interface_font(20, 500)
            title = entry.label
            if d.textlength(title, font=face) > tw-26:
                while title and d.textlength(title+'…', font=face) > tw-26:
                    title = title[:-1]
                title += '…'
            d.text((x+tw//2, y+th-31), title, font=face, fill=colors['text'], anchor='mm')
            if corner:
                left, top, right, bottom = remove_button_box(x+tw, y)
                d.rounded_rectangle((left, top, right, bottom), radius=6,
                                    fill=colors['background'], outline=edge)
                d.text(((left+right)//2, (top+bottom)//2), '×', font=face, fill=colors['text'], anchor='mm')
            return
        shadow=art.tile_shadow(tw,th)
        image.paste(shadow,(x-8,y-5),shadow)
        tile = tile_image(theme, entry.label, entry.icon, corner, active)
        image.paste(tile, (x + (tw - tile.width) // 2, y + (th - tile.height) // 2), tile)
    gesture = editor.gesture if editing else None
    offset = round(slide * 720)
    neighbor = page + (-1 if offset > 0 else 1)
    visible_pages = [page]
    if offset and 0 <= neighbor < pages:
        visible_pages.append(neighbor)
    for visible_page in visible_pages:
        shift = offset + (visible_page - page) * 720
        for i, entry in enumerate(layout[visible_page]):
            left, y, right, bottom = slot_box(i)
            x = left + shift
            if entry is None or (gesture and gesture.plugin_id == entry.id):
                if editing:
                    d.rounded_rectangle((x, y, right + shift, bottom), radius=10, outline=colors.get('muted', '#857381'), width=2)
                continue
            actual = bounds((left, y, right, bottom))
            has_corner = editing and entry.id in editor.ui.manifests
            draw_tile(entry, x, y, active=not offset and pressed == actual, corner=has_corner)
            if not offset:
                if not editing:
                    actions.append((actual, entry.action))
                elif has_corner:
                    actions.append((bounds(remove_button_box(right, y)), lambda pid=entry.id: editor.confirm(pid)))
    if gesture and gesture.page < len(layout):
        dragged = layout[gesture.page][gesture.slot]
        if dragged is not None and dragged.id == gesture.plugin_id:
            target = editor.target_slot(gesture.point)
            if gesture.moved and target is not None:
                d.rounded_rectangle(slot_box(target), radius=10, outline=colors.get('accent', '#f0dbe5'), width=3)
            origin = slot_box(gesture.slot)
            x = round(min(720-tw, max(0, origin[0] + gesture.point[0] - gesture.start[0])))
            y = round(min(480-th, max(55, origin[1] + gesture.point[1] - gesture.start[1])))
            draw_tile(dragged, x, y, active=True)
    if pages > 7:
        d.text((360, 467), f'{page + 1} / {pages}', font=interface_font(16), fill='#f4edf2', anchor='mm')
        for label, box, delta in (('‹', (220, 456, 300, 480), -1), ('›', (420, 456, 500, 480), 1)):
            if 0 <= page + delta < pages:
                d.text(((box[0] + box[2]) // 2, 467), label, font=interface_font(22),
                       fill='#f4edf2', anchor='mm')
                if change_page is not None:
                    actions.append((bounds(box), lambda delta=delta: change_page(delta)))
    elif pages > 1:
        for index in range(pages):
            center = 360 + (2 * index - pages + 1) * 22
            color = '#f4edf2' if index == page else '#827982'
            d.rounded_rectangle((center - 13, 465, center + 13, 469), radius=2, fill=color)
            if change_page is not None:
                actions.append((bounds((center - 21, 458, center + 21, 480)),
                                lambda delta=index-page: change_page(delta)))
    if editing or (edit_empty and not offset and not any(layout[page])):
        from .controls import Page
        header = Page('', None, theme, size, pressed, layout_theme=layout_theme)
        header.image, header.draw = image, d
        if editing:
            if pages > 1:
                header.button((428, 6, 540, 46), 'Delete page', editor.confirm_delete_page, size=16, secondary=True)
            if editor.can_add_page(layout):
                header.button((552, 6, 624, 46), '+ Page', editor.add_page, size=16, secondary=True)
            header.button((634, 6, 704, 46), 'Done', editor.done, size=19)
        else:
            header.button((240, 204, 480, 268), 'Edit Home', edit_empty, size=22)
        actions += header.actions
    if confirmation is not None or (message and dismiss is not None):
        from .controls import Page
        from .projection import wrap_status

        dialog = Page('Notice', None, theme, size, pressed, layout_theme=layout_theme)
        dialog.image.paste(Image.blend(image, Image.new('RGB', image.size), .64), (0, 0))
        title, body, buttons = confirmation or ('Notice', message, [('OK', dismiss)])
        lines = wrap_status(str(body), dialog.draw, interface_font(22), 464)
        height = 132 + len(lines) * 28
        top = (480 - height) // 2
        dialog.panel((96, top, 624, top + height))
        dialog.label((124, top + 18), title, 25)
        for i, line in enumerate(lines):
            dialog.text((124, top + 60 + 28 * i), line, 22, fill='#f4f4f7')
        width = 148
        left = (720 - (len(buttons) * (width + 12) - 12)) // 2
        for label, action in buttons:
            dialog.button((left, top + height - 60, left + width, top + height - 14), label, action,
                          secondary=label in ('Cancel', 'No'))
            left += width + 12
        image, actions = dialog.image, dialog.actions
    if size!=(720,480):image=image.resize(size,Image.Resampling.LANCZOS)
    return Frame(image,actions,page)


def launcher_layout(launcher, presentation=None):
    from .home_edit import SETTINGS, display_pages

    entries=[Entry(m.name,'phone-projection' if m.id in ('carplay','android-auto') else m.icon or m.id,lambda pid=m.id:launcher.open_plugin(pid),m.id)
             for m in launcher.home_manifests()]
    # entries.append(Entry('Audio', 'audio', launcher.audio_page, AUDIO))
    entries.append(Entry('Settings', 'settings', launcher.settings, SETTINGS))
    by_id = {entry.id: entry for entry in entries}
    return [[by_id.get(pid) for pid in page] for page in display_pages(launcher, presentation)]


def draw_launcher(launcher):
    """Thin adapter; callbacks and enabled/default plugin policy remain core-owned."""
    editor = launcher.home_editor
    confirmation = editor.dialog()
    theme = launcher.layout_theme
    alternate = theme.layouts.get('home', 'tiles' if theme.colors else None)
    if alternate and not (editor.editing or confirmation or launcher.banner):
        from . import theme_menu

        layout = launcher_layout(launcher, alternate)
        frame = theme_menu.render(
            theme, alternate, 'Home', theme_menu.home_items(layout),
            size=(launcher.fb.w, launcher.fb.h), page=launcher.page,
            change_page=launcher.change_page, slide=launcher.home_slide,
            edit_empty=editor.begin_editing,
            pressed=launcher.pressed_box if launcher.press is not None else None,
            clock=datetime.now().strftime('%-I:%M') if launcher.prefs.data['show_clock'] else None,
            color=launcher.prefs.data['tile_color'],
        )
        launcher.page = frame.page
        theme_menu.present(launcher, frame)
        return
    layout = launcher_layout(launcher)
    frame=render(layout,theme=launcher.prefs.data['tile_color'],size=(launcher.fb.w,launcher.fb.h),
                 page=launcher.page,message=launcher.banner,dismiss=launcher.dismiss_home_notice,
                 change_page=launcher.change_page,
                 slide=launcher.home_slide,
                 edit_empty=editor.begin_editing,
                 editor=editor if editor.editing else None, confirmation=confirmation,
                 pressed=launcher.pressed_box if launcher.press is not None else None,show_clock=launcher.prefs.data['show_clock'],
                 layout_theme=theme)
    launcher.actions=frame.actions;launcher.page=frame.page
    launcher.home_clock=datetime.now().strftime('%Y-%m-%d %H:%M')
    # Preserve the existing RGB565 dithering path; home handles its own touch style.
    from sdk.hlauncher_sdk.theme import dither_rgb565
    launcher.fb.image(dither_rgb565(frame.image))
