"""Live gauges. Bluetooth transport stays in the launcher-owned OBD service."""
import time
from hlauncher_sdk import Client
from hlauncher_sdk.theme import load_accent
from gauges import Dashboard, encode
from hlauncher_sdk.obd import snapshot


def main():
    client=Client();dashboard=Dashboard(client.width,client.height)
    active=False;pressed=False;last_xy=None;last_render=0;heartbeat=0;frames=0
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
                elif kind=='touch.cancel':
                    pressed=False
                elif kind=='touch' and active:
                    contacts=message.get('contacts',[])
                    contact=contacts[0] if contacts else {'action':'unused'}
                    if contact.get('x_px') is not None:
                        last_xy=(contact['x_px'],contact['y_px'])
                    action=contact.get('action')
                    box=dashboard.home_box
                    inside=last_xy is not None and box[0]<=last_xy[0]<=box[2] and box[1]<=last_xy[1]<=box[3]
                    if action=='down':pressed=inside;last_render=0
                    elif action=='move' and not inside:pressed=False;last_render=0
                    elif action in ('up','unused'):
                        go_home=pressed;pressed=False;last_render=0
                        if go_home:
                            client.home();active=False
            now=time.monotonic()
            if active and now-last_render>=1/20:
                if client.free:
                    if client.present(encode(dashboard.render((data:=snapshot())['values'],pressed,connected=data['connected']))):frames+=1
                last_render=now
            if now-heartbeat>=2:
                client.send(type='health',metrics={'live_data_only':True,'frames':frames,'target_fps':20})
                heartbeat=now
            time.sleep(.003 if active else .02)
    except (EOFError,BrokenPipeError,ConnectionResetError):
        pass
    finally:client.close()


if __name__=='__main__':main()
