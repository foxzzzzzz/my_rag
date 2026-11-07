import json
from types import SimpleNamespace
import pytest
from deploy import deploy as d
REAL_HEALTH = d.health

@pytest.fixture
def rig(tmp_path, monkeypatch):
    calls=[]
    old={'web': {'Image':'sha256:old','State':{'Status':'running'}}, 'worker': {'Image':'sha256:old','State':{'Status':'running'}}}
    state={'services':old, 'fail':None}
    monkeypatch.setattr(d,'fcntl',SimpleNamespace(LOCK_EX=1,LOCK_NB=2,flock=lambda *a:None))
    monkeypatch.setattr(d,'prepare',lambda root: ({'CONFIG_DIR':str(root)},state['services'],'https://example.org',8768,{'docker_timeout_seconds':15,'switch_timeout_seconds':180}))
    (tmp_path/'state/tmp').mkdir(parents=True)
    def run(args,**kw):
        calls.append(args)
        if args[1]=='build' and state['fail']=='build': raise RuntimeError('build failed')
        if args[1]=='run' and state['fail']=='candidate': raise RuntimeError('invalid config')
        return 'sha256:new' if args[1:3]==['image','inspect'] else ''
    def compose(env,*args,**kwargs):
        calls.append(list(args))
        if args[0]=='up' and state['fail']=='up':
            state['fail']=None; raise RuntimeError('up failed')
    def health(env,origin,port,image,settings):
        calls.append(['health',image])
        if image=='sha256:new' and state['fail']=='health': raise RuntimeError('health failed')
    monkeypatch.setattr(d,'run',run); monkeypatch.setattr(d,'compose',compose); monkeypatch.setattr(d,'health',health)
    return tmp_path,calls,state

def test_upgrade_retains_old_tag_and_switches(rig):
    root,calls,state=rig; d.deploy(root)
    assert calls.index(['docker','tag','sha256:old',d.ROLLBACK]) < calls.index(['docker','tag','sha256:new',d.IMAGE])
    assert ['up','-d','--no-build','--pull','never','--force-recreate','web','worker'] in calls
    assert calls[-1]==['health','sha256:new']

def test_first_deploy_and_failed_first_stops_only_services(rig):
    root,calls,state=rig; state['services']={}; state['fail']='health'
    with pytest.raises(d.DeployError): d.deploy(root)
    assert ['rm','-s','-f','web','worker'] in calls
    assert not any(d.ROLLBACK in c for c in calls)

def test_first_deploy_succeeds(rig):
    root,calls,state=rig; state['services']={}; d.deploy(root)
    assert calls[-1]==['health','sha256:new']
    assert not any(d.ROLLBACK in c for c in calls)

def test_build_failure_never_switches(rig):
    root,calls,state=rig; state['fail']='build'
    with pytest.raises(RuntimeError): d.deploy(root)
    assert not any('tag' in c or 'up' in c for c in calls)

def test_candidate_validation_failure_never_switches(rig):
    root,calls,state=rig; state['fail']='candidate'
    with pytest.raises(RuntimeError): d.deploy(root)
    assert not any('tag' in c or 'up' in c for c in calls)

def test_post_build_preflight_failure_never_switches(rig,monkeypatch):
    root,calls,state=rig
    count=0
    def prepare(root):
        nonlocal count
        count+=1
        if count==2: raise d.DeployError('Insufficient space')
        return {'CONFIG_DIR':str(root)},state['services'],'https://example.org',8768,{'docker_timeout_seconds':15,'switch_timeout_seconds':180}
    monkeypatch.setattr(d,'prepare',prepare)
    with pytest.raises(d.DeployError,match='Insufficient space'): d.deploy(root)
    assert not any('tag' in c or 'up' in c for c in calls)

def test_health_rejects_non_object(monkeypatch):
    class Response:
        status=200
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self): return b'[]'
    monkeypatch.setattr(d.urllib.request,'build_opener',lambda *args: SimpleNamespace(open=lambda *a,**kw:Response()))
    assert not d.url_ok('https://example.org/healthz',5)

@pytest.mark.parametrize('existing',['workflow/workflow.sqlite3','budget.sqlite'])
def test_first_install_rejects_partial_migration(tmp_path,existing):
    for directory in ('config','state/tmp','secrets','backups'):
        (tmp_path/directory).mkdir(parents=True)
    (tmp_path/'secrets/personalkb.env').touch()
    file=tmp_path/'state'/existing
    file.parent.mkdir(parents=True,exist_ok=True)
    file.touch()
    with pytest.raises(d.DeployError,match='both exist or both be absent'):
        d.prepare(tmp_path)

