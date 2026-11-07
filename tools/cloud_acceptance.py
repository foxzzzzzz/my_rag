"""User-run, non-paid HTTPS acceptance and passive host sampling."""
import argparse
import getpass
import http.cookiejar
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

class RejectedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate(config, origin, seconds):
    url = urllib.parse.urlsplit(origin)
    if origin != config['allowed_origin'] or url.scheme != 'https' or not url.hostname or url.username or url.password or url.path or url.query or url.fragment: raise ValueError('invalid_origin')
    for name in ('request_timeout_seconds','max_response_bytes','max_sample_seconds','sample_interval_seconds'):
        if type(config[name]) is not int or config[name] < 1: raise ValueError('invalid_config')
    if type(seconds) is not int or seconds < 0 or seconds > min(300, config['max_sample_seconds']): raise ValueError('invalid_sample_duration')
    path = config.get('protected_historical_path')
    if path is not None and (not isinstance(path,str) or not path.startswith('/') or path.startswith('//') or '\\' in path or '?' in path or '#' in path or '..' in path.split('/')): raise ValueError('invalid_historical_path')


def client():
    return urllib.request.build_opener(RejectedRedirect(), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), urllib.request.HTTPSHandler())


def _request(opener, config, origin, path, *, body=None, csrf=None):
    headers = {'Accept':'application/json'}
    if body is not None:
        headers.update({'Content-Type':'application/json','Origin':origin})
        body = json.dumps(body).encode()
    if csrf is not None: headers['X-CSRF-Token'] = csrf
    req = urllib.request.Request(origin + path, data=body, headers=headers, method='POST' if body is not None else 'GET')
    try: response = opener.open(req, timeout=config['request_timeout_seconds'])
    except urllib.error.HTTPError as e: response = e
    with response:
        status = response.status
        if 300 <= status < 400: raise ValueError('redirect_rejected')
        data = response.read(config['max_response_bytes']+1)
        if len(data) > config['max_response_bytes']: raise ValueError('response_too_large')
        try: payload = json.loads(data) if data else {}
        except (ValueError, UnicodeError): payload = {}
        cookies = response.headers.get_all('Set-Cookie') or []
        return status, payload, cookies


def _cookie_flags(headers):
    relevant = [v.lower() for v in headers if v.lower().startswith('pkb_session=')]
    return {'secure':any('secure' in h.split(';') or any(p.strip() == 'secure' for p in h.split(';')) for h in relevant),
            'http_only':any(any(p.strip() == 'httponly' for p in h.split(';')) for h in relevant),
            'same_site_strict':any(any(p.strip() == 'samesite=strict' for p in h.split(';')) for h in relevant)}


def host_info(config):
    out={'system':platform.system(), 'architecture':platform.machine(), 'cpu_count':os.cpu_count(), 'disk':None, 'versions':{}}
    try:
        disk=shutil.disk_usage(config['disk_path']); out['disk']={'total_bytes':disk.total,'free_bytes':disk.free}
    except OSError: pass
    try:
        import psutil
        mem=psutil.virtual_memory(); swap=psutil.swap_memory()
        out['memory']={'total_bytes':mem.total,'used_bytes':mem.total-mem.available,'swap_used_bytes':swap.used}
    except ImportError:
        out['memory']=None
        try:
            info={}
            for line in Path('/proc/meminfo').read_text().splitlines():
                key, value = line.split(':', 1)
                if key in ('MemTotal','MemAvailable','SwapTotal','SwapFree'): info[key] = int(value.split()[0]) * 1024
            out['memory']={'total_bytes':info['MemTotal'],'used_bytes':info['MemTotal']-info['MemAvailable'],'swap_used_bytes':info['SwapTotal']-info['SwapFree']}
        except (OSError, ValueError, KeyError): pass
    for name,cmd in (('docker',['docker','--version']),('compose',['docker','compose','version','--short'])):
        try:
            p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,timeout=config['request_timeout_seconds'],check=True)
            out['versions'][name]=p.stdout.strip()[:200]
        except (OSError,subprocess.SubprocessError): out['versions'][name]=None
    return out


