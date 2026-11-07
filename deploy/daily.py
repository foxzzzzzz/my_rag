import argparse, datetime, json, os, re, subprocess, sys
from pathlib import Path

def write_report(path, report):
    p=Path(path); tmp=p.with_suffix('.tmp'); tmp.write_text(json.dumps(report,ensure_ascii=False)+'\n',encoding='utf-8'); tmp.replace(p)
def daily(config, report):
    project=os.environ.get('PERSONALKB_COMPOSE_PROJECT','personalkb')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*',project): raise ValueError('invalid project name')
    result={'time_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'state':'failed','snapshot':None,'services_restored':None,'retention':{'applied':False,'result':None}}
    def run(profile, service, command, *args):
        env_args=[]
        if command in ('push','pull'):
            for key in ('access_key_id_env','access_key_secret_env'):
                name=cfg['oss'][key]
                if not isinstance(name,str) or not re.fullmatch(r'[A-Z_][A-Z0-9_]*',name): raise ValueError('invalid credential variable name')
                if name in os.environ: env_args.extend(['-e',name])
        p=subprocess.run(['docker','compose','--project-name',project,'--profile',profile,'run','--rm',*env_args,service,'python','-m','tools.maintenance','--config','/app/config/maintenance.json',command,*args],capture_output=True,text=True,check=True)
        return json.loads(p.stdout)
    try:
        cfg=json.loads(Path(config).read_text(encoding='utf-8-sig'))
        mode=cfg['storage_mode']
        if mode not in ('manual','oss'): raise ValueError('invalid storage mode')
        result['snapshot']=run('maintenance','maintenance','create')['snapshot']
        run('maintenance','maintenance','verify',result['snapshot'])
        enabled=cfg.get('auto_retention_enabled',False)
        if type(enabled) is not bool: raise ValueError('invalid retention setting')
        if enabled:
            result['retention']['result']=run('maintenance','maintenance','retention','--apply')
            result['retention']['applied']=True
        if mode=='oss': run('push','push','push',result['snapshot'])
        else: print('Manual backup: copy the verified snapshot repository to external storage.')
        result['state']='success'
    except Exception:
        write_report(report,result); raise
    write_report(report,result)
if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--config',required=True); p.add_argument('--report',required=True); a=p.parse_args()
    try: daily(a.config,a.report)
    except Exception: print('Daily backup failed; inspect local service logs.',file=sys.stderr); sys.exit(1)
