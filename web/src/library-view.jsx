import React, {useEffect, useRef, useState} from 'react';
import {filterSources} from './management-helpers';
import {formatDate} from './helpers';

const batchStatus = {
  success:'已完成',
  classification_conflict:'分类已更新，请取消选择后重新勾选',
  classification_not_found:'所选主题或标签已不存在',
  source_not_found:'资料已不存在',
  invalid_classification:'分类选项无效'
};

function Choices({catalog,kind,value,onChange}) {
  return <fieldset>
    <legend>{kind==='topic'?'主题':'标签'}</legend>
    <div className="choices">{catalog.filter(item=>item.kind===kind).map(item=>
      <label key={item.id}>
        <input type="checkbox" checked={value.includes(item.id)}
          onChange={event=>onChange(event.target.checked?[...value,item.id]:value.filter(id=>id!==item.id))}/>
        {item.name}
      </label>)}
    </div>
  </fieldset>;
}

export function LibraryView({sources,catalog,api,open,changed,disabled,topicId,filters,setFilters,onResetFilters,onImport,onTrash,displayTimezone}) {
  const [selection,setSelection]=useState({});
  const [batchOpen,setBatchOpen]=useState(false);
  const [topics,setTopics]=useState([]), [tags,setTags]=useState([]), [operation,setOperation]=useState('add');
  const [results,setResults]=useState([]), [working,setWorking]=useState(false), [message,setMessage]=useState('');
  const selectionScope=useRef(0);
  const visible=filterSources(sources,{...filters,topics:topicId?[topicId]:[]});
  const selected=visible.filter(source=>Object.hasOwn(selection,source.id));
  const allSelected=visible.length>0&&selected.length===visible.length;
  const hasBatchFeedback=results.length>0||!!message;
  const changedRevision=selected.some(source=>(source.classification?.revision??0)!==selection[source.id]);

  function clearSelection() {
    selectionScope.current++;
    setSelection({});
    setResults([]);
    setMessage('');
    setBatchOpen(false);
  }
  useEffect(()=>{clearSelection()},[topicId,filters]);

  function filter(key,value) {
    setFilters(previous=>({...previous,[key]:value}));
  }
  function toggleSource(source,checked) {
    if(!checked&&selected.length===1){clearSelection();return}
    setSelection(previous=>{
      const next={...previous};
      if(checked)next[source.id]=source.classification?.revision??0;
      else delete next[source.id];
      return next;
    });
  }
  function toggleAll(checked) {
    if(!checked){clearSelection();return}
    setSelection(Object.fromEntries(visible.map(source=>[
      source.id,selection[source.id]??source.classification?.revision??0
    ])));
  }
  async function apply() {
    const scope=selectionScope.current;
    setWorking(true);
    setMessage('');
    try {
      const items=selected.map(source=>({source_id:source.id,expected_revision:selection[source.id]}));
      const response=await api('/classifications/bulk',{method:'POST',body:JSON.stringify({items,operation,topics,tags})});
      if(scope===selectionScope.current){
        setResults(response.items);
        setSelection(previous=>{
          const next={...previous};
          for(const item of response.items){
            if(item.status==='success')next[item.source_id]=item.classification.revision;
          }
          return next;
        });
      }
      await changed();
    } catch(error) {
      if(scope===selectionScope.current)setMessage(error.message);
    } finally {
      setWorking(false);
    }
  }

  return <section className="library-view">
    <div className="page-heading">
      <h2 data-page-title tabIndex={-1}>资料库</h2>
      <div className="actions">
        <button type="button" disabled={disabled} onClick={onTrash}>回收站</button>
        <button className="primary" onClick={onImport}>导入资料</button>
      </div>
    </div>
    <div className="toolbar">
      <label className="search">查找<input value={filters.q} placeholder="标题或文件名" onChange={event=>filter('q',event.target.value)}/></label>
      <label>类型<select value={filters.kind} onChange={event=>filter('kind',event.target.value)}>
        <option value="">全部类型</option>
        <option value="html">网页</option>
        <option value="video">视频</option>
      </select></label>
      <label>审核<select value={filters.review} onChange={event=>filter('review',event.target.value)}>
        <option value="">全部状态</option>
        <option value="pending">待审核</option>
        <option value="approve">已批准</option>
        <option value="rework">返工</option>
        <option value="reject">拒绝</option>
      </select></label>
      <button onClick={onResetFilters}>清空筛选</button>
    </div>
    <details>
      <summary>标签筛选</summary>
      <Choices catalog={catalog} kind="tag" value={filters.tags} onChange={value=>filter('tags',value)}/>
    </details>
    <div className="library-list-head">
      <label>
        <input type="checkbox" checked={allSelected} disabled={!visible.length||working}
          ref={input=>{if(input)input.indeterminate=!allSelected&&selected.length>0}}
          onChange={event=>toggleAll(event.target.checked)}/>
        全选匹配结果
      </label>
      <span className="muted" role="status">匹配 {visible.length} 份{selected.length>0&&`，已选 ${selected.length} 份`}</span>
      {(selected.length>0||hasBatchFeedback)&&<div className="library-selection-actions">
        <button aria-expanded={batchOpen} aria-controls="library-batch-classification"
          onClick={()=>setBatchOpen(!batchOpen)}>{selected.length?'批量分类':'批量分类结果'}</button>
        <button disabled={working} onClick={clearSelection}>{selected.length?'取消选择':'清除结果'}</button>
      </div>}
    </div>
    <div id="library-batch-classification" className="library-batch" hidden={!batchOpen||(!selected.length&&!hasBatchFeedback)}>
      {!!selected.length&&<>
        {changedRevision&&<p className="error">分类已变化，保存时将检查原修订号。</p>}
        <Choices catalog={catalog} kind="topic" value={topics} onChange={setTopics}/>
        <Choices catalog={catalog} kind="tag" value={tags} onChange={setTags}/>
        <div className="actions">
          <label>操作<select value={operation} onChange={event=>setOperation(event.target.value)}>
            <option value="add">追加所选分类</option>
            <option value="remove">移除所选分类</option>
            <option value="replace">替换全部主题和标签</option>
          </select></label>
          <button disabled={disabled||working} onClick={apply}>应用到已选资料</button>
        </div>
        {operation==='replace'&&<p>替换会清除原有主题和标签。</p>}
      </>}
      {message&&<p className="error" role="alert">{message}</p>}
      <div aria-live="polite">{results.map(item=>
        <p key={item.source_id}>{sources.find(source=>source.id===item.source_id)?.original_name||item.source_id}：{batchStatus[item.status]||'分类更新失败'}</p>)}
      </div>
    </div>
    {!visible.length&&<p>没有匹配的资料，请清空筛选或导入资料。</p>}
    {visible.map(source=>
      <div className="source-row" key={source.id}>
        <input aria-label={'选择 '+source.original_name} type="checkbox" disabled={working}
          checked={Object.hasOwn(selection,source.id)} onChange={event=>toggleSource(source,event.target.checked)}/>
        <button className="source" onClick={()=>open(source.id)}>
          <strong>{source.title||source.original_name}</strong>
          <small>{[...(source.classification?.topics||[]),...(source.classification?.tags||[])].map(item=>item.name).join('、')||'未分类'}</small>
          <small>{['video','mp4'].includes(source.kind)?'视频':'网页'}</small>
        </button>
        <div className="source-side">
          <span>{({approve:'已批准',rework:'返工',reject:'拒绝',pending:'待审核'})[source.review_status]||'待审核'}</span>
          <span className="source-date">{(source.updated_at||source.created_at)?formatDate(source.updated_at||source.created_at,displayTimezone):''}</span>
        </div>
      </div>)}
  </section>;
}
