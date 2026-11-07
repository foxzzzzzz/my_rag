import tempfile, unittest
from pathlib import Path
from personalkb.workflow_store import WorkflowStore, WorkflowError
from personalkb.classification import ClassificationStore

class ClassificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.store=WorkflowStore(Path(self.tmp.name)/'db')
        self.s=self.store.import_source('html','a'*64,'a','originals/a')['source']['id']
        self.c=ClassificationStore(self.store)
    def tearDown(self): self.tmp.cleanup()
    def test_bulk_invalid_item_does_not_abort(self):
        label=self.c.create_label('topic','Topic')
        result=self.c.bulk([{'source_id':self.s,'expected_revision':0}, {'source_id':[],'expected_revision':0}, {'source_id':self.s,'expected_revision':1}], 'add', [label['id']], [])
        self.assertEqual([r['status'] for r in result],['success','invalid_classification','success'])

    def test_normalization_cas_rename_and_bulk(self):
        label=self.c.create_label('topic','  Ａ  ',['别名'])
        with self.assertRaises(WorkflowError): self.c.create_label('topic','a')
        tag=self.c.create_label('tag','a')
        snap=self.c.update(self.s,0,[label['id']],[tag['id']]); self.assertEqual(snap['revision'],1)
        with self.assertRaises(WorkflowError): self.c.update(self.s,0,[],[])
        renamed=self.c.update_label(label['id'],1,'新名',[]); self.assertEqual(renamed['id'],label['id'])
        snap=self.c.snapshot(self.s); self.assertEqual(snap['revision'],2); self.assertEqual(snap['topics'][0]['name'],'新名')
        batch=self.c.bulk([{'source_id':self.s,'expected_revision':2},{'source_id':self.s,'expected_revision':2}], 'remove', [label['id']], [])
        self.assertEqual([x['status'] for x in batch],['success','classification_conflict'])
        with self.store._tx() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM reviews').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM versions').fetchone()[0],0)
            self.assertGreater(c.execute('SELECT generation FROM content_sync WHERE source_id=?',(self.s,)).fetchone()[0],1)

if __name__=='__main__': unittest.main()
