"""Explicit HTML live processing; no secrets in output."""
import argparse
import json
import os
from personalkb.workflow import ROOT, load_config
from personalkb.workflow_store import WorkflowError
from personalkb.html_pipeline import load_html_config, run_html, html_status


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--config',default='config/workflow.json');p.add_argument('--pipeline-config',default='config/html-pipeline.json')
    p.add_argument('--env-file',default='.env')
    p.add_argument('action',choices=('run','resume','status'));p.add_argument('task_id');p.add_argument('--live',action='store_true')
    a=p.parse_args()
    try:
        wc=load_config(ROOT/a.config)
        if a.action=='status': result=html_status(wc,a.task_id)
        else:
            if not a.live: raise WorkflowError('live_confirmation_required')
            from tools.demo_setup import dotenv
            keys=dotenv(ROOT/a.env_file);keys.update(os.environ)
            v=run_html(wc,load_html_config(ROOT/a.pipeline_config),keys,task_id=a.task_id,resume=a.action=='resume')
            result={k:v[k] for k in ('id','source_id','content_sha256','output_kind')}
        print(json.dumps(result,ensure_ascii=False));return 0
    except WorkflowError as e:
        print(json.dumps({'error':e.code}));return 1

if __name__=='__main__': raise SystemExit(main())
