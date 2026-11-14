"""Live probes for the Civic's HondaLink integration."""
import time

def draw(ui, page, snapshot):
    tab = ui.integration_tab
    for index, title in enumerate(('Display', 'Buttons')):
        x = 24 + index * 344
        page.button((x,164,x+328,200), title, lambda title=title: ui.set_integration_tab(title),
                    selected=title == tab, size=17)
    if tab == 'Buttons':
        page.text((24,212), 'Press a steering wheel media button.', 16)
        events = snapshot['app_keys']
        if not events:
            page.text((24,252), 'Waiting for radio buttons', 18)
        for index, event in enumerate(events):
            age = max(0, int(time.monotonic() - event['monotonic']))
            details = f"{event['source']} · {event['action']}"
            page.text((24,243 + index * 24), f"{event['label']} · {details} · {age}s ago", 15)
    else:
        page.text((24,211), 'Show sends after 8 seconds so you can open the factory screen.', 15)
        page.button((24,240,352,284), 'Show HondaLink in 8s',
                    lambda: ui.test_hondalink_display('show'), size=18)
        page.button((368,240,696,284), 'Test Exit HondaLink',
                    lambda: ui.test_hondalink_display('exit'), size=18)
        for index, event in enumerate(snapshot['display_trials']):
            name = 'Show' if event['action'] == 'show' else 'Exit'
            text = f"{name} · {event['status']}"
            page.text((24,295 + index * 22), page.fit(text, 672, 15), 15)
        page.text((24,387), 'Check the actual screen and whether call or mic audio continues.', 14)
    page.button((24,416,240,456), 'Stop recording' if snapshot['recording'] else 'Start recording',
                ui.toggle_protocol_capture, size=17)
    page.button((252,416,456,456), 'Mark this test', lambda: ui.mark_integration_test(tab), size=17)
    page.text((24,462), page.fit(f"{snapshot['status']} · {snapshot['saved']} saved · {snapshot['dropped']} dropped",
                              672, 12), 12)
