from test_web_api import WebApiTests

class ClassificationApiTests(WebApiTests):
    def test_topic_required_api_and_bulk_partial(self):
        client,h=self.client,self.h
        sid,_=self.make_version()
        tag=client.post('/api/classifications',json={'kind':'tag','name':'标签'},headers=h).json()['id']
        topic=client.post('/api/classifications',json={'kind':'topic','name':'主题'},headers=h).json()['id']
        result=client.post('/api/sources/'+sid+'/classification',json={'expected_revision':0,'topics':[],'tags':[tag]},headers=h)
        self.assertEqual(result.json()['error'],'classification_topic_required')
        client.post('/api/sources/'+sid+'/classification',json={'expected_revision':0,'topics':[topic],'tags':[]},headers=h)
        bulk=client.post('/api/classifications/bulk',json={'items':[{'source_id':sid,'expected_revision':1},{'source_id':sid,'expected_revision':0}],'operation':'add','tags':[tag]},headers=h).json()
        self.assertEqual([x['status'] for x in bulk['items']],['success','classification_conflict'])
        bulk=client.post('/api/classifications/bulk',json={'items':[{'source_id':sid,'expected_revision':2}],'operation':'remove','topics':[topic]},headers=h).json()
        self.assertEqual(bulk['items'][0]['status'],'classification_topic_required')
    def test_classification_api_filters_bulk_and_security(self):
        client,h=self.client,self.h
        sid,v=self.make_version()
        self.assertEqual(client.post('/api/classifications',json={'kind':'topic','name':'主题'}).status_code,403)
        created=client.post('/api/classifications',json={'kind':'topic','name':'主题','aliases':['别名']},headers=h)
        self.assertEqual(created.status_code,200); label=created.json()
        self.assertIn('default-src',created.headers['content-security-policy'])
        revised=client.post('/api/sources/'+sid+'/revisions',json={'expected_version_id':v['id'],'title':'Distinctive Title'},headers=h).json()
        v['id']=revised['id']
        self.assertEqual(client.get('/api/sources',params={'q':'Distinctive'}).json()['items'][0]['title'],'Distinctive Title')
        result=client.post('/api/sources/'+sid+'/classification',json={'expected_revision':0,'topics':[label['id']],'tags':[]},headers=h)
        self.assertEqual(result.json()['revision'],1)
        self.assertEqual(client.get('/api/sources',params={'topics':label['id'],'reviews':'pending','q':'review'}).json()['items'][0]['id'],sid)
        self.assertEqual(client.get('/api/sources',params={'topics':'missing'}).json()['items'],[])
        bulk=client.post('/api/classifications/bulk',json={'items':[{'source_id':sid,'expected_revision':1},{'source_id':sid,'expected_revision':1}],'operation':'remove','topics':[label['id']]},headers=h).json()
        self.assertEqual([x['status'] for x in bulk['items']],['success','classification_conflict'])
        detail=client.get('/api/sources/'+sid).json()
        self.assertEqual(detail['current']['id'],v['id']); self.assertIsNone(detail['review']); self.assertEqual(self.calls,[])
