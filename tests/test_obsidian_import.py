import io, json, zipfile, stat, hashlib
import pytest
from personalkb.workflow import load_config
from personalkb.workflow_store import WorkflowError
from personalkb.obsidian import ObsidianService

@pytest.fixture
def setup(tmp_path):
 c=load_config(); c['data_dir']=str(tmp_path); s=ObsidianService(c)
 x=s.store.import_source('html','a'*64,'a','originals/a'); sid=x['source']['id']; t=s.store.claim_specific(x['task']['id'],'test')
 r=dict(title='Title',body='Body',summary='Summary',notes='Notes',scheme_id='s',scheme_version='1',output_kind='machine_initial',provenance='local_extraction',evidence=[{'text':'proof'}])
 v=s.store.finish(t['id'],t['lease_token'],r); s.store.review(sid,v['id'],v['content_sha256'],99,'approve','me')
 return s,sid,v

def edit(data,old,new): return data.replace(old.encode(),new.encode())
def preview(s,data): return s.preview(data,'note.md')['preview_id']
def error(code, f):
 with pytest.raises(WorkflowError) as ex: f()
 assert ex.value.code==code

def test_preview_and_apply(setup):
 s,sid,v=setup; data,_=s.export_note(sid); p=preview(s,edit(data,'Notes','Changed'))
 assert s.store.get_source(sid)['current_version_id']==v['id']
 r=s.apply(p,'use_uploaded'); new=s.store.get_version(r['version_id'])
 assert new['output_kind']=='human_edited' and new['result']['notes']=='Changed' and r['review_required']
 with s.store._tx() as c: assert c.execute('select count(*) from reviews where version_id=?',(new['id'],)).fetchone()[0]==0 and c.execute('select count(*) from reviews where version_id=?',(v['id'],)).fetchone()[0]==1
 assert s.apply(p,'use_uploaded')==r
 error('preview_conflict',lambda:s.apply(p,'keep_server'))

def test_unchanged_and_keep(setup):
 s,sid,v=setup; data,_=s.export_note(sid)
 assert not s.apply(preview(s,data),'use_uploaded')['changed']
 assert not s.apply(preview(s,edit(data,'Notes','Changed')),'keep_server')['changed']
 assert len(s.store.list_versions(sid))==1

def test_metadata_only(setup):
 s,sid,v=setup; label=s.classification.create_label('topic','topic'); data,_=s.export_note(sid)
 data=edit(data,'topic_ids: []','topic_ids: ["'+label['id']+'"]')
 r=s.apply(preview(s,data),'use_uploaded'); assert r['classification_changed'] and not r['content_changed'] and len(s.store.list_versions(sid))==1

def test_stale_and_concurrent(setup):
 s,sid,v=setup; data,_=s.export_note(sid); r=dict(v['result'],notes='Server',output_kind='human_edited',provenance='human_edited')
 s.store.revise(sid,v['id'],r); p=s.preview(edit(data,'Notes','Upload'),'note.md'); assert p['conflict']
 assert s.apply(p['preview_id'],'use_uploaded')['content_changed']
 data,_=s.export_note(sid); p=preview(s,edit(data,'Upload','Next')); current=s.store.get_version(s.store.get_source(sid)['current_version_id'])
 s.store.revise(sid,current['id'],dict(current['result'],notes='Concurrent'))
 error('version_conflict',lambda:s.apply(p,'use_uploaded'))

def test_metadata_concurrency(setup):
 s,sid,v=setup; data,_=s.export_note(sid); p=preview(s,data); label=s.classification.create_label('topic','topic'); s.classification.update(sid,0,[label['id']],[])
 error('classification_conflict',lambda:s.apply(p,'use_uploaded'))

def test_expired_deleted(setup):
 s,sid,v=setup; data,_=s.export_note(sid); p=preview(s,data)
 with s.store._tx() as c: c.execute('update obsidian_previews set expires_at=0 where id=?',(p,))
 error('preview_expired',lambda:s.apply(p,'use_uploaded'))
 p=preview(s,data); s.store.delete_source(sid); error('source_deleted',lambda:s.apply(p,'use_uploaded'))

