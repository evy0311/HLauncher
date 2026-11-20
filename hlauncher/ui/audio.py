"""Touch-sized EQ controls within the current radio theme."""
from ..audio_settings import BANDS, EQ_BANDS, EQ_GAIN_LIMIT, PRESETS
from .controls import Page, present
from .chrome import scale_bounds


PRESET_DETAILS = {
    'Flat': 'Reset all bands and previous tone gains to 0 dB',
    'Bass lift': 'A little more low bass, a little less upper bass',
    'Vocal clarity': 'Gentle presence boost with less low-mid weight',
    'Softer treble': 'Reduce the upper frequencies for a gentler balance',
}


def draw_launcher(launcher):
    settings = launcher.audio_settings
    values = settings.values

    def view(*, bank=None, presets=False):
        if bank is not None:
            launcher.audio_bank = bank
        launcher.audio_presets_open = presets
        launcher.press = None
        launcher.draw()

    presets = getattr(launcher, 'audio_presets_open', False)
    page = Page.for_launcher(
        launcher, 'Audio presets' if presets else 'Audio & EQ',
        (lambda: view()) if presets else getattr(launcher, 'audio_return', launcher.home),
        detail=settings.preset_name())

    if presets:
        def apply(name):
            launcher.audio_presets_open = False
            launcher.change_audio(**settings.preset_changes(name))

        for i, name in enumerate(PRESETS):
            y = 112 + i * 76
            page.button((24, y, 696, y + 44), name, lambda name=name: apply(name),
                        settings.preset_name() == name, size=22)
            page.text((40, y + 50), PRESET_DETAILS[name], 16)
        page.text((24, 424), 'Presets keep PipeWire on or off as selected', 16)
        page.notice('Boosting bands can clip loud recordings', y=452)
        present(launcher, page)
        return

    active = values['pipewire'] and values['eq']
    legacy_bypass = values['pipewire'] and not values['eq']
    controls = (
        ('PipeWire bypassed' if legacy_bypass else 'PipeWire ' + ('On' if active else 'Off'),
         lambda: launcher.change_audio(pipewire=not active, eq=True), active),
        ('Presets / Reset', lambda: view(presets=True), False),
    )
    for i, (title, action, selected) in enumerate(controls):
        x = 24 + i * 344
        page.button((x, 112, x + 328, 156), title, action, selected, size=21)

    if not values['pipewire']:
        status = 'Direct HDMI · EQ is not applied; band changes are saved'
    elif not values['eq']:
        status = 'Previous EQ bypass · Tap PipeWire to apply your saved curve'
    elif any(values[key] for key in BANDS):
        status = 'PipeWire selected · EQ enabled, including previous tone gains'
    else:
        status = 'Tap a band to select it, then adjust below'
    error = launcher.audio_notice and launcher.audio_notice != 'Saved'
    page.text((24, 172), page.fit(launcher.audio_notice if error else status, 672, 16),
              16, fill='#efbd82' if error else '#c2c0cc')

    bank = min(1, max(0, getattr(launcher, 'audio_bank', 0)))
    bands = list(EQ_BANDS.items())[bank * 6:bank * 6 + 6]
    selections = getattr(launcher, 'audio_selected_bands', {0: 'b50', 1: 'b1k'})
    selected_key = selections.get(bank)
    if selected_key not in dict(bands):
        selected_key = bands[0][0]

    def select_band(key):
        launcher.audio_selected_bands = dict(selections)
        launcher.audio_selected_bands[bank] = key
        launcher.press = None
        launcher.draw()

    limit = 12 if any(abs(values['bands'][key]) > EQ_GAIN_LIMIT for key, _ in bands) else EQ_GAIN_LIMIT
    ink = page.colors.get('text', '#f4f4f7')
    muted = page.colors.get('muted', '#a7a4ae')
    top, bottom = 232, 360
    zero = (top + bottom) // 2
    for gain in (limit, 0, -limit):
        y = zero - gain / limit * (bottom - top) / 2
        page.text((24, y), f'{gain:+d}' if gain else '0', 14, anchor='lm')
        page.draw.line((60, y, 688, y), fill=page.edge, width=1)
    for i, (key, frequency) in enumerate(bands):
        cx = 80 + i * 112
        gain = values['bands'][key]
        selected = key == selected_key
        label = f'{frequency / 1000:g} kHz' if frequency >= 1000 else f'{frequency:g} Hz'
        page.text((cx, 200), label, 18, fill=page.accent if selected else '#c2c0cc', anchor='mt')
        if selected:
            page.draw.line((cx - 28, 224, cx + 28, 224), fill=page.accent, width=2)
        point = zero - gain / limit * (bottom - top) / 2
        page.draw.line((cx, top, cx, bottom), fill=page.edge, width=3)
        page.draw.line((cx, zero, cx, point), fill=page.accent if selected else muted, width=3)
        page.draw.rounded_rectangle((cx - 16, point - 4, cx + 16, point + 4),
                                    radius=2, fill=page.accent if selected else ink)
        page.actions.append((scale_bounds((cx - 48, 192, cx + 48, 376), page.size),
                             lambda key=key: select_band(key)))

    frequency = EQ_BANDS[selected_key]
    label = f'{frequency / 1000:g} kHz' if frequency >= 1000 else f'{frequency:g} Hz'
    gain = values['bands'][selected_key]
    gain_label = f'{gain:+d} dB' if gain else '0 dB'
    page.button((24, 384, 144, 428), '−',
                lambda: launcher.adjust_eq(selected_key, -1), size=30, secondary=True)
    page.text((360, 406), f'{label}  ·  {gain_label}', 26, fill='#f4f4f7', anchor='mm')
    page.button((576, 384, 696, 428), '+',
                lambda: launcher.adjust_eq(selected_key, 1), size=30, secondary=True)

    page.button((24, 436, 352, 476), 'Low · 31.5–315 Hz', lambda: view(bank=0),
                bank == 0, size=19, secondary=bank != 0)
    page.button((368, 436, 696, 476), 'High · 500 Hz–16 kHz', lambda: view(bank=1),
                bank == 1, size=19, secondary=bank != 1)
    present(launcher, page)
