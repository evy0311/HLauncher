"""Local network setup/recovery site and serialized maintenance jobs."""
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
from .ssh_access import status as ssh_status

UPDATER_CONFIG=Path('/etc/hlauncher-updater/config.json')


def request_job(operation, **values):
    if operation not in ('protect','unprotect','pair','hotspot','wifi','reboot','ssh'):
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


def network_status(folder=STATE_DIR):
    try:
        item=json.loads((Path(folder)/'network-status.json').read_text())
        if 0<=time.monotonic()-item.get('monotonic',0)<10:return item
    except (OSError,ValueError,TypeError):pass
    return {}


def sample_network(run=execute):
    import ipaddress
    result={'monotonic':time.monotonic()}
    # A LAN address is more useful than the temporary setup hotspot address.
    for device in ('wlan0','eth0'):
        try:text=run(['nmcli','-g','IP4.ADDRESS','device','show',device],timeout=3).stdout
        except (OSError,subprocess.SubprocessError):continue
        for line in text.splitlines():
            try:address=str(ipaddress.IPv4Interface(line.strip()).ip)
            except ValueError:continue
            if not address.startswith('127.'):
                result.update(address=address,device=device)
                if address!='192.168.4.1':return result
    return result


class Maintenance:
    def __init__(self, state=None, run=execute, portal=None):
        self.state = state or SetupState(); self.run = run; self.portal = portal
        self.lock = threading.Lock(); self.ap = False; self.ap_automatic = False

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
            self.hotspot()
            self.ap_automatic = item.get('automatic') is True
            return 'Setup hotspot is ready'
        if op == 'ssh':
            from .ssh_access import apply
            enabled=item.get('enabled')
            apply(enabled,self.state.folder)
            return 'SSH is on' if enabled else 'SSH is off'
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
        if self.portal:self.portal.configure_dns()
        def run(args, stage, **kwargs):
            try:return self.run(args, **kwargs)
            except (OSError, subprocess.SubprocessError) as exc:
                # Keep the useful failure, without logging argv (which may contain PSK).
                detail = getattr(exc,'stderr',None) or getattr(exc,'stdout',None) or ''
                if isinstance(detail,bytes):detail=detail.decode(errors='replace')
                detail=' '.join(str(detail).split())
                for secret in (creds['password'],creds['ssid']):
                    detail=detail.replace(secret,'[redacted]')
                detail=re.sub(r'[\x00-\x1f\x7f]','',detail)[:280]
                reason = ('Required Wi-Fi tool is missing: '+args[0] if isinstance(exc,FileNotFoundError)
                          else 'Wi-Fi command timed out' if isinstance(exc,subprocess.TimeoutExpired)
                          else detail or 'Wi-Fi command failed')
                failure=dict(operation='hotspot',stage=stage,error=type(exc).__name__,
                             returncode=getattr(exc,'returncode',None),reason=reason)
                atomic_json(self.state.folder/'maintenance-failure.json',failure)
                print(json.dumps(dict(state='hotspot_failed',**failure)),flush=True)
                raise ValueError('Hotspot '+stage+': '+reason) from None
        # Image prep / Imager must set country first; never guess a regulatory domain.
        domain = run(['iw','reg','get'],'country check',timeout=5).stdout
        if not re.search(r'country (?!00:)[A-Z]{2}:', domain):
            raise ValueError('Set Wi-Fi country in Raspberry Pi Imager or connect Ethernet for setup')
        # rfkill and NetworkManager keep separate radio state. Enable both, even
        # if the initial boot unblocked rfkill before NM restored a disabled state.
        run(['rfkill','unblock','wifi'],'radio enable',timeout=5)
        run(['nmcli','radio','wifi','on'],'radio enable',timeout=10)
        rc = run(['nmcli','-t','-f','NAME','connection','show'],'profile check',timeout=5).stdout.splitlines()
        if 'HLauncher Recovery' not in rc:
            run(['nmcli','connection','add','type','wifi','ifname','wlan0','con-name','HLauncher Recovery',
                 'ssid',creds['ssid'],'802-11-wireless.mode','ap','ipv4.method','shared',
                 'ipv4.addresses','192.168.4.1/24','ipv6.method','disabled',
                 'wifi-sec.key-mgmt','wpa-psk','wifi-sec.psk',creds['password'],
                 'connection.autoconnect','no'],'profile creation',timeout=10)
        run(['nmcli','--wait','15','connection','up','HLauncher Recovery'],'activation',timeout=20)
        self.ap = True
        if self.portal:self.portal.start()
        (self.state.folder/'maintenance-failure.json').unlink(missing_ok=True)

    def finish_initial_hotspot(self, setup_complete):
        # A user-requested recovery AP stays up until they connect normal Wi-Fi.
        if not (self.ap and self.ap_automatic and setup_complete and self.state.peer):return False
        self.run(['nmcli','connection','down','HLauncher Recovery'],timeout=10)
        self.ap = False; self.ap_automatic = False
        return True

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