def pack(files):
 b=io.BytesIO()
 with zipfile.ZipFile(b,'w') as z:
  for name,data in files: z.writestr(name,data)
 return b.getvalue()

def test_official_zip_and_anchor(setup):
 s,sid,v=setup; data,_=s.export_zip(sid); s.preview(data,'x.zip')
 with zipfile.ZipFile(io.BytesIO(data)) as z: files={n:z.read(n) for n in z.namelist()}
 files['evidence.json']=b'forged'; m=json.loads(files['manifest.json']); m['files']['evidence.json']=hashlib.sha256(b'forged').hexdigest(); files['manifest.json']=json.dumps(m).encode()
 error('attachment_integrity',lambda:s.preview(pack(files.items()),'x.zip'))

@pytest.mark.parametrize('members',[[('../x',b'x')],[('/x',b'x')],[('a',b'x'),('A',b'x')]])
def test_unsafe_zip(setup,members):
 s,_,_=setup; error('unsafe_zip',lambda:s.preview(pack(members),'x.zip'))

def test_symlink_and_limits(setup):
 s,_,_=setup; info=zipfile.ZipInfo('link'); info.create_system=3; info.external_attr=(stat.S_IFLNK|0o777)<<16
 error('unsafe_zip',lambda:s.preview(pack([(info,b'x')]),'x.zip'))
 s.config=dict(s.config,max_uncompressed_bytes=3); error('zip_limits',lambda:s.preview(pack([('x',b'1234')]),'x.zip'))

def test_score_property_ignored(setup):
 s,sid,v=setup; data,_=s.export_note(sid); data=data.replace(b'---\n\n',b'review_status: "approved"\n---\n\n',1); data=edit(data,'Notes','changed')
 r=s.apply(preview(s,data),'use_uploaded'); assert r['review_required']

def test_crlf_noop_preserves_approval(setup):
 s,sid,v=setup
 updated=s.store.revise(sid,v['id'],dict(v['result'],notes='A\r\nB',output_kind='human_edited',provenance='human_edited'))
 s.store.review(sid,updated['id'],updated['content_sha256'],99,'approve','reviewer')
 data,_=s.export_note(sid); receipt=s.apply(preview(s,data),'use_uploaded')
 assert not receipt['changed'] and receipt['version_id']==updated['id']
 with s.store._tx() as c: assert c.execute("select count(*) from reviews where version_id=? and decision='approve'",(updated['id'],)).fetchone()[0]==1

def test_plain_title_block_list_and_yaml_tags_rejected(setup):
 s,sid,v=setup; label=s.classification.create_label('topic','topic'); data,_=s.export_note(sid)
 data=edit(data,'title: "Title"','title: Title'); data=edit(data,'topic_ids: []','topic_ids:\n  - '+label['id'])
 p=s.preview(data,'note.md'); assert p['incoming']['title']=='Title' and p['incoming']['classification']['topics'][0]['id']==label['id']
 receipt=s.apply(p['preview_id'],'use_uploaded'); assert receipt['classification_changed']
 error('invalid_obsidian_note',lambda:s.preview(edit(data,'title: Title','title: !!python/object/apply:os.system'), 'note.md'))

def test_classification_stale_separately_reported(setup):
 s,sid,v=setup; data,_=s.export_note(sid); label=s.classification.create_label('topic','topic'); s.classification.update(sid,0,[label['id']],[])
 p=s.preview(data,'note.md')
 assert p['conflict'] and not p['content_conflict'] and p['classification_conflict']
 assert p['incoming_metadata_revision']==0 and p['current_metadata_revision']==1

def test_tag_only_import_rolls_back_content(setup):
 s,sid,v=setup; tag=s.classification.create_label('tag','tag'); data,_=s.export_note(sid)
 data=edit(edit(data,'Notes','Changed'),'tag_ids: []','tag_ids: ["'+tag['id']+'"]')
 p=preview(s,data)
 error('classification_topic_required',lambda:s.apply(p,'use_uploaded'))
 assert s.store.get_source(sid)['current_version_id']==v['id']
 assert len(s.store.list_versions(sid))==1
 assert s.classification.snapshot(sid)['tags']==[]