def test_interrupted_switch_restores_old_image(rig,monkeypatch):
    root,calls,state=rig
    def interrupted(env,*args,**kwargs):
        calls.append(list(args))
        if len([c for c in calls if c and c[0]=='up'])==1: raise KeyboardInterrupt()
    monkeypatch.setattr(d,'compose',interrupted)
    with pytest.raises(d.DeployError): d.deploy(root)
    assert ['docker','tag',d.ROLLBACK,d.IMAGE] in calls

@pytest.mark.parametrize('failure',['up','health'])
def test_failed_upgrade_restores_old_image(rig,failure):
    root,calls,state=rig; state['fail']=failure
    with pytest.raises(d.DeployError): d.deploy(root)
    assert ['docker','tag',d.ROLLBACK,d.IMAGE] in calls
    assert calls[-1]==['health','sha256:old']

def test_check_does_not_write(rig):
    root,calls,state=rig; d.deploy(root,check=True)
    assert not (root/'state/tmp/personalkb-deploy.lock').exists() and calls==[]

def test_rejects_wrong_mount_and_missing_database(tmp_path):
    dirs=d.paths(tmp_path)
    mounts=[{'Destination':target,'Source':str(path),'Type':'bind','RW':target not in ('/app/config','/run/secrets/personalkb.env')} for target,path in {'/state':dirs['STATE_DIR'],'/tmp':dirs['STATE_DIR']/ 'tmp','/app/tmp':dirs['STATE_DIR']/ 'tmp','/app/config':dirs['CONFIG_DIR'],'/run/secrets/personalkb.env':dirs['SECRET_FILE'],'/backups':dirs['BACKUP_DIR']}.items()]
    item={'State':{'Running':True,'Status':'running'},'Mounts':mounts,'Image':'sha256:old'}
    with pytest.raises(d.DeployError,match='ledger missing'): d.validate_mounts({'web':item,'worker':item},dirs)
    (dirs['STATE_DIR']/'workflow').mkdir(parents=True); (dirs['STATE_DIR']/'workflow/workflow.sqlite3').touch(); (dirs['STATE_DIR']/'budget.sqlite').touch()
    mounts[0]['Source']=str(tmp_path/'wrong')
    with pytest.raises(d.DeployError,match='mounts'): d.validate_mounts({'web':item,'worker':item},dirs)

def test_stopped_pair_allowed_but_restarting_rejected(tmp_path):
    dirs=d.paths(tmp_path)
    targets={'/state':dirs['STATE_DIR'],'/tmp':dirs['STATE_DIR']/'tmp','/app/tmp':dirs['STATE_DIR']/'tmp','/app/config':dirs['CONFIG_DIR'],'/run/secrets/personalkb.env':dirs['SECRET_FILE'],'/backups':dirs['BACKUP_DIR']}
    mounts=[{'Destination':target,'Source':str(path),'Type':'bind','RW':target not in ('/app/config','/run/secrets/personalkb.env')} for target,path in targets.items()]
    (dirs['STATE_DIR']/'workflow').mkdir(parents=True)
    (dirs['STATE_DIR']/'workflow/workflow.sqlite3').touch(); (dirs['STATE_DIR']/'budget.sqlite').touch()
    obj={'State':{'Status':'exited'},'Mounts':mounts,'Image':'old'}
    d.validate_mounts({'web':obj,'worker':obj},dirs)
    restarting={**obj,'State':{'Status':'restarting'}}
    with pytest.raises(d.DeployError): d.validate_mounts({'web':obj,'worker':restarting},dirs)

def test_empty_initialization_uses_real_empty_databases_and_is_idempotent(tmp_path):
    import sqlite3
    state=tmp_path/'state'; (state/'tmp').mkdir(parents=True)
    d.initialize_empty_state(state)
    with sqlite3.connect(state/'workflow/workflow.sqlite3') as db:
        assert db.execute('select count(*) from sources').fetchone()[0]==0
        db.execute("insert into sources(id,kind,sha256,original_name,blob_relpath) values('x','html','x','x','x')")
    with sqlite3.connect(state/'budget.sqlite') as db:
        assert db.execute('select count(*) from reservations').fetchone()[0]==0
    d.initialize_empty_state(state)
    with sqlite3.connect(state/'workflow/workflow.sqlite3') as db:
        assert db.execute('select count(*) from sources').fetchone()[0]==1

