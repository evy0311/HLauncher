"""Live gauges. Bluetooth transport stays in the launcher-owned OBD service."""
import time
from hlauncher_sdk import Client
from hlauncher_sdk.theme import load_accent
from gauges import Dashboard, encode
from hlauncher_sdk.obd import snapshot


def main():
    client=Client();dashboard=Dashboard(client.width,client.height)
    active=False;pressed=False;last_xy=None;last_render=0;heartbeat=0;frames=0;vehicle=None;data=None
    try:
        while True:
            while message:=client.receive(0):
                kind=message['type']
                if kind=='host.activate':
                    if dashboard.accent != load_accent():dashboard=Dashboard(client.width,client.height)
                    active=True;last_render=0
                    client.status('OBD gauges',video_available=True)
                elif kind in ('host.deactivate','host.stop'):
                    return
                elif kind=='vehicle.gauges':
                    vehicle=message.get('snapshot')
                elif kind=='touch.cancel':
                    pressed=False;dashboard.touch('cancel',None)
                elif kind=='touch' and active:
                    contacts=message.get('contacts',[])
                    contact=contacts[0] if contacts else {'action':'unused'}
                    if contact.get('x_px') is not None:
                        last_xy=(contact['x_px'],contact['y_px'])
                    action=contact.get('action')
                    result=dashboard.touch(action,last_xy)
                    last_render=0
                    if result=='home':client.home();active=False
            now=time.monotonic()
            if active and now-last_render>=1/30:
                if client.free:
                    data=snapshot(vehicle=vehicle,allow_ble=False)
                    if client.present(encode(dashboard.render(data['values'],pressed,connected=data['connected'],
                        sources=data['sources'],ages=data['ages'],intervals=data['intervals']))):frames+=1
                last_render=now
            if now-heartbeat>=2:
                client.send(type='health',metrics={'live_data_only':True,'frames':frames,'target_fps':30,
                    'gauge_values':data['values'] if data else [],'gauge_sources':data['sources'] if data else []})
                heartbeat=now
            time.sleep(.003 if active else .02)
    except (EOFError,BrokenPipeError,ConnectionResetError):
        pass
    finally:client.close()


if __name__=='__main__':main()
