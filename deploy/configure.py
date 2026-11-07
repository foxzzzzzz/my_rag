import argparse, json, re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def configure(hostname, output, port=8768, enable_douyin=False, force=False):
    if not re.fullmatch(r"(?=.{1,253}$)[a-zA-Z0-9]+(?:[a-zA-Z0-9-]*[a-zA-Z0-9])?(?:\.[a-zA-Z0-9]+(?:[a-zA-Z0-9-]*[a-zA-Z0-9])?)+", hostname): raise ValueError("invalid hostname")
    if type(port) is not int or not 1 <= port <= 65535: raise ValueError("invalid port")
    hostname=hostname.lower()
    output=Path(output)
    sources=list((ROOT/'config').glob('*.json'))
    if not force and any((output/src.name).exists() for src in sources): raise FileExistsError("configuration already exists; use --force")
    output.mkdir(parents=True, exist_ok=True)
    def rewrite(obj):
        if isinstance(obj, dict):
            return {k: ('/state/budget.sqlite' if k == 'ledger' else '/run/secrets/personalkb.env' if k == 'env_file' else rewrite(v)) for k,v in obj.items()}
        if isinstance(obj, list): return [rewrite(v) for v in obj]
        return obj
    for src in sources:
        data=rewrite(json.loads(src.read_text(encoding='utf-8-sig')))
        if src.name=='maintenance.json': data.update(ledger_paths=['/state/budget.sqlite'], backup_root='/backups', auto_retention_enabled=True)
        if src.name=='auth.json': data['enabled']=True
        if src.name=='workflow.json': data['data_dir']='/state/workflow'
        if src.name=='douyin.json': data.update(enabled=enable_douyin, resolver_python='/opt/douyin/bin/python')
        if src.name=='web.json': data.update(host='127.0.0.1', port=port, trusted_hosts=[hostname,'127.0.0.1'], trusted_origins=['https://'+hostname], deployment_mode='production', dispatch_enabled=False, live_video_enabled=False, live_html_enabled=False, auth_config='config/auth.json')
        (output/src.name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--hostname',required=True); p.add_argument('--output',required=True); p.add_argument('--port',type=int,default=8768); p.add_argument('--enable-douyin',action='store_true'); p.add_argument('--force',action='store_true'); a=p.parse_args(); configure(a.hostname,a.output,a.port,a.enable_douyin,a.force)

