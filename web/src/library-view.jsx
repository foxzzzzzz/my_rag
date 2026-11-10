import React,{useState,useEffect} from 'react';
import {filterSources} from './management-helpers';
import {formatDate} from './helpers';
function Choices({catalog,kind,value,onChange}) {return <fieldset>
<legend>{kind==='topic'?'主题':'标签'}</legend>
<div className="choices">{catalog.filter(x=>x.kind===kind).map(x=>
<label key={x.id}>
<input type="checkbox" checked={value.includes(x.id)} onChange={e=>onChange(e.target.checked?[...value,x.id]:value.filter(y=>y!==x.id))}/>{x.name}</label>)}</div>
</fieldset>}
export function LibraryView({sources,catalog,api,open,changed,disabled,topicId,onTopicChange,onImport,onTrash,displayTimezone}) {
 const [filters,F]=useState({q:'',kind:'',review:'',tags:[]}),[selected,S]=useState([]),[revisions,SR]=useState({}),[topics,T]=useState([]),[tags,G]=useState([]),[operation,O]=useState('add'),[results,R]=useState([]),[working,W]=useState(false),[message,M]=useState('');
 useEffect(()=>{S([]);SR({});R([])},[topicId]);
 const visible=filterSources(sources,{...filters,topics:topicId?[topicId]:[]});
 function filter(key,value){F(prev=>({...prev,[key]:value}));S([]);SR({});R([])}
 async function apply(){W(true);M('');try{const r=await api('/classifications/bulk',{method:'POST',body:JSON.stringify({items:selected.map(id=>({source_id:id,expected_revision:revisions[id]})),operation,topics,tags})});R(r.items);SR(prev=>{const next={...prev};for(const item of r.items)if(item.status==='success')next[item.source_id]=item.classification.revision;
 return next});await changed()}catch(e){M(e.message)}finally{W(false)}}
 return <section className="library-view">
<div className="page-heading">
<h2 data-page-title tabIndex={-1}>资料库</h2>
<div className="actions">
<button type="button" disabled={disabled} onClick={onTrash}>回收站</button>
<button className="primary" onClick={onImport}>导入资料</button>
</div>
</div>
<div className="toolbar">
<label className="search">查找<input value={filters.q} placeholder="标题或文件名" onChange={e=>filter('q',e.target.value)}/>
</label>
<label>类型<select value={filters.kind} onChange={e=>filter('kind',e.target.value)}>
<option value="">全部类型</option>
<option value="html">网页</option>
<option value="video">视频</option>
</select>
</label>
<label>审核<select value={filters.review} onChange={e=>filter('review',e.target.value)}>
<option value="">全部状态</option>
<option value="pending">待审核</option>
<option value="approve">已批准</option>
<option value="rework">返工</option>
<option value="reject">拒绝</option>
</select>
</label>
<label>主题<select value={topicId||''} onChange={e=>onTopicChange(e.target.value)}>
<option value="">全部主题</option>{catalog.filter(x=>x.kind==='topic').map(x=>
<option key={x.id} value={x.id}>{x.name}</option>)}</select>
</label>
<button onClick={()=>{F({q:'',kind:'',review:'',tags:[]});onTopicChange('')}}>清空筛选</button>
</div>
<details>
<summary>标签筛选</summary>
<Choices catalog={catalog} kind="tag" value={filters.tags} onChange={x=>filter('tags',x)}/>
</details>
<div className="library-list-head"><p className="muted">匹配 {visible.length} 份；已选 {selected.length} 份</p>
<div>
<button onClick={()=>{S(visible.map(x=>x.id));SR(Object.fromEntries(visible.map(x=>[x.id,x.classification?.revision||0])))}}>选择当前结果</button>
<button onClick={()=>{S([]);SR({})}}>清空选择</button>
</div></div>{!visible.length&&<p>没有匹配的资料，请清空筛选或导入资料。</p>}{visible.map(x=>
<div className="source-row" key={x.id}>
<input aria-label={'选择 '+x.original_name} type="checkbox" checked={selected.includes(x.id)} onChange={e=>{S(e.target.checked?[...selected,x.id]:selected.filter(id=>id!==x.id));
 if(e.target.checked)SR({...revisions,[x.id]:x.classification?.revision||0})}}/>
<button className="source" onClick={()=>open(x.id)}>
<strong>{x.title||x.original_name}</strong>
<small>{[...(x.classification?.topics||[]),...(x.classification?.tags||[])].map(y=>y.name).join('、')||'未分类'}</small>
<small>{['video','mp4'].includes(x.kind)?'视频':'网页'}</small>
</button>
<div className="source-side"><span>{({approve:'已批准',rework:'返工',reject:'拒绝',pending:'待审核'})[x.review_status]||'待审核'}</span><span className="source-date">{(x.updated_at||x.created_at)?formatDate(x.updated_at||x.created_at,displayTimezone):''}</span></div>
</div>)}{selected.some(id=>(sources.find(x=>x.id===id)?.classification?.revision||0)!==revisions[id])&&<p className="error">分类已变化，保存时将检查原修订号。</p>}{!!selected.length&&<details>
<summary>批量分类（{selected.length} 份）</summary>
<Choices catalog={catalog} kind="topic" value={topics} onChange={T}/>
<Choices catalog={catalog} kind="tag" value={tags} onChange={G}/>
<label>操作<select value={operation} onChange={e=>O(e.target.value)}>
<option value="add">追加所选分类</option>
<option value="remove">移除所选分类</option>
<option value="replace">替换全部主题和标签</option>
</select>
</label>{operation==='replace'&&<p>替换会清除原有主题和标签。</p>}<button disabled={disabled||working} onClick={apply}>应用到已选资料</button>
</details>}{message&&<p className="error">{message}</p>}{results.map((r,i)=>
<p key={i}>{sources.find(x=>x.id===r.source_id)?.original_name||r.source_id}：{r.status==='success'?'已完成':r.status}</p>)}</section>;
}