PAGE = '''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>HLauncher setup</title>
<style>
@font-face{font-family:Radio;src:url('/ui-font.ttf');font-weight:700}*{box-sizing:border-box}[hidden]{display:none!important}body{margin:0;background:#09090d;color:#f5f4fb;font:16px system-ui,sans-serif;--accent:112,12,29}header{height:64px;border-bottom:1px solid rgba(var(--accent),.8);display:flex;align-items:center;gap:12px;padding:0 20px;background:linear-gradient(#25232d,#111017)}header b{font-size:24px;font-weight:500}header small{font-size:12px;color:#a5a0ae}header time{margin-left:auto;font-size:26px}.grid{display:grid;grid-template-columns:repeat(3,5px);gap:3px;margin-right:12px}.grid i{height:5px;background:#eee}main{max-width:640px;padding:24px 20px 48px;margin:auto}h1,h2,button,summary{font-family:Radio,system-ui,sans-serif;font-weight:700}h1{font-size:28px;margin:0 0 12px}h2{font-size:23px;margin:0 0 12px}section,details{margin:28px 0}p{line-height:1.5;margin:8px 0 16px;color:#c2c0cc}.status{padding:12px 0;border-bottom:1px solid #38333f;color:#ddd8e8}label{display:block;color:#c2c0cc;font-size:14px;margin:14px 0 6px}input::file-selector-button{background:#302a39;color:#f5f4fb;border:1px solid #756a82;border-radius:4px;padding:8px 12px;margin-right:12px;font:inherit}input{width:100%;padding:13px 12px;background:#17151d;color:#f4f2fa;border:1px solid #61586b;border-radius:5px;font:inherit}button{display:block;width:100%;min-height:46px;padding:10px 14px;margin:14px 0;background:linear-gradient(rgba(var(--accent),.22),rgba(var(--accent),.10) 50%,rgba(var(--accent),.28)),#161419;border:1px solid rgba(var(--accent),.95);border-radius:6px;color:#f5f4fb;font-size:20px;cursor:pointer}button.secondary{background:#27242e;border-color:#6d6479}button:disabled{opacity:.55;cursor:wait}button:focus-visible,input:focus-visible,summary:focus-visible{outline:2px solid #e5dcef;outline-offset:3px}.row{display:flex;gap:12px}.row>*{flex:1}summary{font-size:22px;cursor:pointer}small{color:#a9a2b4}#notice{color:#e3c397}footer{border-top:1px solid #38333f;padding-top:16px;color:#a9a2b4;font-size:13px}
</style></head><body><header><span class="grid" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></span><b>HLauncher</b><small>by Evan Horsley</small></header><main>
<h1>Wi-Fi &amp; pairing</h1><p id="notice" role="status"></p>
<section><h2>Connect the Pi to Wi-Fi</h2><p>Choose the network the Pi should use. After connecting, join that same network on your phone or computer.</p>
<label for="ssid">Wi-Fi name</label><input id="ssid" autocomplete="off" placeholder="Network name">
<label for="password">Wi-Fi password</label><input id="password" type="password" autocomplete="new-password">
<label for="country">Country code</label><input id="country" placeholder="US" maxlength="2" autocapitalize="characters">
<button onclick="wifi()">Connect to Wi-Fi</button></section>
<section><h2>Local update</h2><p>Install a signed .hlu file from your computer. Your settings stay saved; HLauncher restarts after verification.</p>
<label for="updatefile">Update file</label><input type="file" id="updatefile" accept=".hlu"><button id="uploadbutton" onclick="uploadUpdate()">Install local update</button><p id="uploadstatus" role="status"></p></section>
<section><h2>SSH access</h2><p id="sshstate">Checking SSH…</p><p>Username: <b>pi</b><br>Default password: <b>raspberry</b></p><button id="sshbutton" class="secondary" onclick="toggleSSH()">Enable SSH</button></section>
<details><summary>Radio pairing</summary><p>On the radio, open Settings → Phone → Connect a phone → Add Bluetooth device. Select HLauncher and confirm the pairing code. To replace the saved radio, reopen pairing below.</p>
<button class="secondary" onclick="act('pair')">Forget radio and reopen pairing</button>
<details><summary>Enter a radio address manually</summary><p>Use this only if the radio was not recognized automatically.</p><label for="peer">Bluetooth address</label><input id="peer" placeholder="AA:BB:CC:DD:EE:FF"><button class="secondary" onclick="manual()">Allow this radio for five minutes</button></details></details>
<details><summary>Support</summary><p>Debug mode enables the hardware tests and detailed logging on the Pi.</p><button class="secondary" onclick="debug()">Toggle debug mode</button><button id="capture" class="secondary" hidden onclick="location.href='/debug-capture'">Download latest debug capture</button><button class="secondary" onclick="location.href='/report'">Download diagnostic summary</button></details>

<script>
const themes={Blue:'34,20,170',Red:'112,12,29',Green:'10,105,59',Amber:'148,81,9',Purple:'98,25,154',Graphite:'72,85,104'};
async function post(path,data){try{let r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});let v=await r.json();if(!r.ok)throw new Error(v.error||'Request failed');document.getElementById('notice').textContent='Requested';refresh();return true}catch(e){document.getElementById('notice').textContent=e.message;return false}}
function act(operation){if(operation==='pair'&&!confirm('Forget the saved radio and restart pairing?'))return;post('/api/job',{operation})}
function manual(){post('/api/manual',{address:document.getElementById('peer').value})}
async function wifi(){if(!document.getElementById('ssid').value)return;let queued=await post('/api/job',{operation:'wifi',ssid:document.getElementById('ssid').value,password:document.getElementById('password').value,country:document.getElementById('country').value.toUpperCase()});if(queued){document.getElementById('password').value='';document.getElementById('notice').textContent='The Pi is switching networks. Reconnect this device to the same Wi-Fi afterward.'}}
async function uploadUpdate(){let file=document.getElementById('updatefile').files[0];if(!file){document.getElementById('uploadstatus').textContent='Choose a .hlu file';return}if(!confirm('Install this signed update and restart HLauncher?'))return;let button=document.getElementById('uploadbutton');button.disabled=true;document.getElementById('uploadstatus').textContent='Uploading…';try{let response=await fetch('/api/update-file',{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:file});let data=await response.json();if(!response.ok)throw new Error(data.error||'Upload failed');document.getElementById('uploadstatus').textContent='Uploaded. Verifying and installing; HLauncher will restart.'}catch(error){document.getElementById('uploadstatus').textContent=error.message}finally{button.disabled=false}}
let sshEnabled=false;
function toggleSSH(){post('/api/job',{operation:'ssh',enabled:!sshEnabled})}
function debug(){post('/api/debug',{})}
async function refresh(){try{let r=await fetch('/api/status');let data=await r.json();document.body.style.setProperty('--accent',themes[data.theme]||(/^#[0-9A-Fa-f]{6}$/.test(data.theme||'')?[1,3,5].map(i=>parseInt(data.theme.slice(i,i+2),16)).join(','):themes.Red));document.getElementById('capture').hidden=!data.debug;sshEnabled=!!data.ssh?.enabled;document.getElementById('sshstate').textContent=sshEnabled?'SSH is on':'SSH is off';document.getElementById('sshbutton').textContent=sshEnabled?'Disable SSH':'Enable SSH';let job=data.maintenance||{};if(job.status==='Working')document.getElementById('notice').textContent='Applying connection changes…';else if(job.status==='Failed')document.getElementById('notice').textContent=job.message||job.status;else if(job.status==='Done')document.getElementById('notice').textContent=''}catch{}}
refresh();setInterval(refresh,3000)
</script></main></body></html>'''


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
        def do_GET(self):
            if self.path == '/': return self.send(200,PAGE,'text/html; charset=utf-8')
            if self.path == '/ui-font.ttf':
                path=Path(__file__).parent/'ui/assets/fonts/NotoSansJP.ttf'
                self.send_response(200);self.send_header('Content-Type','font/ttf')
                self.send_header('Content-Length',str(path.stat().st_size));self.end_headers()
                with path.open('rb') as source:
                    while block:=source.read(65536):self.wfile.write(block)
                return
            if self.path == '/api/status':
                return self.send(200,dict(radio=state.peer or 'Waiting for pairing',
                    setup_complete=Preferences().data['setup_complete'], debug=Preferences().data['debug_mode'],
                    maintenance=job_status(),storage=storage_status(),connection=connection_status(),
                    network=network_status(),ssh=ssh_status(state.folder),theme=Preferences().data['tile_color']))
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
        def upload_update(self):
            from . import updater, update_client
            import fcntl
            if self.headers.get('Content-Type')!='application/octet-stream':
                return self.send(415,{'error':'Choose a signed .hlu file'})
            config=updater.read(UPDATER_CONFIG)
            if not config:return self.send(409,{'error':'Requires an update-enabled image'})
            inbox=Path(config['root'])/'inbox';inbox.mkdir(mode=0o700,parents=True,exist_ok=True)
            lock=(inbox/'.upload-lock').open('a')
            try:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                info=update_client.status(state.folder)
                if info.get('phase') in ('checking','downloading','installing'):
                    return self.send(409,{'error':'Another update operation is running'})
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=updater.MAX_PACKAGE+262144:raise ValueError('Invalid update file size')
                if (inbox/'local-update.hlu').exists() or (state.folder/'update-request.json').exists():
                    return self.send(409,{'error':'An update is already queued'})
                import shutil
                if shutil.disk_usage(inbox).free<size*2+updater.RESERVE:raise ValueError('Not enough storage for this file')
                partial=inbox/'.upload.part'
                try:
                    with partial.open('wb') as output:
                        remaining=size
                        while remaining:
                            block=self.rfile.read(min(65536,remaining))
                            if not block:raise ValueError('Upload was interrupted')
                            output.write(block);remaining-=len(block)
                        output.flush();os.fsync(output.fileno())
                    os.replace(partial,inbox/'local-update.hlu');updater.sync_dir(inbox)
                    try:update_client.request('import',state.folder)
                    except Exception:
                        (inbox/'local-update.hlu').unlink(missing_ok=True)
                        raise
                finally:partial.unlink(missing_ok=True)
                self.send(202,{'status':'Local update queued'})
            except BlockingIOError:self.send(409,{'error':'Another upload is running'})
            except (OSError,ValueError):self.send(400,{'error':'Local update upload failed; check storage and retry'})
            finally:lock.close()

        def do_POST(self):
            origin = self.headers.get('Origin')
            if origin and urlsplit(origin).netloc != self.headers.get('Host'):
                return self.send(403,{'error':'Origin rejected'})
            if self.path=='/api/update-file':return self.upload_update()
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
                    if data.get('operation') not in ('pair','wifi','ssh'): raise ValueError('Operation unavailable here')
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
    from .captive_portal import Portal
    portal=Portal(RecoveryServer)
    state = SetupState(); state.credentials(); maintenance = Maintenance(state,portal=portal)
    def worker():
        seen = None; hotspot_attempted = False
        while True:
            try:portal.start()
            except OSError:pass
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
                if not connected: maintenance.process({'operation':'hotspot','automatic':True})
            try: maintenance.finish_initial_hotspot(Preferences().data['setup_complete'])
            except subprocess.SubprocessError: pass
            try:
                from .ssh_access import refresh
                refresh(state.folder)
            except OSError:pass
            try:atomic_json(state.folder/'network-status.json',sample_network(maintenance.run))
            except OSError:pass
            time.sleep(2)
    threading.Thread(target=worker,daemon=True).start()
    server = RecoveryServer(('0.0.0.0',8080),handler_for(state,maintenance))
    server.timeout = 5
    server.serve_forever()


if __name__ == '__main__': main()
