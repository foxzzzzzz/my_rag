"""Explicit downloader operations; never starts model processing."""
import argparse,json,os
from pathlib import Path
from personalkb.workflow import ROOT,load_config
from personalkb.workflow_store import WorkflowError
from personalkb.douyin import load_douyin_config
from personalkb.douyin_import import DouyinImporter
from tools.demo_setup import dotenv

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--config',default='config/workflow.json');p.add_argument('--douyin-config',default='config/douyin.json');p.add_argument('--env-file',default='.env')
    sub=p.add_subparsers(dest='action',required=True)
    for cmd in ('status','jobs','recover','run-once'):sub.add_parser(cmd)
    a=sub.add_parser('import');a.add_argument('share_text');a.add_argument('--rights-confirmed',action='store_true')
    a=sub.add_parser('retry');a.add_argument('job_id')
    a=p.parse_args(argv)
    try:
        cfg=load_douyin_config(ROOT/a.douyin_config);path=ROOT/a.env_file;keys=dotenv(path) if path.exists() else {};keys.update(os.environ)
        importer=DouyinImporter(load_config(ROOT/a.config),cfg,{cfg['cookie_env']:keys.get(cfg['cookie_env'],'')})
        if a.action=='status':result=importer.status()
        elif a.action=='jobs':result={'items':importer.jobs()}
        elif a.action=='recover':importer.recover_expired();result={'recovered':True}
        elif a.action=='run-once':result=importer.process_next()
        elif a.action=='retry':result=importer.retry(a.job_id)
        else:result=importer.enqueue(a.share_text,a.rights_confirmed)
        print(json.dumps(result,ensure_ascii=True));return 0
    except WorkflowError as e:print(json.dumps({'error':e.code}));return 1
    except (OSError,ValueError):print(json.dumps({'error':'douyin_operation_failed'}));return 1
if __name__=='__main__':raise SystemExit(main())
