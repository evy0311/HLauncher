"""BLE adapter selection using the shared Settings bars."""
from .controls import Page, present
from .scroll_list import Row,draw as draw_rows
from .projection import wrap_status
from sdk.hlauncher_sdk.fonts import font


def draw_launcher(launcher):
    state=launcher.obd.state
    launcher.obd_revision=launcher.obd.revision
    page=Page('OBD Gauges',getattr(launcher,'obd_return',launcher.home),launcher.prefs.data['tile_color'],
              (launcher.fb.w,launcher.fb.h),
              launcher.pressed_box if launcher.press is not None else None,detail='Bluetooth LE adapter',show_clock=launcher.prefs.data['show_clock'])
    message=state.get('message','No OBD dongle connected')
    lines=wrap_status(message,page.draw,font(17),672)
    for i,line in enumerate(lines[:2]):page.text((24,112+i*22),line,17,fill='#e0dfe8')
    page.button((24,168,352,212),'Scan',launcher.obd_scan)
    page.button((368,168,696,212),'Disconnect',launcher.obd_disconnect)
    devices=state.get('devices',[])
    draw_rows(launcher,page,[Row(row.get('name') or 'BLE device',
        lambda address=row['address']:launcher.obd_connect(address),value=row['address']) for row in devices],top=228,bottom=436)
    if not devices:page.text((24,240),'Scan nearby BLE devices, then select your dongle.',18)
    page.text((24,452),'Unavailable sensor readings show —',14)
    present(launcher,page)