def test_initialization_partial_publish_cleans_own_file(tmp_path,monkeypatch):
    state=tmp_path/'state'; (state/'tmp').mkdir(parents=True)
    link=d.os.link; calls=[]
    def fail_second(src,dst):
        calls.append(dst)
        if len(calls)==2: raise OSError('failed')
        link(src,dst)
    monkeypatch.setattr(d.os,'link',fail_second)
    with pytest.raises(OSError): d.initialize_empty_state(state)
    assert not (state/'workflow/workflow.sqlite3').exists() and not (state/'budget.sqlite').exists()
    monkeypatch.setattr(d.os,'link',link)
    d.initialize_empty_state(state)
    assert (state/'budget.sqlite').is_file()

def test_first_failure_then_retry_preserves_initialized_databases(rig):
    root,calls,state=rig; state['services']={}; state['fail']='health'
    with pytest.raises(d.DeployError): d.deploy(root)
    db=root/'state/workflow/workflow.sqlite3'; ledger=root/'state/budget.sqlite'
    before=(db.read_bytes(),ledger.read_bytes())
    state['fail']=None; d.deploy(root)
    assert (db.read_bytes(),ledger.read_bytes())==before

def test_stopped_service_failure_restores_stopped_image(rig,monkeypatch):
    root,calls,state=rig
    for item in state['services'].values(): item['State']['Status']='exited'
    state['fail']='health'
    monkeypatch.setattr(d,'restore_stopped',lambda env,old,settings:calls.append(['restore-stopped',old]))
    with pytest.raises(d.DeployError): d.deploy(root)
    assert ['docker','tag',d.ROLLBACK,d.IMAGE] in calls
    assert calls[-1]==['restore-stopped','sha256:old']

@pytest.mark.parametrize('signum',[1,15])
def test_registered_signal_triggers_rollback_and_restores_handlers(rig,monkeypatch,signum):
    root,calls,state=rig; handlers={}; originals={1:'original-hup',15:'original-term'}
    monkeypatch.setattr(d.signal,'SIGHUP',1,raising=False)
    monkeypatch.setattr(d.signal,'SIGTERM',15)
    def register(sig,handler):
        previous=handlers.get(sig,originals[sig]); handlers[sig]=handler; return previous
    monkeypatch.setattr(d.signal,'signal',register)
    def health(env,origin,port,image,settings):
        calls.append(['health',image])
        if image=='sha256:new': handlers[signum](signum,None)
    monkeypatch.setattr(d,'health',health)
    with pytest.raises(d.DeployError): d.deploy(root)
    assert ['docker','tag',d.ROLLBACK,d.IMAGE] in calls
    assert handlers==originals

def test_restore_stopped_uses_no_start_and_verifies_images(monkeypatch):
    calls=[]
    monkeypatch.setattr(d,'compose',lambda env,*args,**kwargs:calls.append((args,kwargs)))
    services={name:{'Image':'old','State':{'Status':status}} for name,status in [('web','created'),('worker','exited')]}
    monkeypatch.setattr(d,'inspect_services',lambda *args,**kwargs:services)
    d.restore_stopped({},'old',{'switch_timeout_seconds':180,'docker_timeout_seconds':15})
    assert calls[0][0]==('up','--no-start','--no-build','--pull','never','--force-recreate','web','worker')
    assert not calls[0][1].get('stream',False)
    services['worker']['Image']='wrong'
    with pytest.raises(d.DeployError): d.restore_stopped({},'old',{'switch_timeout_seconds':180,'docker_timeout_seconds':15})

def test_interrupt_immediately_after_link_removes_only_own_files(tmp_path,monkeypatch):
    state=tmp_path/'state'; (state/'tmp').mkdir(parents=True)
    link=d.os.link
    def interrupted(src,dst):
        link(src,dst)
        raise KeyboardInterrupt()
    monkeypatch.setattr(d.os,'link',interrupted)
    with pytest.raises(KeyboardInterrupt): d.initialize_empty_state(state)
    assert not (state/'workflow/workflow.sqlite3').exists()
    assert not (state/'budget.sqlite').exists()

