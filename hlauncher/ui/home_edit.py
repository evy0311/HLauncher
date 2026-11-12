"""Home layout, long press, and drag gestures."""
from dataclasses import dataclass
import time

from .home import remove_button_box, slot_box

SLOTS = 6
MAX_PAGES = 3
HOLD_SECONDS = .55
EDGE_SECONDS = .55
AUDIO = '@audio'
SETTINGS = '@settings'
UTILITIES = (
    # AUDIO,
    SETTINGS,
)


def layout(plugin_ids, saved):
    plugin_ids = list(plugin_ids)
    ordered = plugin_ids + list(UTILITIES)
    remaining = dict.fromkeys(ordered)
    pages = []
    for page in saved:
        slots = []
        for plugin_id in page:
            slots.append(plugin_id if plugin_id in remaining else None)
            remaining.pop(plugin_id, None)
        pages.append(slots)
    if not pages:
        pages.append([None] * SLOTS)
    for page in pages:
        for slot, plugin_id in enumerate(page):
            if plugin_id is None and remaining:
                first = next(iter(remaining))
                page[slot] = first
                del remaining[first]
    pending = list(remaining)
    for start in range(0, len(pending), SLOTS):
        page = pending[start:start + SLOTS]
        pages.append(page + [None] * (SLOTS - len(page)))
    return pages


@dataclass
class Gesture:
    page: int
    slot: int
    plugin_id: str
    start: tuple
    point: tuple
    since: float
    edge: int = 0
    edge_since: float = 0
    moved: bool = False


class Editor:
    def __init__(self, ui):
        self.ui = ui
        self.reset()

    def reset(self):
        self.editing = False
        self.gesture = None
        self.confirmation = None

    def pages(self, entries):
        return layout(entries, self.ui.prefs.data['home_pages'])

    def save(self, pages):
        try:
            self.ui.prefs.set_home_pages(pages)
            return True
        except OSError as exc:
            self.ui.event(state='settings_save_failed', error=str(exc))
            self.ui.banner = 'Could not save the Home layout.'
            return False

    def add_page(self):
        pages = self.ui.home_pages()
        if len(pages) < MAX_PAGES and self.save(pages + [[None] * SLOTS]):
            self.ui.page = len(pages)
        self.ui.draw()

    def done(self):
        self.reset()
        self.ui.draw()

    def confirm(self, plugin_id):
        self.confirmation = plugin_id
        self.ui.draw()

    def dialog(self):
        ui = self.ui
        if ui.banner:
            self.confirmation = None
            return None
        if self.editing and ui.plugin_manager and ui.plugin_manager.job:
            return 'Plugin settings', 'Saving plugin settings…', []
        plugin_id = self.confirmation
        manifest = ui.manifests.get(plugin_id)
        if manifest is None or not ui.prefs.enabled(manifest):
            self.confirmation = None
            return None
        disable = lambda: self.plugin_action(plugin_id, 'disable')
        cancel = lambda: self.confirm(None)
        if manifest.bundled:
            return 'Disable plugin?', f'Disable {manifest.name}?', [('Yes', disable), ('No', cancel)]
        return ('Manage plugin', f'Disable or uninstall {manifest.name}?',
                [('Disable', disable), ('Uninstall', lambda: self.plugin_action(plugin_id, 'remove')),
                 ('Cancel', cancel)])

    def plugin_action(self, plugin_id, operation):
        ui = self.ui
        self.confirmation = None
        manifest = ui.manifests.get(plugin_id)
        if manifest is None or not ui.prefs.enabled(manifest):
            ui.draw()
            return
        if manifest.bundled:
            ui.toggle_plugin(plugin_id)
        elif ui.plugin_manager:
            def done(_result):
                ui.refresh_plugins()
                ui.draw()

            ui.plugin_manager.start('Saving plugin settings…',
                                    lambda: ui.plugin_store.change(plugin_id, operation),
                                    done)
        else:
            ui.draw()

    def touch(self, action, point):
        ui = self.ui
        if ui.mode != 'home' or ui.banner or self.confirmation or (ui.plugin_manager and ui.plugin_manager.job):
            self.gesture = None
            return False
        if point is not None:
            point = (point[0] * 720 / ui.fb.w, point[1] * 480 / ui.fb.h)
        if action == 'down':
            self.gesture = None
            if point is None:
                return False
            for slot, plugin_id in enumerate(ui.home_pages()[ui.page]):
                if not plugin_id:
                    continue
                x, y, right, bottom = slot_box(slot)
                if self.editing and plugin_id in ui.manifests:
                    left, top, button_right, button_bottom = remove_button_box(right, y)
                    if left <= point[0] <= button_right and top <= point[1] <= button_bottom:
                        return False
                if x <= point[0] < right and y <= point[1] < bottom:
                    self.gesture = Gesture(ui.page, slot, plugin_id, point, point, time.monotonic())
                    if self.editing:
                        ui.home_swipe = None
                        ui.draw()
                    return self.editing
        elif gesture := self.gesture:
            if action == 'move' and point is not None:
                gesture.point = point
                gesture.moved |= max(abs(a - b) for a, b in zip(point, gesture.start)) >= 12
                if not self.editing and gesture.moved:
                    self.gesture = None
                elif self.editing:
                    self.update_edge(gesture, time.monotonic())
                    ui.draw()
                    return True
            elif action in ('up', 'unused'):
                self.gesture = None
                if self.editing:
                    self.drop(gesture)
                    return True
        return False

    def update_edge(self, gesture, now):
        x, y = gesture.point
        direction = (-1 if x < 32 else 1 if x >= 688 else 0) if y >= 60 else 0
        if direction != gesture.edge:
            gesture.edge, gesture.edge_since = direction, now
        if direction and now - gesture.edge_since >= EDGE_SECONDS:
            target = self.ui.page + direction
            if 0 <= target < len(self.ui.home_pages()):
                self.ui.page = target
                gesture.edge_since = float('inf')  # Cross one page per visit to the edge.

    def drop(self, gesture):
        ui = self.ui
        pages = ui.home_pages()
        source = pages[gesture.page] if gesture.page < len(pages) else None
        slot = self.target_slot(gesture.point)
        if (source is not None and source[gesture.slot] == gesture.plugin_id
                and (gesture.moved or gesture.page != ui.page) and slot is not None):
            target = pages[ui.page]
            target[slot], source[gesture.slot] = gesture.plugin_id, target[slot]
            self.save(pages)
        ui.draw()

    @staticmethod
    def target_slot(point):
        x, y = point
        if not (38 <= x < 682 and 72 <= y < 460):
            return None

        def distance(slot):
            left, top, right, bottom = slot_box(slot)
            return (x - (left + right) / 2) ** 2 + (y - (top + bottom) / 2) ** 2

        return min(range(SLOTS), key=distance)

    def tick(self, now):
        ui = self.ui
        if ui.mode != 'home' or ui.banner or self.confirmation or (ui.plugin_manager and ui.plugin_manager.job):
            return
        if self.gesture and not self.editing and now - self.gesture.since >= HOLD_SECONDS:
            self.editing = True
            ui.press = ui.pressed_box = ui.home_swipe = None
            ui.draw()
        elif self.editing and self.gesture:
            page = ui.page
            self.update_edge(self.gesture, now)
            if ui.page != page:
                ui.draw()
