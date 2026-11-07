import argparse, json, os, platform, shutil, socket, stat, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def probe(config, state, secret, port=8768):
    min_free=None
    result={'system':platform.system(),'architecture':platform.machine(),'config_valid':False,'compose_available':False,'ffmpeg_available':bool(shutil.which('ffmpeg')),'port_available':False,'disk_free_bytes':None,'secret_file_exists':Path(secret).is_file(),'auth_hash_present':False,'auth_valid':False,'secret_permissions_private':None,'model_key_in_environment':any(bool(os.environ.get(k)) for k in ('DASHSCOPE_API_KEY','DEEPSEEK_API_KEY')),'tls_verified':False,'domain_verified':False}
    try:
        c=json.loads(Path(config).read_text(encoding='utf-8-sig'))
        result['config_valid']=(c.get('deployment_mode')=='production' and c.get('host')=='127.0.0.1' and c.get('port')==port and c.get('dispatch_enabled') is False and bool(c.get('trusted_hosts')) and bool(c.get('trusted_origins')))
        wc=json.loads((Path(config).parent/'workflow.json').read_text(encoding='utf-8-sig'))
        min_free=int(wc['min_free_bytes'])
    except (ValueError, OSError, KeyError, TypeError): pass
    try:
        from tools.demo_setup import dotenv
        from personalkb.web_auth import load_auth, validate_hash
        auth_path=Path(config).parent/'auth.json'
        auth=json.loads(auth_path.read_text(encoding='utf-8-sig'))
        values=dotenv(Path(secret)); value=values.get(auth['password_hash_env'])
        result['auth_hash_present']=bool(value)
        validate_hash(value)
        local=dict(c, auth_config=str(auth_path.resolve()), env_file=str(Path(secret).resolve()))
        load_auth(local)
        result['auth_valid']=True
    except Exception: pass
    try:
        p=subprocess.run(['docker','compose','version','--short'],capture_output=True,text=True,timeout=10)
        result['compose_available']=p.returncode==0
        if p.returncode==0: result['compose_version']=p.stdout.strip()[:100]
    except (OSError,subprocess.TimeoutExpired): pass
    try: result['disk_free_bytes']=shutil.disk_usage(state).free
    except OSError: pass
    try:
        with socket.socket() as s: s.bind(('127.0.0.1',port)); result['port_available']=True
    except OSError: pass
    try: result['secret_permissions_private']=(stat.S_IMODE(Path(secret).stat().st_mode)&0o077)==0
    except OSError: pass
    result['port_owner']='unknown' if not result['port_available'] else None
    result['ready']=(result['system']=='Linux' and result['architecture'] in ('x86_64','AMD64') and result['config_valid'] and result['compose_available'] and result['port_available'] and result['secret_file_exists'] and result['auth_valid'] and result['secret_permissions_private'] is True and min_free is not None and (result['disk_free_bytes'] or 0)>=min_free)
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--config',required=True); p.add_argument('--state',required=True); p.add_argument('--secret',required=True); p.add_argument('--port',type=int,default=8768); a=p.parse_args(); result=probe(a.config,a.state,a.secret,a.port); print(json.dumps(result,indent=2)); sys.exit(0 if result['ready'] else 1)
