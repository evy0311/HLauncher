"""Run the real HLauncher UI with desktop-only hardware substitutes."""
import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import tempfile
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit, parse_qs


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir',type=Path)
    parser.add_argument('--port',type=int,default=0)
    parser.add_argument('--ready-file',type=Path,help='Write the local URL for the native Mac shell')
    parser.add_argument('--self-test',action='store_true',help='Exercise real UI routes without a window')
    args=parser.parse_args()
    temporary=tempfile.TemporaryDirectory(prefix='hlauncher-simulator-') if args.self_test and args.state_dir is None else None
    folder=(args.state_dir or (Path(temporary.name) if temporary else Path.home()/'Library/Application Support/HLauncher Simulator')).resolve()
    folder.mkdir(parents=True,exist_ok=True)
    for name,child in (('STATE_DIR',''),('RUNTIME_DIR','runtime'),('LOG_DIR','logs')):
        path=folder/child;path.mkdir(exist_ok=True)
        os.environ['HLAUNCHER_'+name]=str(path)
    os.environ['HLAUNCHER_SERIAL']='Desktop Simulator'
    from .runtime import Simulator
    import signal
    def stop(*_):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop)
    simulator=Simulator(folder)
    try:
        if args.self_test:
            from .self_test import check
            print(json.dumps(check(simulator),indent=2));return
        token=secrets.token_urlsafe(32)
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def reply(self,code,data,kind='application/json'):
                if not isinstance(data,bytes):data=json.dumps(data,default=str).encode()
                self.send_response(code);self.send_header('Content-Type',kind)
                self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)))
                self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data)
            def authorized(self):
                return secrets.compare_digest(self.headers.get('X-Simulator-Token',''),token)
            def do_GET(self):
                url=urlsplit(self.path)
                if url.path=='/' and secrets.compare_digest(parse_qs(url.query).get('token',[''])[0],token):
                    html=Path(__file__).with_name('index.html').read_text().replace('__SIM_TOKEN__',token)
                    return self.reply(200,html.encode(),'text/html; charset=utf-8')
                if not self.authorized():return self.reply(403,dict(error='Simulator token required'))
                if url.path=='/api/view':
                    state=simulator.snapshot()
                    if str(state['revision'])!=parse_qs(url.query).get('after',[''])[0]:
                        state['frame']=base64.b64encode(simulator.display.png).decode()
                    return self.reply(200,state)
                if url.path=='/api/screenshot':return self.reply(200,simulator.display.png,'image/png')
                self.reply(404,dict(error='Unknown simulator endpoint'))
            def do_POST(self):
                if not self.authorized():return self.reply(403,dict(error='Simulator token required'))
                try:
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<size<=16384:raise ValueError('Invalid payload size')
                    data=json.loads(self.rfile.read(size))
                    if not isinstance(data,dict):raise ValueError('Expected JSON object')
                    if self.path=='/api/touch':simulator.touch(data['action'],data['x'],data['y'])
                    elif self.path=='/api/state':simulator.set_state(data)
                    elif self.path=='/api/update':simulator.set_update(data['phase'])
                    elif self.path=='/api/navigate':
                        routes={'home':'home','settings':'settings','projection':'projection_page','audio':'audio_page','updates':'updates_page',
                                'parking':'open_parking_status','system':'system_settings','setup':'setup_page','diagnostics':'system_diagnostics','power':'shutdown_page'}
                        getattr(simulator.ui,routes[data['page']])()
                    elif self.path=='/api/button':
                        from sdk.hlauncher_sdk.buttons import BUTTONS
                        if data['button'] not in BUTTONS:raise ValueError('Unknown radio button')
                        simulator.ui.inputs.offer(data['button'],'down','hondalink-iap')
                        simulator.ui.inputs.offer(data['button'],'up','hondalink-iap')
                        simulator.event(state='simulated_radio_button',button=data['button'])
                    else:return self.reply(404,dict(error='Unknown simulator endpoint'))
                    simulator.tick();self.reply(200,simulator.snapshot())
                except (ValueError,KeyError,TypeError) as exc:self.reply(400,dict(error=str(exc)))
                except Exception as exc:
                    simulator.event(state='simulator_ui_error',error=repr(exc));self.reply(500,dict(error=repr(exc)))
        server=HTTPServer(('127.0.0.1',args.port),Handler);server.timeout=.03
        url=f'http://127.0.0.1:{server.server_port}/?token={token}'
        if args.ready_file:args.ready_file.write_text(url)
        print('HLauncher Simulator: '+url,flush=True)
        print('State: '+str(folder),flush=True)
        try:
            while True:
                server.handle_request()
                try:simulator.tick()
                except Exception as exc:
                    simulator.event(state='simulator_tick_error',error=repr(exc));time.sleep(.1)
        except KeyboardInterrupt:pass
        finally:server.server_close()
    finally:
        simulator.close()
        if temporary:temporary.cleanup()


if __name__=='__main__':main()
