"""BLE adapter selection using the shared Settings bars."""
import math
from .controls import Page, present
from .projection import wrap_status
from sdk.hlauncher_sdk.fonts import font


def draw_launcher(launcher):
    state=launcher.obd.state
    launcher.obd_revision=launcher.obd.revision
    page=Page('OBD Gauges',launcher.home,launcher.prefs.data['tile_color'],
              (launcher.fb.w,launcher.fb.h),
              launcher.pressed_box if launcher.press is not None else None,detail='Bluetooth LE adapter')
    message=state.get('message','No OBD dongle connected')
    lines=wrap_status(message,page.draw,font(17),672)
    for i,line in enumerate(lines[:2]):page.text((24,112+i*22),line,17,fill='#e0dfe8')
    page.button((24,168,352,212),'Scan',launcher.obd_scan)
    page.button((368,168,696,212),'Disconnect',launcher.obd_disconnect)
    devices=state.get('devices',[])
    pages=max(1,math.ceil(len(devices)/3))
    launcher.obd_page=min(launcher.obd_page,pages-1)
    for i,row in enumerate(devices[launcher.obd_page*3:launcher.obd_page*3+3]):
        address=row['address']
        page.row(228+i*52,row.get('name') or 'BLE device',address,
                 lambda address=address:launcher.obd_connect(address))
    if not devices:
        page.text((24,240),'Scan nearby BLE devices, then select your dongle.',18)
    if pages>1:
        page.text((24,412),f'Page {launcher.obd_page+1} of {pages}',16)
        page.button((480,396,584,436),'Prev',lambda:launcher.obd_devices_page(-1),size=18)
        page.button((592,396,696,436),'Next',lambda:launcher.obd_devices_page(1),size=18)
    page.text((24,452),'BLE ELM327 · unsupported sensors show —',14)
    present(launcher,page)