def test_real_prepare_accepts_initialized_unpaid_install_and_upgrade(tmp_path,monkeypatch):
    import json
    dirs=d.paths(tmp_path)
    for folder in (dirs['CONFIG_DIR'],dirs['STATE_DIR']/'tmp',dirs['SECRET_FILE'].parent,dirs['BACKUP_DIR']): folder.mkdir(parents=True)
    dirs['SECRET_FILE'].touch()
    (dirs['CONFIG_DIR']/'web.json').write_text(json.dumps({'trusted_origins':['https://example.org'],'trusted_hosts':['example.org'],'port':8768}),encoding='utf-8')
    (dirs['CONFIG_DIR']/'workflow.json').write_text(json.dumps({'data_dir':'/state/workflow','min_free_bytes':1}),encoding='utf-8')
    for file in dirs['CONFIG_DIR'].glob('*.json'): file.chmod(0o444)
    monkeypatch.setattr(d,'probe',lambda *a:{'system':'Linux','architecture':'x86_64','config_valid':True,'compose_available':True,'secret_file_exists':True,'auth_valid':True,'secret_permissions_private':True,'disk_free_bytes':1000,'port_available':True})
    monkeypatch.setattr(d,'compose',lambda *a,**kw:'')
    monkeypatch.setattr(d,'health',lambda *a:None)
    services={}
    monkeypatch.setattr(d,'inspect_services',lambda *a,**kw:services)
    d.initialize_empty_state(dirs['STATE_DIR'])
    assert d.prepare(tmp_path)[1]=={}
    targets={'/state':dirs['STATE_DIR'],'/tmp':dirs['STATE_DIR']/'tmp','/app/tmp':dirs['STATE_DIR']/'tmp','/app/config':dirs['CONFIG_DIR'],'/run/secrets/personalkb.env':dirs['SECRET_FILE'],'/backups':dirs['BACKUP_DIR']}
    mounts=[{'Destination':target,'Source':str(path),'Type':'bind','RW':target not in ('/app/config','/run/secrets/personalkb.env')} for target,path in targets.items()]
    services.update({name:{'Image':'old','State':{'Status':'running'},'Mounts':mounts} for name in ('web','worker')})
    assert len(d.prepare(tmp_path)[1])==2
    import sqlite3
    with sqlite3.connect(dirs['STATE_DIR']/'budget.sqlite') as conn:
        assert conn.execute('select count(*) from reservations').fetchone()[0]==0

def test_real_health_propagates_registered_signal_and_rolls_back(rig,monkeypatch):
    root,calls,state=rig
    handlers={}
    monkeypatch.setattr(d.signal,'SIGHUP',1,raising=False)
    monkeypatch.setattr(d.signal,'SIGTERM',15)
    def register(sig,handler):
        old=handlers.get(sig,None); handlers[sig]=handler; return old
    monkeypatch.setattr(d.signal,'signal',register)
    settings={'docker_timeout_seconds':15,'switch_timeout_seconds':180,'health_timeout_seconds':5,'health_interval_seconds':0.01,'request_timeout_seconds':1}
    monkeypatch.setattr(d,'prepare',lambda root:({'CONFIG_DIR':str(root)},state['services'],'https://example.org',8768,settings))
    current={'image':'sha256:new','first':True}
    def inspect(*args,**kwargs):
        return {name:{'Image':current['image'],'State':{'Status':'running'}} for name in ('web','worker')}
    def url(*args,**kwargs):
        if current['first']:
            current['first']=False
            current['image']='sha256:old'
            handlers[15](15,None)
        return True
    monkeypatch.setattr(d,'health',REAL_HEALTH)
    monkeypatch.setattr(d,'inspect_services',inspect)
    monkeypatch.setattr(d,'url_ok',url)
    with pytest.raises(d.DeployError,match='previous service restored'): d.deploy(root)
    assert ['docker','tag',d.ROLLBACK,d.IMAGE] in calls

def test_repeated_signal_during_rollback_is_latched(rig,monkeypatch):
    root,calls,state=rig
    handlers={}; repeated=[]
    monkeypatch.setattr(d.signal,'SIGHUP',1,raising=False)
    monkeypatch.setattr(d.signal,'SIGTERM',15)
    def register(sig,handler):
        old=handlers.get(sig,None)
        if handler is d.signal.SIG_IGN and callable(old):
            old(sig,None)
            repeated.append(sig)
        handlers[sig]=handler
        return old
    monkeypatch.setattr(d.signal,'signal',register)
    def health(env,origin,port,image,settings):
        calls.append(['health',image])
        if image=='sha256:new': handlers[15](15,None)
    monkeypatch.setattr(d,'health',health)
    with pytest.raises(d.DeployError): d.deploy(root)
    assert repeated==[1,15]
    assert calls.count(['docker','tag',d.ROLLBACK,d.IMAGE])==1
    assert calls.count(['health','sha256:old'])==1