def sample(config, seconds):
    if not seconds: return {'status':'not_requested','samples':[]}
    try: import psutil
    except ImportError: return {'status':'psutil_unavailable','samples':[]}
    result=[]; start=time.monotonic(); proc=psutil.Process()
    while time.monotonic()-start < seconds:
        m=psutil.virtual_memory(); sw=psutil.swap_memory()
        try: disk=shutil.disk_usage(config['disk_path']); free=disk.free
        except OSError: free=None
        result.append({'elapsed_seconds':round(time.monotonic()-start,2),'memory_used_bytes':m.total-m.available,'memory_total_bytes':m.total,'process_rss_bytes':proc.memory_info().rss,'swap_used_bytes':sw.used,'disk_free_bytes':free})
        time.sleep(min(config['sample_interval_seconds'],max(0,seconds-(time.monotonic()-start))))
    return {'status':'observed_only','samples':result,'workload':'user_managed_not_verified'}


def run(config, origin, password, seconds=0, opener=None):
    validate(config, origin, seconds)
    out={'https_tested':False,'host':host_info(config),'checks':{},'resource_sampling':{'status':'not_tested'},'paid_end_to_end':'not_tested','cost':'not_tested','external_backup_restore':'not_tested','hard_interrupt':'not_tested'}
    checks=out['checks']; op=opener or client()
    try:
        status, _, _ = _request(op,config,origin,'/api/session'); out['https_tested']=True; checks['unauthenticated_session']=status
        historical=config.get('protected_historical_path')
        checks['historical_path']=_request(op,config,origin,historical)[0] if historical else 'not_configured'
        if status != 401: raise ValueError('unexpected_auth_state')
        status, _, headers = _request(op,config,origin,'/api/auth/login',body={'password':password}); checks['login']=status; checks['cookie_flags']=_cookie_flags(headers)
        if status != 200: raise ValueError('login_failed')
        status, session, _ = _request(op,config,origin,'/api/session'); checks['authenticated_session']=status
        if status != 200 or not isinstance(session,dict) or not isinstance(session.get('csrf_token'),str): raise ValueError('session_failed')
        csrf=session['csrf_token']
        status, source, _ = _request(op,config,origin,'/api/sources'); checks['sources_status']=status
        items=source.get('items') if isinstance(source,dict) else source
        checks['source_count']=len(items) if status == 200 and isinstance(items,list) else None
        status, rag, _ = _request(op,config,origin,'/api/rag/status'); checks['rag_status']=status
        checks['rag']={k:rag[k] for k in ('enabled','ready','needs_rebuild','eligible_sources','indexed_sources','indexed_chunks') if k in rag and type(rag[k]) in (bool,int)} if status == 200 and isinstance(rag,dict) else None
        checks['logout_without_csrf']=_request(op,config,origin,'/api/auth/logout',body={})[0]
        checks['logout_with_csrf']=_request(op,config,origin,'/api/auth/logout',body={},csrf=csrf)[0]
        checks['session_after_logout']=_request(op,config,origin,'/api/session')[0]
        out['resource_sampling']=sample(config,seconds)
        out['result']='passed' if (checks['unauthenticated_session']==401 and checks['login']==200 and all(checks['cookie_flags'].values()) and checks['authenticated_session']==200 and checks['sources_status']==200 and checks['rag_status']==200 and checks['logout_without_csrf']==403 and checks['logout_with_csrf']==200 and checks['session_after_logout']==401 and (not historical or checks['historical_path'] in (401,403))) else 'failed'
    except Exception as e:
        out['result']='failed'; out['error']=str(e) if isinstance(e,ValueError) and str(e) in ('redirect_rejected','response_too_large','unexpected_auth_state','login_failed','session_failed') else 'connection_or_protocol_error'
    return out


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--url',required=True); parser.add_argument('--output',required=True); parser.add_argument('--config',default=str(ROOT/'config/cloud-acceptance.json')); parser.add_argument('--sample-seconds',type=int,default=0)
    args=parser.parse_args()
    try:
        config=json.loads(Path(args.config).read_text(encoding='utf-8-sig')); validate(config,args.url,args.sample_seconds)
        with open(args.output,'x',encoding='utf8') as f:
            password=getpass.getpass('PersonalKB password: ')
            report=run(config,args.url,password,args.sample_seconds); password=None
            json.dump(report,f,ensure_ascii=False,indent=2); f.write('\n')
        print(json.dumps({'result':report['result'],'report':args.output},ensure_ascii=False))
        return 0 if report['result']=='passed' else 1
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps({'error':'invalid_configuration_or_output'}),file=sys.stderr); return 1

if __name__=='__main__': sys.exit(main())
