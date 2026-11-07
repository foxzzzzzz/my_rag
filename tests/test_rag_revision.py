import unittest
from personalkb.web_service import WebService
class Store:
 def __init__(self): self.old={'body':'旧正文','transcript':'旧转录','visual':'旧画面','evidence':[{'type':'audio','text':'旧转录','start':1,'end':2},{'type':'visual','text':'旧画面','seconds':3}]};self.result=None
 def get_source(self,id): return {'current_version_id':'v1'}
 def get_version(self,id): return {'result':self.old}
 def revise(self,id,expected,result):
  self.result=result
  return {'id':'v2','source_id':id,'content_sha256':'sha','output_kind':'human_edited','parent_version_id':'v1','created_at':'now'}
class RevisionTests(unittest.TestCase):
 def setUp(self): self.s=WebService.__new__(WebService);self.s.store=Store()
 def test_body_replaces_all_evidence_and_parent_untouched(self):
  self.s.revise('s',{'expected_version_id':'v1','body':'修正正文'})
  self.assertEqual(self.s.store.result['evidence'],[{'type':'human_body','locator':'human-edit:body','text':'修正正文'}]);self.assertEqual(len(self.s.store.old['evidence']),2)
 def test_transcript_replaces_only_audio_without_time(self):
  self.s.revise('s',{'expected_version_id':'v1','transcript':'修正转录'})
  evidence=self.s.store.result['evidence'];self.assertEqual(evidence[0]['type'],'visual');self.assertEqual(evidence[1],{'type':'human_transcript','locator':'human-edit:transcript','text':'修正转录'})
 def test_summary_preserves_evidence(self):
  self.s.revise('s',{'expected_version_id':'v1','summary':'摘要'});self.assertEqual(self.s.store.result['evidence'],self.s.store.old['evidence'])
