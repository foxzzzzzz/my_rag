"""Offline real sqlite-vec benchmark with an explicitly synthetic load extension."""
import argparse,hashlib,json,math,os,platform,random,sqlite3,sys,time,threading,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def load(p):return json.loads(Path(p).read_text(encoding='utf8'))
def digest(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def percentile(values,p):
 values=sorted(values)
 return values[max(0,math.ceil(len(values)*p)-1)]
def stats(values):return {'count':len(values),'p50_ms':percentile(values,.5),'p95_ms':percentile(values,.95),'max_ms':max(values)}

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',default=str(ROOT/'config/index-benchmark.json'));args=parser.parse_args();c=load(args.config)
 sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/c['dependencies']))
 import psutil,sqlite_vec
 from tools.sqlite_index import SQLiteIndex
 from tools.retrieval_trial import dense
 base=ROOT/c['base_directory'];parts=load(base/'chunks.json')['heading'];index=load(base/'index-m0-heading.json');vectors=index['vectors']
 if index['chunks_hash']!=digest(parts) or index['model']['dimensions']!=c['dimensions']:raise RuntimeError('input_changed')
 dense(parts,vectors,vectors[0],1)
 queries=load(base/'report.json')['questions'];qvectors=[]
 for f in sorted((base/'stages').glob('m0-queries-*.json')):
  data=load(f);qvectors.extend(row['embedding'] for row in sorted(data['data'],key=lambda x:x['index']))
 if len(qvectors)!=len(queries) or any(len(v)!=c['dimensions'] for v in qvectors):raise RuntimeError('query_mismatch')
 out=ROOT/c['output'];out.mkdir(exist_ok=True);dbfile=out/'benchmark.sqlite'
 if dbfile.exists() or (out/'report.json').exists():raise RuntimeError('benchmark_output_exists')
 proc=psutil.Process();baseline_rss=proc.memory_info().rss;peak=[baseline_rss];stop=threading.Event()
 def sample():
  while not stop.wait(c['rss_interval_seconds']):peak[0]=max(peak[0],proc.memory_info().rss)
 thread=threading.Thread(target=sample,daemon=True);thread.start();db=None
 try:
  db=SQLiteIndex(str(dbfile),c['dimensions']);db.db.execute('PRAGMA journal_mode=WAL');db.db.execute('PRAGMA synchronous=NORMAL');db.db.execute('PRAGMA cache_size=?'.replace('?',str(-c['cache_kib'])))
  rand=random.Random(c['seed']);tick=time.perf_counter();db.db.execute('BEGIN')
  for i in range(c['rows']):
   j=i%len(parts);v=vectors[j]
   if i>=len(parts):
    v=[n+rand.uniform(-c['jitter'],c['jitter']) for n in v];norm=math.sqrt(sum(n*n for n in v));v=[n/norm for n in v]
   db.upsert(i+1,parts[j]['item_id'],parts[j]['text'],v)
  db.db.commit();build_seconds=time.perf_counter()-tick
  counts=[db.db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ('docs','docs_fts','embeddings')]
  if counts!=[c['rows']]*3:raise RuntimeError('store_counts')
  # Compare exact native distance on the real 128 vectors, excluding synthetic rows.
  reference=dense(parts,vectors,qvectors[0],c['top_k']);actual=db.db.execute('SELECT id,vec_distance_cosine(vector,?) d FROM embeddings WHERE id<=? ORDER BY d LIMIT ?', (db._vector(qvectors[0]),len(parts),c['top_k'])).fetchall()
  expected_distances=sorted(1-x['score'] for x in reference)
  if any(abs(a[1]-b)>1e-5 for a,b in zip(actual,expected_distances)):raise RuntimeError('native_cosine_mismatch')
  methods={'lexical':lambda d,q,v:d.search_lexical(q,c['top_k']),'vector':lambda d,q,v:d.search_vector(v,c['top_k']),'hybrid':lambda d,q,v:d.search_hybrid(q,v,c['top_k'],c['rrf_constant'])}
  warm={};fresh={}
  for name,fn in methods.items():
   for i in range(c['warmups']):fn(db,queries[i%len(queries)]['question'],qvectors[i%len(queries)])
   samples=[]
   for i in range(c['timed_queries']):
    j=i%len(queries);t=time.perf_counter();hits=fn(db,queries[j]['question'],qvectors[j]);samples.append((time.perf_counter()-t)*1000)
    if not hits:raise RuntimeError('empty_benchmark_result')
   warm[name]=stats(samples);samples=[]
   for i in range(c['cold_queries']):
    freshdb=SQLiteIndex(str(dbfile),c['dimensions'])
    try:
     t=time.perf_counter();fn(freshdb,queries[i%len(queries)]['question'],qvectors[i%len(queries)]);samples.append((time.perf_counter()-t)*1000)
    finally:freshdb.close()
   fresh[name]=stats(samples)
  # Transactional cross-store updates, deletes, and caller rollback on a separate probe row.
  probe_id=c['rows']+1;marker='probeuniquemarker';db.upsert(probe_id,'probe',marker,vectors[0]);assert db.search_lexical(marker,1)[0]['id']==probe_id
  db.upsert(probe_id,'probe','updateduniquemarker',vectors[1]);assert not db.search_lexical(marker,1);assert db.search_lexical('updateduniquemarker',1)[0]['id']==probe_id
  db.db.execute('BEGIN');db.delete(probe_id);db.db.rollback();assert db.search_lexical('updateduniquemarker',1)[0]['id']==probe_id
  db.delete(probe_id);assert not db.search_lexical('updateduniquemarker',1)
  counts_after=[db.db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ('docs','docs_fts','embeddings')];assert counts_after==counts
  # Constrained-source scalar distance correctness; this path is distinct from global vec0 KNN.
  selected=parts[0]['item_id'];filtered=db.db.execute('SELECT d.id,d.source,vec_distance_cosine(e.vector,?) distance FROM docs d JOIN embeddings e ON e.id=d.id WHERE d.source=? ORDER BY distance LIMIT ?', (db._vector(qvectors[0]),selected,c['top_k'])).fetchall();assert filtered and all(x[1]==selected for x in filtered)
  extension_version=db.db.execute('SELECT vec_version()').fetchone()[0];db.db.execute('PRAGMA wal_checkpoint(TRUNCATE)');db.close();db=None
  peak[0]=max(peak[0],proc.memory_info().rss)
  result={'scope':'local_offline_synthetic_load_not_target_server_acceptance','environment':{'os':platform.platform(),'python':platform.python_version(),'sqlite':sqlite3.sqlite_version,'sqlite_vec':extension_version,'logical_cpus':os.cpu_count(),'host_memory_bytes':psutil.virtual_memory().total},'rows':c['rows'],'dimensions':c['dimensions'],'real_seed_rows':len(parts),'synthetic_rows':c['rows']-len(parts),'model':index['model'],'chunks_hash':index['chunks_hash'],'build_seconds':build_seconds,'database_bytes':dbfile.stat().st_size,'process_baseline_rss_bytes':baseline_rss,'sampled_process_peak_rss_bytes':peak[0],'warm_queries':warm,'fresh_connection_queries':fresh,'fresh_connection_note':'New DB connection, timer excludes extension loading; OS filesystem cache is NOT cleared.','correctness':{'counts':counts,'cosine_tolerance_1e5':True,'update_delete_rollback':True,'constrained_source_filter':True},'local_latency_pass':all(x['p95_ms']<=c['p95_limit_ms'] for x in list(warm.values())+list(fresh.values())),'target_server_pass':None,'config':c}
  (out/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(result,ensure_ascii=True))
 finally:
  if db is not None:db.close()
  stop.set();thread.join()

if __name__=='__main__':main()
