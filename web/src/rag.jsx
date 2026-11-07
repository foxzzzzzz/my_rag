import React,{useEffect,useState,useRef} from 'react';
import './citation-display.css';
import './rag.css';
import {guardedJson} from './auth-client';
import {displayAnswer,locationText,config} from './citation-display';
import {parseSSE,applyEvent,errorText} from './rag-helpers';
import {sourceSignature,isCurrentRequest} from './rag-state';
export function RagPanel({onLoginRequired,api,sources,catalog,session,connected=true,active=true,reviewEpoch=0,reviewPending=false}) {
 const [status,S]=useState(null),[question,Q]=useState(''),[mode,M]=useState('hybrid'),[paid,P]=useState(false),[filters,F]=useState({sources:[],topics:[],tags:[]}),[result,R]=useState({}),[candidates,G]=useState(null),[citation,C]=useState(null),[error,E]=useState(''),[busy,B]=useState(false);
 const requestGeneration=useRef(0), citationGeneration=useRef(0), validationGeneration=useRef(0), readerRef=useRef(null), abortRef=useRef(null);
 useEffect(()=>()=>{requestGeneration.current++; abortRef.current?.abort(); readerRef.current?.cancel().catch(()=>{});},[]);
 const resultSignature=useRef(null), previousActive=useRef(active);
 const [checking,SetChecking]=useState(false), [,refreshActivation]=useState(0);
 const signature=sourceSignature(sources,reviewEpoch), context=useRef({signature,connected});
 context.current={signature,connected};
 const previous=useRef({signature,connected});
 const [submitted,SetSubmitted]=useState(null);
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
  if(!connected){P(false);S(null)}
  previous.current={signature,connected};
 },[signature,connected]);
 useEffect(()=>{
  if(!connected)return;
  let live=true;
  api('/rag/status').then(value=>{if(live && context.current.connected)S(value)}).catch(e=>{if(live && context.current.connected)E(errorText(e))});
  return ()=>{live=false};
 },[connected]);
 async function openCitation(id){
  if(!connected)return;
  const token=++citationGeneration.current, captured=signature; C(null); E('');
  try{const value=await api('/rag/citations/'+encodeURIComponent(id));
   if(isCurrentRequest(token,citationGeneration.current,context.current.connected,captured,context.current.signature))C(value);
  }catch{if(isCurrentRequest(token,citationGeneration.current,context.current.connected,captured,context.current.signature)){R({});C(null);E(errorText('rag_invalidated'))}}
 }
 async function run(action){
  if(!connected||reviewPending||!status||status.enabled===false||busy)return;
  const token=++requestGeneration.current, captured=signature;
  const valid=()=>isCurrentRequest(token,requestGeneration.current,context.current.connected,captured,context.current.signature);
  citationGeneration.current++; validationGeneration.current++; SetChecking(false); resultSignature.current=signature; if(action!=='build')SetSubmitted({question,mode,filters:JSON.parse(JSON.stringify(filters))});
  B(true);E('');R({});C(null);G(null);
  try{
   const body={allow_paid:paid,request_id:crypto.randomUUID(),...(action==='build'?{}:{question,mode,filters})};
   if(action==='stream'){
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
      R(s=>valid()?applyEvent(s,event):s);
     }
    }
    if(!doneEvent)throw Error('internal_error');
   }else{
    const x=await api('/rag/'+action,{method:'POST',body:JSON.stringify(body)}); if(!valid())return;
    if(action==='build'){const next=await api('/rag/status');if(valid())S(next)}else G(x.items);
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
 function toggle(key,id){F(old=>({...old,[key]:old[key].includes(id)?old[key].filter(x=>x!==id):[...old[key],id]}))}
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
 <span className="rag-status">{status?(status.enabled===false?'问答未启用':status.ready?'索引可用':'尚无可用索引')+(status.needs_rebuild?'，需要重新构建':''):'索引状态加载中'}</span>
 </header>
 <div className="rag-compose">
 <label htmlFor="rag-question">问题</label>
 <textarea id="rag-question" rows="3" value={question} onChange={e=>Q(e.target.value)} placeholder="输入问题"/>
 <p className="rag-muted">范围：{scope(filters)}；{mode==='lexical'?'本地关键词':'混合检索'}</p>
 <details>
 <summary>选择范围和检索方式</summary>
 <div className="rag-options">{[['sources','资料',sources.filter(x=>x.eligible)]].map(([key,label,items])=>
 <fieldset key={key}>
 <legend>{label}</legend>{items.map(x=>
 <label key={x.id}>
 <input type="checkbox" checked={filters[key].includes(x.id)} onChange={()=>toggle(key,x.id)}/>{x.title||x.original_name}</label>)}</fieldset>)}
 {['topics','tags'].map(key=>
 <fieldset key={key}>
 <legend>{key==='topics'?'主题':'标签'}</legend>{catalog.filter(x=>x.kind===(key==='topics'?'topic':'tag')).map(x=>
 <label key={x.id}>
 <input type="checkbox" checked={filters[key].includes(x.id)} onChange={()=>toggle(key,x.id)}/>{x.name}</label>)}</fieldset>)}<label>检索模式 <select value={mode} onChange={e=>M(e.target.value)}>
 <option value="lexical">本地关键词</option>
 <option value="hybrid">混合检索</option>
 </select>
 </label>
 </div>
 </details>
 <div className="rag-actions">
 <label>
 <input type="checkbox" checked={paid} onChange={e=>P(e.target.checked)}/> 我同意本次操作可能产生模型费用</label>
 <button className="rag-primary" disabled={busy||reviewPending||!connected||!status||status.enabled===false||!question.trim()||!paid} onClick={()=>run('stream')}>生成回答</button>
 </div>
 </div>
 <details className="rag-diagnostics">
 <summary>索引与检索诊断</summary>{status&&<>
 <p>合格资料：{status.eligible_sources??'—'}；已索引资料：{status.indexed_sources??'—'}；已索引片段：{status.indexed_chunks??'—'}</p>
 <p>空间：{typeof status.space==='string'?status.space:status.space_id||'暂无空间'}</p>
 </>}<p>尚无索引时，请先复核并批准资料，再构建索引。本地关键词检索无需付费。</p>
 <button disabled={busy||reviewPending||!connected||!status||status.enabled===false||!paid} onClick={()=>run('build')}>构建索引</button> <button disabled={busy||reviewPending||!connected||!status||status.enabled===false||!question.trim()||(mode!=='lexical'&&!paid)} onClick={()=>run('search')}>检索候选</button>
 </details>
 {reviewPending&&<p role="status">资料审核正在提交，完成后再提问</p>}
 {busy&&<p role="status">{result.progress||'处理中，请勿重复提交。'}</p>}
 {(error||result.error)&&<p className="rag-error" role="alert">{error||result.error}</p>}
 {showEvidence&&submitted&&(result.answer||result.insufficient||candidates)&&<div className="rag-result">
 <h3>{submitted.question}</h3>
 <p className="rag-muted">范围：{scope(submitted.filters)}；{submitted.mode==='lexical'?'本地关键词':'混合检索'}</p>
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
