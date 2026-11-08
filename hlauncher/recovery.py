"""Password-protected local setup/recovery site and serialized maintenance jobs."""
import base64
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlsplit
from .config import STATE_DIR, Preferences
from .setup_state import SetupState, atomic_json, address
from .storage import configure, execute, status as storage_status


def request_job(operation, **values):
    if operation not in ('protect','unprotect','pair','hotspot','wifi','reboot'):
        raise ValueError('Unknown setup operation')
    # No shell commands are accepted. The daemon owns one fixed request queue.
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = STATE_DIR/'maintenance-request.json'
    fd = os.open(path, os.O_CREAT|os.O_EXCL|os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd,'w') as output:
            json.dump(dict(operation=operation, id=time.time_ns(), **values),output)
            output.flush(); os.fsync(output.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def job_status(folder=STATE_DIR):
    try: return json.loads((Path(folder)/'maintenance-status.json').read_text())
    except (OSError, ValueError): return {'status': 'Ready'}


def connection_status():
    try:
        item=json.loads(Path('/run/hlauncher/connection.json').read_text())
        if time.monotonic()-item.get('monotonic',0)>5:return {'status':'Waiting for connection service'}
        return item
    except (OSError,ValueError,TypeError):return {'status':'Waiting for connection service'}


class Maintenance:
    def __init__(self, state=None, run=execute):
        self.state = state or SetupState(); self.run = run
        self.lock = threading.Lock(); self.ap = False

    def perform(self, item):
        op = item.get('operation')
        if op == 'protect': return configure(True, self.run)
        if op == 'unprotect': return configure(False, self.run)
        if op == 'pair':
            old = self.state.peer
            if old:
                self.run(['bluetoothctl','remove', old], timeout=10)
            self.state.forget()
            self.run(['systemctl','restart','hlauncher.service'], timeout=15)
            return 'Pairing open for five minutes'
        if op == 'hotspot':
            self.hotspot(); return 'Recovery Wi-Fi enabled'
        if op == 'reboot':
            self.run(['systemctl','reboot','--no-block'], timeout=5)
            return 'Restarting'
        if op == 'wifi':
            ssid, password, country = item.get('ssid'), item.get('password'), item.get('country')
            if not isinstance(ssid,str) or not 1 <= len(ssid.encode()) <= 32 or any(ord(c)<32 or ord(c)==127 for c in ssid):
                raise ValueError('Enter a valid Wi-Fi name')
            if not isinstance(password,str) or not 8 <= len(password) <= 63 or any(ord(c)<32 or ord(c)==127 for c in password):
                raise ValueError('Use an 8–63 character Wi-Fi password')
            if not isinstance(country,str) or not re.fullmatch('[A-Z]{2}', country):
                raise ValueError('Choose a two-letter Wi-Fi country')
            # Password goes to an NM keyfile, never process arguments or logs.
            import configparser
            import uuid
            connection = configparser.ConfigParser(interpolation=None)
            connection.read_dict({'connection': {'id':'HLauncher Wi-Fi','uuid':str(uuid.uuid4()),'type':'wifi'},
                'wifi': {'mode':'infrastructure','ssid':ssid},
                'wifi-security': {'key-mgmt':'wpa-psk','psk':password},
                'ipv4': {'method':'auto'}, 'ipv6': {'method':'auto'}})
            path = Path('/etc/NetworkManager/system-connections/hlauncher-wifi.nmconnection')
            self.run(['raspi-config','nonint','do_wifi_country',country], timeout=15)
            fd, name = tempfile.mkstemp(prefix='.hlauncher-', dir=path.parent)
            try:
                with os.fdopen(fd,'w') as f:
                    connection.write(f, space_around_delimiters=False); f.flush(); os.fsync(f.fileno())
                os.replace(name,path)
            finally:
                if os.path.exists(name): os.unlink(name)
            self.run(['nmcli','connection','load',str(path)],timeout=10)
            self.run(['nmcli','--wait','20','connection','up','HLauncher Wi-Fi'],timeout=25)
            self.ap = False
            return 'Wi-Fi connected; reconnect your phone to your normal network'
        raise ValueError('Unknown setup operation')

    def hotspot(self):
        creds = self.state.credentials()
        # Image prep / Imager must set country first; never guess a regulatory domain.
        domain = self.run(['iw','reg','get'],timeout=5).stdout
        if not re.search(r'country (?!00:)[A-Z]{2}:', domain):
            raise ValueError('Set Wi-Fi country in Raspberry Pi Imager or connect Ethernet for setup')
        rc = self.run(['nmcli','-t','-f','NAME','connection','show'],timeout=5).stdout.splitlines()
        if 'HLauncher Recovery' not in rc:
            self.run(['nmcli','connection','add','type','wifi','ifname','wlan0','con-name','HLauncher Recovery',
                      'ssid',creds['ssid'],'802-11-wireless.mode','ap','ipv4.method','shared',
                      'ipv4.addresses','192.168.4.1/24','ipv6.method','disabled',
                      'wifi-sec.key-mgmt','wpa-psk','wifi-sec.psk',creds['password'],
                      'connection.autoconnect','no'],timeout=10)
        self.run(['nmcli','--wait','15','connection','up','HLauncher Recovery'],timeout=20)
        self.ap = True

    def process(self, item):
        if not self.lock.acquire(blocking=False): return False
        try:
            atomic_json(self.state.folder/'maintenance-status.json', {'status':'Working','operation':item.get('operation')})
            try:
                result = self.perform(item)
                atomic_json(self.state.folder/'maintenance-status.json', {'status':'Done','message':result})
            except Exception as exc:
                # Subprocess stderr can contain connection details. Keep errors generic.
                message = str(exc) if isinstance(exc,ValueError) else 'System operation failed; enable debug for diagnosis'
                atomic_json(self.state.folder/'maintenance-status.json', {'status':'Failed','message':message})
                print(json.dumps(dict(state='maintenance_failed',operation=op if (op:=item.get('operation')) else 'unknown',
                                      error=type(exc).__name__)),flush=True)
            return True
        finally: self.lock.release()


PAGE = '''<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>HLauncher setup</title>
<style>body{font:17px system-ui;background:#111820;color:#eee;max-width:560px;margin:40px auto;padding:20px}input,button{font:inherit;padding:12px;margin:6px 0;box-sizing:border-box;width:100%;border-radius:6px}button{background:#275d78;color:white;border:0}small{color:#abb9c6}</style>
<h1>HLauncher</h1><p>Pair from HandsFreeLink: add a phone, select HLauncher, then confirm on the radio.</p><pre id="state">Loading…</pre>
<button onclick="act('pair')">Forget saved radio and open pairing</button>
<p>If your radio wasn't recognized, enter its Bluetooth address, then retry pairing from the radio.</p><input id="peer" placeholder="AA:BB:CC:DD:EE:FF"><button onclick="manual()">Allow this radio for five minutes</button>
<h2>Home Wi-Fi</h2><small>This switches the Pi away from its setup hotspot. Reconnect your phone afterward. Optional.</small>
<input id="ssid" placeholder="Wi-Fi name" autocomplete="off"><input id="password" type="password" placeholder="Wi-Fi password" autocomplete="new-password"><input id="country" placeholder="Country code, e.g. US" maxlength="2"><button onclick="wifi()">Connect Wi-Fi</button>
<h2>Support</h2><button id="capture" hidden onclick="location.href='/debug-capture'">Download latest debug capture</button><button onclick="debug()">Toggle debug mode</button><button onclick="location.href='/report'">Download diagnostic summary</button>
<script>
async function post(path,data){let r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});let v=await r.json();if(!r.ok)alert(v.error||'Request failed');refresh()}
function act(operation){if(operation==='pair'&&!confirm('Forget the saved radio and restart pairing?'))return;post('/api/job',{operation})}
function manual(){post('/api/manual',{address:document.getElementById('peer').value})}
function wifi(){post('/api/job',{operation:'wifi',ssid:document.getElementById('ssid').value,password:document.getElementById('password').value,country:document.getElementById('country').value.toUpperCase()});document.getElementById('password').value=''}
function debug(){post('/api/debug',{})}
async function refresh(){try{let r=await fetch('/api/status');let data=await r.json();document.getElementById('state').textContent=JSON.stringify(data,null,2);document.getElementById('capture').hidden=!data.debug}catch{}}
refresh();setInterval(refresh,3000)
</script>'''


def handler_for(state, maintenance):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup(); self.connection.settimeout(10)
        def log_message(self, *args): pass
        def send(self, code, data, kind='application/json'):
            raw = data.encode() if isinstance(data,str) else json.dumps(data).encode()
            self.send_response(code); self.send_header('Content-Type',kind)
            self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
        def authorized(self):
            expected = 'Basic '+base64.b64encode(('hlauncher:'+state.credentials()['password']).encode()).decode()
            if hmac.compare_digest(self.headers.get('Authorization','').encode(), expected.encode()): return True
            self.send_response(401); self.send_header('WWW-Authenticate','Basic realm="HLauncher setup"')
            self.send_header('Content-Length','0'); self.end_headers(); return False
        def do_GET(self):
            if not self.authorized(): return
            if self.path == '/': return self.send(200,PAGE,'text/html; charset=utf-8')
            if self.path == '/api/status':
                return self.send(200,dict(radio=state.peer or 'Waiting for pairing',
                    setup_complete=Preferences().data['setup_complete'], debug=Preferences().data['debug_mode'],
                    maintenance=job_status(),storage=storage_status(),connection=connection_status()))
            if self.path == '/debug-capture':
                if not Preferences().data['debug_mode']:return self.send(403,{'error':'Enable debug mode first'})
                files=sorted((state.folder/'protocol-captures').glob('protocol-*.jsonl'))
                if not files:return self.send(404,{'error':'No capture recorded yet'})
                with files[-1].open('rb') as source:raw=source.read(8*1024*1024)
                self.send_response(200);self.send_header('Content-Type','application/x-ndjson')
                self.send_header('Content-Disposition','attachment; filename="'+files[-1].name+'"')
                self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)))
                self.end_headers();self.wfile.write(raw);return
            if self.path == '/report':
                # Production summary contains no raw packets, phone data or network passwords.
                return self.send(200,dict(maintenance=job_status(),storage=storage_status(),
                    debug=Preferences().data['debug_mode'],radio_verified=bool(state.peer)))
            self.send(404,{'error':'Not found'})
        def do_POST(self):
            if not self.authorized(): return
            origin = self.headers.get('Origin')
            if origin and urlsplit(origin).netloc != self.headers.get('Host'):
                return self.send(403,{'error':'Origin rejected'})
            if self.headers.get('Content-Type','').split(';')[0] != 'application/json':
                return self.send(415,{'error':'JSON required'})
            try:
                size = int(self.headers.get('Content-Length','0'))
                if not 0 < size <= 4096: raise ValueError('Invalid request size')
                data = json.loads(self.rfile.read(size))
                if not isinstance(data,dict): raise ValueError('Invalid request')
                if self.path == '/api/debug':
                    prefs = Preferences(); prefs.data['debug_mode'] = not prefs.data['debug_mode']; prefs.save()
                elif self.path == '/api/manual':
                    peer = address(data.get('address',''))
                    if state.peer: raise ValueError('Forget the saved radio first')
                    state.open_pairing()
                    atomic_json(state.folder/'manual-peer.json',{'address':peer,'expires':time.time()+300})
                elif self.path == '/api/job':
                    if data.get('operation') not in ('pair','wifi'): raise ValueError('Operation unavailable here')
                    if maintenance.lock.locked(): raise ValueError('An operation is already running')
                    request_job(**data)
                else: return self.send(404,{'error':'Not found'})
                self.send(202,{'status':'Requested'})
            except (ValueError,TypeError,OSError): self.send(400,{'error':'Invalid setup request'})
    return Handler


class RecoveryServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, *args):
        self.slots=threading.BoundedSemaphore(16)
        super().__init__(*args)
    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:super().process_request(request,client_address)
        except BaseException:
            self.slots.release()
            raise
    def process_request_thread(self, request, client_address):
        try:super().process_request_thread(request,client_address)
        finally:self.slots.release()


def main():
    state = SetupState(); state.credentials(); maintenance = Maintenance(state)
    def worker():
        seen = None; hotspot_attempted = False
        while True:
            path = STATE_DIR/'maintenance-request.json'
            try:
                item = json.loads(path.read_text())
                if item.get('id') != seen and not maintenance.lock.locked():
                    seen = item.get('id'); path.unlink(missing_ok=True); maintenance.process(item)
            except (OSError,ValueError,TypeError): pass
            if not hotspot_attempted and not state.peer:
                hotspot_attempted = True
                try:
                    connected = maintenance.run(['nmcli','-g','GENERAL.STATE','device','show','wlan0'],timeout=5).stdout.startswith('100')
                except (OSError,subprocess.SubprocessError): connected = False
                if not connected: maintenance.process({'operation':'hotspot'})
            if maintenance.ap and Preferences().data['setup_complete'] and state.peer:
                try: maintenance.run(['nmcli','connection','down','HLauncher Recovery'],timeout=10)
                except subprocess.SubprocessError: pass
                maintenance.ap = False
            time.sleep(2)
    threading.Thread(target=worker,daemon=True).start()
    server = RecoveryServer(('0.0.0.0',8080),handler_for(state,maintenance))
    server.timeout = 5
    server.serve_forever()


if __name__ == '__main__': main()
