import json, sqlite3, unicodedata, uuid
from pathlib import Path
from .workflow_store import WorkflowError


def snapshot_from_connection(c, sid):
    row=c.execute('SELECT revision FROM source_metadata WHERE source_id=?',(sid,)).fetchone()
    result={'revision':row[0] if row else 0,'topics':[],'tags':[]}
    for r in c.execute('SELECT l.id,l.name,l.kind FROM classification_labels l JOIN source_labels s ON s.label_id=l.id WHERE s.source_id=? ORDER BY l.name,l.id',(sid,)):
        result['topics' if r[2]=='topic' else 'tags'].append({'id':r[0],'name':r[1]})
    return result

def load_classification_config(path=None):
    try:
        cfg=json.loads(Path(path or Path(__file__).resolve().parent.parent/'config/classification.json').read_text(encoding='utf-8-sig'))
        for key in ('max_name_length','max_aliases','max_labels_per_kind','max_bulk_items'):
            if type(cfg[key]) is not int or cfg[key] <= 0: raise ValueError()
        return cfg
    except (OSError,ValueError,KeyError,TypeError): raise WorkflowError('invalid_config') from None

class ClassificationStore:
    def __init__(self, store, config=None):
        self.store=store
        self.config=config if config is not None else load_classification_config()
        with store._tx() as c:
            c.execute('CREATE TABLE IF NOT EXISTS classification_labels (id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, revision INTEGER NOT NULL)')
            c.execute('CREATE TABLE IF NOT EXISTS classification_names (kind TEXT NOT NULL, normalized TEXT NOT NULL, label_id TEXT NOT NULL, name TEXT NOT NULL, is_alias INTEGER NOT NULL, PRIMARY KEY(kind,normalized))')
            c.execute('CREATE TABLE IF NOT EXISTS source_metadata (source_id TEXT PRIMARY KEY, revision INTEGER NOT NULL)')
            c.execute('CREATE TABLE IF NOT EXISTS source_labels (source_id TEXT NOT NULL, label_id TEXT NOT NULL, PRIMARY KEY(source_id,label_id))')
    def _names(self,name,aliases):
        if not isinstance(aliases,list) or len(aliases)>self.config['max_aliases']: raise WorkflowError('invalid_classification')
        values=[name]+aliases; out=[]
        for x in values:
            if not isinstance(x,str): raise WorkflowError('invalid_classification')
            x=' '.join(unicodedata.normalize('NFKC',x).split())
            if not x or len(x)>self.config['max_name_length'] or any(ord(ch)<32 for ch in x): raise WorkflowError('invalid_classification')
            out.append((x,x.casefold()))
        if len({x[1] for x in out})!=len(out): raise WorkflowError('classification_duplicate')
        return out
    def _label(self,c,id):
        r=c.execute('SELECT * FROM classification_labels WHERE id=?',(id,)).fetchone()
        if not r: raise WorkflowError('classification_not_found')
        d=dict(r); d['aliases']=[x[0] for x in c.execute('SELECT name FROM classification_names WHERE label_id=? AND is_alias=1 ORDER BY name',(id,))]; return d
    def catalog(self):
        with self.store._tx() as c: return [self._label(c,r[0]) for r in c.execute('SELECT id FROM classification_labels ORDER BY kind,name,id').fetchall()]
    def create_label(self,kind,name,aliases=None):
        if kind not in ('topic','tag'): raise WorkflowError('invalid_classification')
        names=self._names(name,aliases if aliases is not None else []); id=uuid.uuid4().hex
        try:
            with self.store._tx() as c:
                c.execute('INSERT INTO classification_labels VALUES(?,?,?,1)',(id,kind,names[0][0]))
                c.executemany('INSERT INTO classification_names VALUES(?,?,?,?,?)',[(kind,n,id,x,i>0) for i,(x,n) in enumerate(names)])
                return self._label(c,id)
        except sqlite3.IntegrityError: raise WorkflowError('classification_duplicate') from None
    def _sync(self,ids):
        if self.store.content_root:
            for sid in ids:
                try: self.store.sync_source(sid)
                except Exception: pass
    def update_label(self,id,expected_revision,name,aliases):
        names=self._names(name,aliases)
        try:
            with self.store._tx() as c:
                old=self._label(c,id)
                if type(expected_revision) is not int or old['revision']!=expected_revision: raise WorkflowError('classification_conflict')
                c.execute('DELETE FROM classification_names WHERE label_id=?',(id,))
                c.executemany('INSERT INTO classification_names VALUES(?,?,?,?,?)',[(old['kind'],n,id,x,i>0) for i,(x,n) in enumerate(names)])
                c.execute('UPDATE classification_labels SET name=?,revision=revision+1 WHERE id=?',(names[0][0],id))
                ids=[r[0] for r in c.execute('SELECT source_id FROM source_labels WHERE label_id=?',(id,))]
                for sid in ids:
                    c.execute('INSERT INTO source_metadata VALUES(?,1) ON CONFLICT(source_id) DO UPDATE SET revision=revision+1',(sid,))
                    c.execute('UPDATE content_sync SET generation=generation+1 WHERE source_id=?',(sid,))
                result=self._label(c,id)
        except sqlite3.IntegrityError: raise WorkflowError('classification_duplicate') from None
        self._sync(ids); return result
    def snapshot(self,source_id,connection=None):
        if connection is not None: return snapshot_from_connection(connection,source_id)
        with self.store._tx() as c:
            self.store._row(c,'sources',source_id); return snapshot_from_connection(c,source_id)
    def update_in_transaction(self,c,sid,expected_revision,topics,tags):
        s=self.store._row(c,'sources',sid)
        if s['deleted']: raise WorkflowError('source_deleted')
        current=snapshot_from_connection(c,sid)
        if type(expected_revision) is not int or current['revision']!=expected_revision: raise WorkflowError('classification_conflict')
        for kind,ids in [('topic',topics),('tag',tags)]:
            if not isinstance(ids,list) or len(ids)>self.config['max_labels_per_kind'] or any(not isinstance(x,str) for x in ids) or len(set(ids))!=len(ids): raise WorkflowError('invalid_classification')
            for id in ids:
                r=c.execute('SELECT kind FROM classification_labels WHERE id=?',(id,)).fetchone()
                if not r or r[0]!=kind: raise WorkflowError('classification_not_found')
        if set(topics)=={x['id'] for x in current['topics']} and set(tags)=={x['id'] for x in current['tags']}: return current
        c.execute('DELETE FROM source_labels WHERE source_id=?',(sid,))
        c.executemany('INSERT INTO source_labels VALUES(?,?)',[(sid,x) for x in topics+tags])
        c.execute('INSERT INTO source_metadata VALUES(?,1) ON CONFLICT(source_id) DO UPDATE SET revision=revision+1',(sid,))
        c.execute('UPDATE content_sync SET generation=generation+1 WHERE source_id=?',(sid,))
        return snapshot_from_connection(c,sid)
    def update(self,source_id,expected_revision,topics,tags):
        with self.store._tx() as c: result=self.update_in_transaction(c,source_id,expected_revision,topics,tags)
        self._sync([source_id]); return result
    def bulk(self,items,operation='add',topics=None,tags=None):
        if not isinstance(items,list) or len(items)>self.config['max_bulk_items'] or operation not in ('add','remove','replace'): raise WorkflowError('invalid_classification')
        topics=[] if topics is None else topics; tags=[] if tags is None else tags; results=[]
        for item in items:
            try:
                if not isinstance(item,dict) or not isinstance(item.get('source_id'),str) or not item['source_id'].strip() or type(item.get('expected_revision')) is not int: raise WorkflowError('invalid_classification')
                sid=item['source_id']
                with self.store._tx() as c:
                    old=snapshot_from_connection(c,sid)
                    for kind, supplied in (('topic',topics),('tag',tags)):
                        if not isinstance(supplied,list) or len(supplied)>self.config['max_labels_per_kind'] or any(not isinstance(x,str) for x in supplied) or len(set(supplied)) != len(supplied): raise WorkflowError('invalid_classification')
                        for label_id in supplied:
                            row=c.execute('SELECT kind FROM classification_labels WHERE id=?',(label_id,)).fetchone()
                            if not row or row[0] != kind: raise WorkflowError('classification_not_found')
                    def combine(key,new):
                        if not isinstance(new,list): raise WorkflowError('invalid_classification')
                        prior=[x['id'] for x in old[key]]
                        return list(dict.fromkeys(prior+new)) if operation=='add' else [x for x in prior if x not in new] if operation=='remove' else new
                    result=self.update_in_transaction(c,sid,item['expected_revision'],combine('topics',topics),combine('tags',tags))
                self._sync([sid]); results.append({'source_id':sid,'status':'success','classification':result})
            except (WorkflowError,KeyError,TypeError) as e: results.append({'source_id':item.get('source_id') if isinstance(item,dict) else None,'status':e.code if isinstance(e,WorkflowError) else 'invalid_classification'})
        return results
