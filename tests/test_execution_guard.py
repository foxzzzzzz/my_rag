import threading
import pytest
from personalkb.execution_guard import execution_guard
from personalkb.workflow_store import WorkflowStore, WorkflowError

def test_cancelled_execution_keeps_other_worker_out(tmp_path):
    db=tmp_path/'db.sqlite'; a=WorkflowStore(db); b=WorkflowStore(db)
    first=a.import_source('html','a'*64,'a','a')['task']
    second=a.import_source('html','b'*64,'b','b')['task']
    started=threading.Event(); release=threading.Event(); result=[]
    def run():
        with execution_guard(a):
            t=a.claim_specific(first['id'],'a'); a.checkpoint(t['id'],t['lease_token'],'remote',external_started=True)
            started.set(); release.wait(5)
            try: a.heartbeat(t['id'],t['lease_token'])
            except WorkflowError as e: result.append(e.code)
    thread=threading.Thread(target=run); thread.start(); assert started.wait(5)
    try:
        a.cancel(first['id']); assert b.claim_specific(second['id'],'b') is None
        with pytest.raises(WorkflowError, match='worker_busy'):
            with execution_guard(b): pass
    finally:
        release.set(); thread.join(5)
    assert result == ['invalid_lease']
    assert b.claim_specific(second['id'],'b') is not None

def test_nested_and_exception_release(tmp_path):
    store=WorkflowStore(tmp_path/'db.sqlite')
    with pytest.raises(ValueError):
        with execution_guard(store):
            with execution_guard(store): raise ValueError()
    with execution_guard(store): pass

def test_process_termination_releases_lock(tmp_path):
    import subprocess, sys, os
    db=tmp_path/'db.sqlite'; store=WorkflowStore(db)
    code='''import sys, time
from personalkb.workflow_store import WorkflowStore
from personalkb.execution_guard import execution_guard
with execution_guard(WorkflowStore(sys.argv[1])):
 print("ready", flush=True)
 time.sleep(60)
'''
    proc=subprocess.Popen([sys.executable, '-u', '-c', code, str(db)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        assert proc.stdout.readline().strip() == 'ready'
        with pytest.raises(WorkflowError, match='worker_busy'):
            with execution_guard(store): pass
    finally:
        proc.terminate(); proc.wait(timeout=10)
        proc.stdout.close(); proc.stderr.close()
    with execution_guard(store): pass

def test_delete_during_html_provider_blocks_other_work(tmp_path):
    from personalkb.workflow import load_config, import_file, make_store
    from personalkb.html_pipeline import load_html_config, run_html
    from personalkb.video_pipeline import run_video, cleanup_video
    from personalkb.douyin_import import DouyinImporter
    from personalkb.web_dispatch import WebDispatcher
    from unittest.mock import Mock
    wc=load_config(); wc['data_dir']=str(tmp_path/'data'); wc['min_free_bytes']=0
    hc=load_html_config(); hc['budget']['ledger']=str(tmp_path/'ledger.sqlite')
    source=tmp_path/'one.html'; source.write_text('<html><title>one</title><body>content</body></html>',encoding='utf8')
    first=import_file(wc,source,True); store=make_store(wc)
    second=store.import_source('html','b'*64,'other','other')
    started=threading.Event(); release=threading.Event(); errors=[]
    class Provider:
        def summarize(self, body, title):
            started.set(); assert release.wait(10)
            return {'structured':{'summary':'summary','notes':'notes'},'model':'fake','usage':{'input_tokens':1,'output_tokens':1},'estimated_cost_cny':'0.001'}
    def run():
        try: run_html(wc,hc,{},task_id=first['task']['id'],services=Provider())
        except WorkflowError as e: errors.append(e.code)
    thread=threading.Thread(target=run); thread.start(); assert started.wait(10)
    try:
        store.delete_source(first['source']['id'])
        assert make_store(wc).claim_specific(second['task']['id'],'other') is None
        fake=Mock()
        with pytest.raises(WorkflowError,match='worker_busy'):
            run_video(wc,{}, {},task_id='unused',resume=True,services=fake,media=fake,storage=fake)
        with pytest.raises(WorkflowError,match='worker_busy'):
            cleanup_video(wc,{}, {},'unused',storage=fake)
        cfg={'enabled':True,'resolver_python':__import__('sys').executable,'cookie_env':'COOKIE','lease_seconds':30,'max_attempts':3,'min_free_bytes':1}
        downloader=DouyinImporter(wc,cfg,{'COOKIE':'secret'},share_resolver=lambda u,c:'123',resolver=fake,downloader=fake)
        downloader.enqueue('https://www.douyin.com/video/123',True)
        with pytest.raises(WorkflowError,match='worker_busy'): downloader.process_next()
        fake.assert_not_called()
        dispatcher=object.__new__(WebDispatcher); dispatcher.store=store
        assert dispatcher.process_next() is None
    finally:
        release.set(); thread.join(10)
    assert not thread.is_alive()
    assert errors and store.list_versions(first['source']['id']) == []
    assert make_store(wc).claim_specific(second['task']['id'],'other') is not None

@pytest.mark.skipif(not hasattr(__import__('os'), 'fork'), reason='requires POSIX fork')
def test_fork_does_not_inherit_reentrant_ownership(tmp_path):
    import os
    store=WorkflowStore(tmp_path/'db.sqlite')
    with execution_guard(store):
        read_fd, write_fd=os.pipe(); pid=os.fork()
        if pid == 0:
            os.close(read_fd)
            try:
                with execution_guard(store): result=b'acquired'
            except WorkflowError: result=b'busy'
            os.write(write_fd,result); os._exit(0)
        os.close(write_fd)
        try: assert os.read(read_fd,20)==b'busy'
        finally: os.close(read_fd); os.waitpid(pid,0)
