import React,{useEffect,useState,useRef} from 'react';
import './citation-display.css';
import './rag.css';
import {guardedJson} from './auth-client';
import {displayAnswer,locationText,config} from './citation-display';
import {parseSSE,applyEvent,errorText} from './rag-helpers';
import {sourceSignature,isCurrentRequest,availableSources,unavailableSourceIds} from './rag-state';

const allFilters={sources:[],topics:[],tags:[]};

export function RagPanel({onLoginRequired,api,sources,catalog,session,connected=true,active=true,reviewEpoch=0,reviewPending=false}) {
 const [status,S]=useState(null),[question,Q]=useState(''),[mode,M]=useState('hybrid'),[paid,P]=useState(false),[result,R]=useState({}),[candidates,G]=useState(null),[citation,C]=useState(null),[error,E]=useState(''),[busy,B]=useState(false);
 const [scopeMode,setScopeMode]=useState('all');
 const [customFilters,setCustomFilters]=useState(allFilters);
 const [sourceSearch,setSourceSearch]=useState('');
 const [statusFailed,SetStatusFailed]=useState(false), [indexPaid,SetIndexPaid]=useState(false), [indexBusy,SetIndexBusy]=useState(false);
 const statusPollInterval=session.config.rag_status_poll_interval_ms ?? session.config.poll_interval_ms;
 const statusGeneration=useRef(0);
 const requestGeneration=useRef(0), citationGeneration=useRef(0), validationGeneration=useRef(0), readerRef=useRef(null), abortRef=useRef(null);
 useEffect(()=>()=>{requestGeneration.current++; abortRef.current?.abort(); readerRef.current?.cancel().catch(()=>{});},[]);
 const resultSignature=useRef(null), previousActive=useRef(active);
 const [checking,SetChecking]=useState(false), [,refreshActivation]=useState(0);
 const signature=sourceSignature(sources,reviewEpoch), context=useRef({signature,connected});
 context.current={signature,connected};
 const previous=useRef({signature,connected});
 const [submitted,SetSubmitted]=useState(null);
 const custom=scopeMode==='custom';
 const filters=custom?customFilters:allFilters;
 const scopeReady=!custom||Object.values(customFilters).some(ids=>ids.length>0);
 const selectableSources=availableSources(sources);
 const titleQuery=sourceSearch.trim().toLowerCase();
 const matchingSources=selectableSources.filter(source=>(source.title||source.original_name||'').toLowerCase().includes(titleQuery));
 const selectedSourceIds=new Set(customFilters.sources);
 const unavailable=unavailableSourceIds(filters.sources,selectableSources);
 function invalidate(message){
  requestGeneration.current++; citationGeneration.current++; validationGeneration.current++; abortRef.current?.abort(); SetChecking(false);
  readerRef.current?.cancel().catch(()=>{}); readerRef.current=null;
  R({}); C(null); G(null); B(false); if(message) E(message);
 }
 useEffect(()=>{
  const old=previous.current;
  if(old.signature!==signature || (old.connected && !connected)) {
   const hasOutput=!!(result.answer || result.insufficient || citation || candidates || busy);
   invalidate(hasOutput?(old.signature!==signature?'资料已变化，之前的回答和证据已清除，请重新提问。':'连接已断开，之前的回答和证据已清除。'):'');
  }
  if(!connected)P(false);
  previous.current={signature,connected};
 },[signature,connected]);
 async function loadStatus(){
  if(!connected)return;
  const token=++statusGeneration.current;
  const current=()=>isCurrentRequest(token,statusGeneration.current,context.current.connected,signature,context.current.signature);
  SetStatusFailed(false);
  try{const value=await api('/rag/status'); if(current())S(value);}
  catch{if(current())SetStatusFailed(true);}
 }
 useEffect(()=>{
  if(!connected){S(null); SetStatusFailed(false); return;}
  if(!active)return;
  let timer, stopped=false;
  async function poll(){
   await loadStatus();
   if(!stopped)timer=setTimeout(poll,statusPollInterval);
  }
  poll();
  return ()=>{stopped=true;clearTimeout(timer);statusGeneration.current++;};
 },[connected,active,signature,statusPollInterval]);
 async function openCitation(id){
  if(!connected)return;
  const token=++citationGeneration.current, captured=signature; C(null); E('');
  try{const value=await api('/rag/citations/'+encodeURIComponent(id));
   if(isCurrentRequest(token,citationGeneration.current,context.current.connected,captured,context.current.signature))C(value);
  }catch{if(isCurrentRequest(token,citationGeneration.current,context.current.connected,captured,context.current.signature)){R({});C(null);E(errorText('rag_invalidated'))}}
 }
 async function indexAction(path,body){
  SetIndexBusy(true); E(''); try{await api(path,{method:'POST',body:JSON.stringify(body)});await loadStatus()}catch(e){E(errorText(e))}finally{SetIndexBusy(false)}
 }
 async function run(action,partial=false){
  if(action==='stream' ? !(partial?canAnswerPartially:canAnswer) : !canSearch)return;
  const requestFilters=partial?{...filters,sources:coverage.covered}:filters;
  const token=++requestGeneration.current, captured=signature;
  const valid=()=>isCurrentRequest(token,requestGeneration.current,context.current.connected,captured,context.current.signature);
  citationGeneration.current++; validationGeneration.current++; SetChecking(false); resultSignature.current=signature; SetSubmitted({question,mode,filters:JSON.parse(JSON.stringify(requestFilters)),partial});
  B(true);E('');R({});C(null);G(null);
  try{
   const body={allow_paid:paid,request_id:crypto.randomUUID(),question,mode,filters:requestFilters};
   if(action==='stream'){
    if(coverage)body.expected_source_ids=coverage.covered;
    const controller=new AbortController(); abortRef.current=controller;
    const res=await fetch('/api/rag/stream',{signal:controller.signal,method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':session.csrf_token},body:JSON.stringify(body)});
    if(!valid()){res.body?.cancel().catch(()=>{});return;}
    if(!res.ok){const data=await guardedJson(res,token,()=>requestGeneration.current,onLoginRequired);if(!valid())return;throw Error(data.error || 'internal_error')}
    const reader=res.body.getReader(); readerRef.current=reader;
    const decoder=new TextDecoder(); let buffer='',doneEvent=false;
    while(true){const {value,done}=await reader.read(); if(!valid())return; if(done)break;
     const parsed=parseSSE(buffer+decoder.decode(value,{stream:true}));buffer=parsed.rest;
     for(const event of parsed.events){
      if(['done','invalidated','error'].includes(event.type))doneEvent=true;
      if(['invalidated','error'].includes(event.type)){citationGeneration.current++;C(null)}
      if(event.code==='rag_coverage_changed')loadStatus();
      R(s=>valid()?applyEvent(s,event):s);
     }
    }
    if(!doneEvent)throw Error('internal_error');
   }else{
    const x=await api('/rag/'+action,{method:'POST',body:JSON.stringify(body)}); if(!valid())return;
    G(x.items);
   }
  }catch(e){if(valid()){citationGeneration.current++;C(null);R({});E(errorText(e))}}
  finally{if(valid()){readerRef.current=null;B(false)}}
 }
 useEffect(()=>{
  const returning=active && !previousActive.current;
  previousActive.current=active;
  if(returning)refreshActivation(n=>n+1);
  if(!returning || !connected || resultSignature.current!==signature || busy)return;
  const ids=displayAnswer(result.answer,result.insufficient?[]:result.citations).items.map(item=>item.id);
  if(!ids.length)return;
  const token=++validationGeneration.current, requestToken=requestGeneration.current, captured=signature;
  SetChecking(true);
  Promise.all(ids.map(id=>api('/rag/citations/'+encodeURIComponent(id)))).then(()=>{
   if(token===validationGeneration.current && isCurrentRequest(requestToken,requestGeneration.current,context.current.connected,captured,context.current.signature))SetChecking(false);
  }).catch(()=>{
   if(token===validationGeneration.current && isCurrentRequest(requestToken,requestGeneration.current,context.current.connected,captured,context.current.signature)){
    citationGeneration.current++;R({});C(null);G(null);SetChecking(false);E('资料引用已失效，请重新提问。');
   }
  });
 },[active]);
 function toggle(key,id){
  setCustomFilters(old=>({...old,[key]:old[key].includes(id)?old[key].filter(x=>x!==id):[...old[key],id]}));
 }
 function selectMatchingSources(){
  setCustomFilters(old=>({...old,sources:[...new Set([...old.sources,...matchingSources.map(source=>source.id)])]}));
 }
 function clearUnavailable(){
  setCustomFilters(old=>({...old,sources:old.sources.filter(id=>!unavailable.includes(id))}));
  P(false);
 }
 const coverage=(()=>{
  if(!scopeReady||!Array.isArray(status?.eligible_source_ids)||!Array.isArray(status?.indexed_source_ids))return null;
  const eligible=new Set(status.eligible_source_ids), indexed=new Set(status.indexed_source_ids);
  const selectedCategories=['topics','tags'].map(key=>[key,new Set(filters[key])]);
  const scoped=selectableSources.filter(source=>eligible.has(source.id)
    &&(!filters.sources.length||selectedSourceIds.has(source.id))
    &&selectedCategories.every(([key,ids])=>!ids.size||(source.classification?.[key]||[]).some(item=>ids.has(item.id))));
  return {total:scoped.length,covered:scoped.filter(x=>indexed.has(x.id)).map(x=>x.id),pending:scoped.filter(x=>!indexed.has(x.id))};
 })();
 const canSubmit=scopeReady&&connected&&!reviewPending&&!busy&&!!status&&status.enabled!==false&&!unavailable.length&&!!question.trim();
 const canSearch=canSubmit&&(mode==='lexical'||paid);
 const canAnswer=canSubmit&&paid&&(!coverage||(coverage.covered.length>0&&!coverage.pending.length));
 const canAnswerPartially=canSubmit&&paid&&!!coverage&&coverage.covered.length>0&&coverage.pending.length>0;
 const scope=f=>[['资料',f.sources],['主题',f.topics],['标签',f.tags]].map(([name,ids])=>ids.length?`${name} ${ids.length} 项`:null).filter(Boolean).join('、')||'全部已批准资料';
 let loc=citation?.locator||{},seconds=loc.seconds??loc.start_seconds??loc.start;
 const isVideo=['video','mp4'].includes(sources.find(x=>x.id===citation?.source_id)?.kind);
 const human=loc.origin==='human_edit'||String(citation?.type||loc.type||'').startsWith('human_')||String(loc.locator||'').startsWith('human-edit:');
 const hasTime=isVideo&&!human&&typeof seconds==='number'&&Number.isFinite(seconds)&&seconds>=0;
 const display=displayAnswer(result.answer,result.insufficient?[]:result.citations);
 const showEvidence=connected && resultSignature.current===signature && !checking && !(active && !previousActive.current);
 const sourceName=x=>{let src=sources.find(y=>y.id===x.source_id);return src?.title||src?.original_name||config.unknown_source_label};
 return <section className="rag-panel">
 <header className="rag-header">
 <h2 data-page-title tabIndex={-1}>问答</h2>
 <span className="rag-status" role="status">{statusFailed?'索引状态加载失败':status?(status.enabled===false?'问答未启用':status.ready&&status.indexed_sources!==0?'索引可用':'尚无可用索引')+(status.needs_rebuild?'，需要重新构建':''):'索引状态加载中'}</span>
 {statusFailed&&<button type="button" onClick={loadStatus}>重试加载索引状态</button>}
 </header>
 {status?.auto_index&&status.enabled!==false&&<div className="rag-coverage">
 <p role="status">自动索引：{({idle:'空闲',queued:'排队中',running:'进行中',failed:'失败',paused:'已暂停'})[status.auto_index.state]||'状态未知'}{status.auto_index.error_code?' · '+errorText(status.auto_index.error_code):''}</p>
 <button disabled={indexBusy||!connected} onClick={()=>{const enabled=!status.auto_index.enabled;if(!enabled||window.confirm('开启自动索引将允许后台索引产生模型费用，确认授权？'))indexAction('/rag/auto-index',{enabled,...(enabled?{allow_paid:true}:{})})}}>{status.auto_index.enabled?'关闭自动索引':'开启自动索引并授权费用'}</button>
 </div>}
 <div className="rag-compose">
 <label htmlFor="rag-question">问题</label>
 <textarea id="rag-question" rows="3" value={question} onChange={e=>Q(e.target.value)} placeholder="输入问题"/>
 <div className="rag-scope-controls">
 <fieldset className="rag-scope-mode">
 <legend>检索范围</legend>
 <label><input type="radio" name="rag-scope" value="all" checked={!custom} onChange={()=>setScopeMode('all')}/> 全部已批准资料</label>
 <label><input type="radio" name="rag-scope" value="custom" checked={custom} onChange={()=>setScopeMode('custom')}/> 自定义范围</label>
 </fieldset>
 <label className="rag-retrieval-mode">检索模式 <select value={mode} onChange={e=>M(e.target.value)}>
 <option value="lexical">本地关键词</option>
 <option value="hybrid">混合检索</option>
 </select></label>
 </div>
 {custom&&<div className="rag-options">
 <fieldset>
 <legend>资料</legend>
 <input className="rag-source-search" type="search" aria-label="搜索资料标题" placeholder="搜索资料标题" value={sourceSearch} onChange={e=>setSourceSearch(e.target.value)}/>
 <div className="rag-source-actions">
 <button type="button" disabled={!matchingSources.some(source=>!selectedSourceIds.has(source.id))} onClick={selectMatchingSources}>全选搜索结果</button>
 <button type="button" disabled={!selectedSourceIds.size} onClick={()=>setCustomFilters(old=>({...old,sources:[]}))}>清空已选资料</button>
 </div>
 <p className="rag-muted rag-source-count" role="status">匹配 {matchingSources.length} 份 · 已选 {selectedSourceIds.size} 份</p>
 <div className="rag-option-list">{matchingSources.map(source=><label key={source.id}>
 <input type="checkbox" checked={selectedSourceIds.has(source.id)} onChange={()=>toggle('sources',source.id)}/>{source.title||source.original_name}
 </label>)}</div>
 </fieldset>
 {['topics','tags'].map(key=><fieldset key={key}>
 <legend>{key==='topics'?'主题':'标签'}</legend>
 <div className="rag-option-list">{catalog.filter(item=>item.kind===(key==='topics'?'topic':'tag')).map(item=><label key={item.id}>
 <input type="checkbox" checked={filters[key].includes(item.id)} onChange={()=>toggle(key,item.id)}/>{item.name}
 </label>)}</div>
 </fieldset>)}
 </div>}
 {!scopeReady&&<p className="rag-muted" role="status">请选择至少一项资料、主题或标签。</p>}
 {unavailable.length>0&&<div>
 <p role="status">已选范围内有 {unavailable.length} 项资料不可用，请移除后重新确认范围。</p>
 <button type="button" onClick={clearUnavailable}>移除不可用资料</button>
 </div>}
 {coverage&&<div className="rag-coverage">
 <p role="status">当前范围已索引 {coverage.covered.length} / {coverage.total} 份。{coverage.total===0?'该范围内没有已批准的资料。':coverage.covered.length===0?'该范围暂无可用于问答的索引。':coverage.pending.length>0?'可等待索引更新，或仅用已索引资料回答。':''}</p>
 {coverage.pending.length>0&&<details><summary>查看 {coverage.pending.length} 份未覆盖资料</summary><ul>{coverage.pending.map(x=><li key={x.id}>{x.title||x.original_name}{status.unindexable_source_ids?.includes(x.id)?'（没有可索引的证据）':''}</li>)}</ul></details>}
 </div>}
 <div className="rag-actions">
 <label>
 <input type="checkbox" checked={paid} onChange={e=>P(e.target.checked)}/> 我同意本次操作可能产生模型费用</label>
 <button className="rag-primary" disabled={!canAnswer} onClick={()=>run('stream')}>生成回答</button>
 {coverage&&coverage.covered.length>0&&coverage.pending.length>0&&<button disabled={!canAnswerPartially} onClick={()=>run('stream',true)}>仅用已索引资料回答</button>}
 </div>
 </div>
 <details className="rag-diagnostics">
 <summary>索引与检索诊断</summary>{status&&<>
 <p>合格资料：{status.eligible_sources??'—'}；已索引资料：{status.indexed_sources??'—'}；已索引片段：{status.indexed_chunks??'—'}</p>
 <p>空间：{typeof status.space==='string'?status.space:status.space_id||'暂无空间'}</p>
 <button type="button" disabled={busy} onClick={loadStatus}>刷新索引状态</button>
 </>}<p>批准后由后台更新索引。本地关键词检索候选无需付费。</p>
 <div className="rag-index-actions">
 <label><input type="checkbox" checked={indexPaid} onChange={e=>SetIndexPaid(e.target.checked)}/> 我同意本次索引更新可能产生模型费用</label>
 <button disabled={indexBusy||reviewPending||!connected||!status?.auto_index||status.enabled===false||!indexPaid||['running','queued'].includes(status.auto_index.state)} onClick={()=>{SetIndexPaid(false);indexAction('/rag/index/retry',{allow_paid:true})}}>{status?.auto_index?.state==='failed'?'重试索引更新':'更新索引'}</button>
 <button disabled={!canSearch} onClick={()=>run('search')}>检索候选</button>
 </div>
 </details>
 {reviewPending&&<p role="status">资料审核正在提交，完成后再提问</p>}
 {busy&&<p role="status">{result.progress||'处理中，请勿重复提交。'}</p>}
 {(error||result.error)&&<p className="rag-error" role="alert">{error||result.error}</p>}
 {showEvidence&&submitted&&(result.answer||result.insufficient||candidates)&&<div className="rag-result">
 <h3>{submitted.question}</h3>
 <p className="rag-muted">范围：{scope(submitted.filters)}{submitted.partial?'（仅已索引资料）':''}；{submitted.mode==='lexical'?'本地关键词':'混合检索'}</p>
 </div>}
 {checking&&<p role="status">正在验证引用…</p>}
 {showEvidence&&result.answer&&<div className="citation-answer">{display.paragraphs.map((paragraph,j)=>
 <p key={j}>{paragraph.map((part,i)=>part.id?<sup key={i}>
 <button className="citation-marker" type="button" aria-label={"查看引用 "+part.marker} onClick={()=>openCitation(part.id)}>{part.marker}</button>
 </sup>:<React.Fragment key={i}>{part.text}</React.Fragment>)}</p>)}</div>}
 {showEvidence&&result.insufficient&&<p>证据不足。</p>}
 {showEvidence&&candidates&&<details className="rag-diagnostics">
 <summary>检索候选（非回答引用）</summary>{candidates.length?candidates.map(x=>
 <article key={x.chunk_id}>
 <pre>{x.text}</pre>
 </article>):<p>没有检索候选。</p>}</details>}
 {showEvidence&&display.items.length>0&&<section>
 <h4>{config.source_label}</h4>{display.items.map(x=>
 <p key={x.id}>
 <button className="citation-marker" type="button" aria-label={"查看引用 "+x.marker} onClick={()=>openCitation(x.id)}>{x.marker}</button> {sourceName(x.citation)} {locationText(x.citation,['video','mp4'].includes(sources.find(y=>y.id===x.citation.source_id)?.kind))}</p>)}</section>}
 {showEvidence&&citation&&<article>
 <h4>{sourceName(citation)}</h4>
 <p>{locationText(citation,isVideo)}</p>
 <h5>{config.evidence_label}</h5>
 <blockquote className="citation-evidence">{citation.text}</blockquote>
 <details>
 <summary>{config.technical_label}</summary>
 <pre className="citation-technical">{JSON.stringify({chunk_id:citation.chunk_id,source_id:citation.source_id,version_id:citation.version_id,content_sha256:citation.content_sha256,locator:citation.locator},null,2)}</pre>
 </details>{hasTime&&<video controls src={'/api/sources/'+encodeURIComponent(citation.source_id)+'/original'} onLoadedMetadata={e=>{e.currentTarget.currentTime=seconds}}/>}</article>}</section>
}
