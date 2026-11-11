import argparse, signal, threading, time
from pathlib import Path
from personalkb import workflow
from personalkb.web_app import load_web_config
from personalkb.video_pipeline import load_pipeline_config
from personalkb.web_service import WebService
from personalkb.runtime_guard import runtime_guard
from personalkb.workflow_store import WorkflowError

def main():
    p=argparse.ArgumentParser(); p.add_argument('--config',default='config/web.json'); a=p.parse_args()
    c=load_web_config(a.config); wc=workflow.load_config(c['workflow_config'])
    stop=threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT): signal.signal(sig, lambda *_: stop.set())
    with runtime_guard(wc['data_dir'],'worker'):
        service=WebService(wc,load_pipeline_config(Path(c['pipeline_config'])),c)
        service.stop_requested=stop.is_set
        while not stop.is_set():
            try: service.process_next()
            except WorkflowError as exc:
                if 'busy' not in str(exc).lower(): raise
            stop.wait(c.get('dispatch_poll_seconds',1))
if __name__=='__main__': main()

