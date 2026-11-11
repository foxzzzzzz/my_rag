import React, {useEffect, useRef, useState} from 'react';
import {filterSources, labelIds, splitAliases, douyinErrorText, suggestionSelection, suggestionError} from './management-helpers';
import {classificationTopicRequired} from './helpers';

function Choices({catalog, kind, value, onChange, disabled=false, allowAdd=true}) {
  const options=catalog.filter(x=>x.kind===kind);
  return <fieldset disabled={disabled}><legend>{kind==='topic'?'主题':'知识标签'}</legend>
    {!options.length&&<small>尚无分类，可到“分类”页面创建。</small>}
    <div className="choices">{options.map(x=><label key={x.id} title={(x.aliases||[]).join('、')}><input type="checkbox" checked={value.includes(x.id)} disabled={!allowAdd&&!value.includes(x.id)} onChange={e=>onChange(e.target.checked?[...value,x.id]:value.filter(id=>id!==x.id))}/>{x.name}</label>)}</div>
  </fieldset>;
}

export function ClassificationEditor({source, catalog, api, changed, disabled}) {
  const incoming=source.classification||{revision:0,topics:[],tags:[]};
  const [base,SB]=useState(incoming),[topics,T]=useState(labelIds(incoming.topics)),[tags,G]=useState(labelIds(incoming.tags)),[dirty,D]=useState(false),[message,M]=useState(''),[working,W]=useState(false);
  const needsTopic=!topics.length&&!!tags.length;
  useEffect(()=>{if(!dirty){SB(incoming);T(labelIds(incoming.topics));G(labelIds(incoming.tags))}},[source.id,incoming.revision,dirty]);
  async function save(){W(true);M('');try{await api('/sources/'+source.id+'/classification',{method:'POST',body:JSON.stringify({expected_revision:base.revision,topics,tags})});D(false);await changed();M('分类已保存，正文版本和评分未改变。')}catch(e){M(e.message)}finally{W(false)}}
  return <div className="management"><h3>主题与知识标签</h3><p>支持多选；独立于审核问题标签。</p>
    {dirty&&base.revision!==incoming.revision&&<p className="error">分类已被其他操作更新，保存会检查冲突，请重新载入后调整。</p>}
    <Choices catalog={catalog} kind="topic" value={topics} onChange={x=>{T(x);D(true)}} disabled={working||disabled}/>
    {!topics.length&&<p className={needsTopic?'error':'muted'}>{needsTopic?classificationTopicRequired:'选择主题后可添加标签。'}</p>}
    <Choices catalog={catalog} kind="tag" value={tags} onChange={x=>{G(x);D(true)}} disabled={working||disabled} allowAdd={!!topics.length}/>
    <button disabled={!dirty||working||disabled||needsTopic} onClick={save}>保存分类</button><button disabled={working} onClick={()=>{SB(incoming);T(labelIds(incoming.topics));G(labelIds(incoming.tags));D(false);M('')}}>重新载入分类</button>
    {message&&<p role="status">{message}</p>}
    <SuggestionPanel source={source} catalog={catalog} api={api} changed={changed} disabled={disabled}/>
  </div>;
}


function SuggestionPanel({source,catalog,api,changed,disabled}) {
  const [record,R]=useState(null),[selection,S]=useState(suggestionSelection()),[paid,P]=useState(false),[working,W]=useState(false),[message,M]=useState(''),[enabled,E]=useState(false);
  const path='/sources/'+source.id+'/classification/suggestions';
  useEffect(()=>{let active=true; R(null); S(suggestionSelection()); P(false); Promise.all([api(path),api('/classification-suggestions/status')]).then(([r,status])=>{if(active){R(r);E(status.enabled);S(suggestionSelection(r?.result?.suggestions))}}).catch(e=>{if(active)M(suggestionError(e.message))}); return()=>{active=false}},[source.id]);
  async function perform(fn){W(true);M('');try{await fn()}catch(e){M(e.message===classificationTopicRequired?e.message:suggestionError(e.message))}finally{W(false)}}
  async function generate(){await perform(async()=>{const r=await api(path,{method:'POST',body:JSON.stringify({expected_version_id:source.current_version_id,expected_revision:source.classification?.revision||0,allow_paid:true})});R(r);S(suggestionSelection(r.result?.suggestions));P(false)})}
  async function apply(){await perform(async()=>{const r=await api('/classification-suggestions/'+record.id+'/apply',{method:'POST',body:JSON.stringify(selection)});R(r);await changed();M('建议已应用，正文和评分保持不变。')})}
  async function reject(){await perform(async()=>{R(await api('/classification-suggestions/'+record.id+'/reject',{method:'POST',body:'{}'}));M('建议已拒绝。')})}
  function toggle(key,value,checked){S(prev=>({...prev,[key]:checked?[...prev[key],value]:prev[key].filter(x=>x!==value)}))}
  const suggestions=record?.result?.suggestions;
  return <div><h4>AI 分类建议</h4><p>生成建议会调用文本模型，可能产生费用；不会自动修改分类。</p>{!enabled&&<p>分类建议未启用，请在本机配置中启用并配置现有文本模型。</p>}<label><input type="checkbox" checked={paid} onChange={e=>P(e.target.checked)}/> 我同意本次模型调用费用</label><button disabled={disabled||working||!enabled||!paid||!source.current_version_id} onClick={generate}>生成分类建议</button>
    {record&&<p>{({running:'生成中',ready:'等待确认',applied:'已应用',rejected:'已拒绝',failed:'生成失败',needs_attention:'生成结果需要处理，请检查预算后再操作'})[record.status]||'状态待确认'}</p>}
    {record?.status==='ready'&&suggestions&&<div>{[['existing_topics','已有主题'],['existing_tags','已有标签'],['new_topics','建议新建主题'],['new_tags','建议新建标签']].map(([key,title])=>{const selectionKey=key.startsWith('new_')?'confirmed_'+key:key;return <fieldset key={key} disabled={working||disabled}><legend>{title}</legend>{suggestions[key].map(value=><label key={value}><input type="checkbox" checked={selection[selectionKey].includes(value)} onChange={e=>toggle(selectionKey,value,e.target.checked)}/>{key.startsWith('new_')?value:(catalog.find(x=>x.id===value)?.name||'分类已变化')}</label>)}</fieldset>})}<button disabled={working||disabled} onClick={apply}>应用所选建议</button><button disabled={working||disabled} onClick={reject}>拒绝建议</button></div>}
    {message&&<p role="status">{message}</p>}
  </div>;
}

export function CatalogManager({catalog,api,changed,disabled}) {
  const [kind,K]=useState('topic'),[name,N]=useState(''),[aliases,A]=useState(''),[editing,E]=useState(null),[message,M]=useState(''),[working,W]=useState(false);
  async function save(){W(true);M('');try{const payload={kind,name,aliases:splitAliases(aliases),...(editing?{expected_revision:editing.revision}:{})};await api('/classifications'+(editing?'/'+editing.id:''),{method:'POST',body:JSON.stringify(payload)});E(null);N('');A('');await changed();M('分类目录已保存。')}catch(e){M(e.message)}finally{W(false)}}
  return <section><h3>分类目录</h3><p>名称或别名重命名后仍保留稳定 ID，不需要移动资料目录。</p>
    <label>类型<select value={kind} disabled={!!editing} onChange={e=>K(e.target.value)}><option value="topic">主题</option><option value="tag">知识标签</option></select></label>
    <label>名称<input value={name} onChange={e=>N(e.target.value)}/></label><label>别名（逗号或换行分隔）<textarea value={aliases} onChange={e=>A(e.target.value)}/></label>
    <button disabled={disabled||working||!name.trim()} onClick={save}>{editing?'保存目录修改':'创建分类'}</button>{editing&&<button onClick={()=>{E(null);N('');A('')}}>取消修改</button>}{message&&<p role="status">{message}</p>}
    {catalog.map(x=><article key={x.id}><strong>{x.kind==='topic'?'主题':'标签'}：{x.name}</strong><small>别名：{x.aliases?.join('、')||'无'}</small><button disabled={working||disabled} onClick={()=>{E(x);K(x.kind);N(x.name);A((x.aliases||[]).join('\n'));M('')}}>修改名称或别名</button></article>)}
  </section>;
}

export function LibraryPanel({sources,catalog,api,open,changed,disabled}) {
  const [filters,F]=useState({q:'',kind:'',review:'',topics:[],tags:[]}),[selected,S]=useState([]),[revisions,SR]=useState({}),[topics,T]=useState([]),[tags,G]=useState([]),[operation,O]=useState('add'),[results,R]=useState([]),[working,W]=useState(false),[message,M]=useState('');
  const visible=filterSources(sources,filters);
  function filter(key,value){F({...filters,[key]:value});S([]);SR({});R([])}
  async function apply(){W(true);M('');try{let items=selected.map(id=>({source_id:id,expected_revision:revisions[id]}));let r=await api('/classifications/bulk',{method:'POST',body:JSON.stringify({items,operation,topics,tags})});R(r.items);SR(prior=>{let next={...prior};for(let item of r.items)if(item.status==='success')next[item.source_id]=item.classification.revision;return next});await changed()}catch(e){M(e.message)}finally{W(false)}}
  return <section><h3>资料与分类视图</h3><label>查找资料<input placeholder="标题或文件名" value={filters.q} onChange={e=>filter('q',e.target.value)}/></label>
    <label>来源类型<select value={filters.kind} onChange={e=>filter('kind',e.target.value)}><option value="">全部类型</option><option value="html">网页</option><option value="video">视频</option></select></label>
    <label>审核状态<select value={filters.review} onChange={e=>filter('review',e.target.value)}><option value="">全部状态</option><option value="pending">待审核</option><option value="approve">已批准</option><option value="rework">返工</option><option value="reject">拒绝</option></select></label>
    <Choices catalog={catalog} kind="topic" value={filters.topics} onChange={x=>filter('topics',x)}/><Choices catalog={catalog} kind="tag" value={filters.tags} onChange={x=>filter('tags',x)}/>
    <p>匹配 {visible.length} 份；已选 {selected.length} 份</p><button onClick={()=>{S(visible.map(x=>x.id));SR(Object.fromEntries(visible.map(x=>[x.id,x.classification?.revision||0])))}}>选择当前结果</button><button onClick={()=>{S([]);SR({})}}>清空选择</button>
    {visible.map(x=><div className="source-row" key={x.id}><input aria-label={'选择 '+x.original_name} type="checkbox" checked={selected.includes(x.id)} onChange={e=>{S(e.target.checked?[...selected,x.id]:selected.filter(id=>id!==x.id));if(e.target.checked)SR({...revisions,[x.id]:x.classification?.revision||0})}}/><button className="source" onClick={()=>open(x.id)}>{x.original_name}<small>{[...(x.classification?.topics||[]),...(x.classification?.tags||[])].map(y=>y.name).join(' · ')||'未分类'}</small></button></div>)}
    {selected.some(id=>sources.find(x=>x.id===id)?.classification?.revision!==revisions[id])&&<p className="error">已选资料分类发生变化；批量保存将检查原修订号，冲突项不会覆盖。</p>}{!!selected.length&&<details open><summary>批量分类（{selected.length} 份）</summary><Choices catalog={catalog} kind="topic" value={topics} onChange={T}/><Choices catalog={catalog} kind="tag" value={tags} onChange={G}/><label>操作<select value={operation} onChange={e=>O(e.target.value)}><option value="add">追加所选分类</option><option value="remove">移除所选分类</option><option value="replace">替换全部主题和标签</option></select></label>{operation==='replace'&&<p>替换会清除原有主题和标签，再使用上方选择。</p>}<button disabled={disabled||working} onClick={apply}>应用到已选资料</button></details>}
    {message&&<p className="error">{message}</p>}{results.map((r,i)=><p key={i}>{sources.find(x=>x.id===r.source_id)?.original_name||r.source_id}：{r.status==='success'?'已完成':r.status}</p>)}
  </section>;
}

export function ObsidianPanel({sourceId,api,applied,disabled}) {
  const [file,F]=useState(null),[preview,P]=useState(null),[choice,C]=useState(''),[message,M]=useState(''),[working,W]=useState(false);
  async function inspect(){W(true);M('');P(null);C('');try{P(await api('/obsidian/preview?filename='+encodeURIComponent(file.name),{method:'POST',body:file,headers:{'Content-Type':'application/octet-stream'}}))}catch(e){M(e.message)}finally{W(false)}}
  async function apply(){W(true);M('');try{let r=await api('/obsidian/apply',{method:'POST',body:JSON.stringify({preview_id:preview.preview_id,choice})});M(choice==='keep_server'?'已保留服务端内容。':r.review_required?'已生成待审更新，请重新查看后评分。':r.changed?'分类已更新，正文版本未改变。':'内容没有变化。');P(null);await applied(r.source_id)}catch(e){M(e.message)}finally{W(false)}}
  return <div className="management"><h3>Obsidian 导出与更新</h3>{sourceId&&<p><a href={'/api/sources/'+sourceId+'/obsidian/note'}>下载可编辑笔记</a> · <a href={'/api/sources/'+sourceId+'/obsidian/zip'}>下载笔记与附件 ZIP</a></p>}
    <p>上传从本系统导出的可编辑 Markdown 或 ZIP，先预览再应用。原始证据不可通过此入口替换。</p>
    <input aria-label="选择Obsidian笔记或ZIP" type="file" accept=".md,.zip" onChange={e=>{F(e.target.files?.[0]||null);P(null);C('')}}/><button disabled={!file||working||disabled} onClick={inspect}>上传并预览差异</button>
    {preview&&<div><p>{preview.conflict?'存在冲突，请核对后明确选择。':'已生成预览，尚未修改资料。'}</p>{preview.content_conflict&&<p className="error">正文基准版本已更新。</p>}{preview.classification_conflict&&<p className="error">分类版本冲突：上传基准 {preview.incoming_metadata_revision}，服务端 {preview.current_metadata_revision}；采用上传内容会使用下方上传分类。</p>}<p>标题：{preview.current?.title} → {preview.incoming?.title}</p><p>服务端分类：{[...(preview.current?.classification?.topics||[]),...(preview.current?.classification?.tags||[])].map(x=>x.name).join('、')||'未分类'}</p><p>上传分类：{[...(preview.incoming?.classification?.topics||[]),...(preview.incoming?.classification?.tags||[])].map(x=>x.name).join('、')||'未分类'}</p><div className="compare"><details><summary>服务端笔记</summary><pre>{preview.current?.notes}</pre></details><details open><summary>上传笔记</summary><pre>{preview.incoming?.notes}</pre></details></div>
      <label>处理方式<select value={choice} onChange={e=>C(e.target.value)}><option value="">请选择</option><option value="keep_server">保留服务端，不应用上传内容</option><option value="use_uploaded">采用上传内容并重新审核</option></select></label><button disabled={!choice||working||disabled} onClick={apply}>确认应用预览</button></div>}
    {message&&<p role="status">{message}</p>}
  </div>;
}

export function DouyinPanel({api,opened,pollInterval,disabled}) {
  const [status,S]=useState(null),[jobs,J]=useState([]),[text,T]=useState(''),[rights,R]=useState(false),[message,M]=useState(''),[working,W]=useState(false);
  const [checkResult,setCheckResult]=useState('');
  const configCheck=useRef({running:false,revision:0});
  async function refresh(){
    const {running,revision}=configCheck.current;
    const [s,j]=await Promise.all([running?null:api('/douyin/status'),api('/douyin/jobs')]);
    if(s&&revision===configCheck.current.revision){
      S(s);
      setCheckResult(previous=>previous==='failed'?'':previous);
    }
    J(j.items);
  }
  async function checkDownloadConfig(){
    if(configCheck.current.running)return;
    configCheck.current={running:true,revision:configCheck.current.revision+1};
    setCheckResult('checking');
    try{
      S(await api('/douyin/status'));
      setCheckResult('checked');
    }catch{
      setCheckResult('failed');
    }finally{
      configCheck.current.running=false;
    }
  }
  useEffect(()=>{let alive=true;const update=async()=>{try{if(alive)await refresh()}catch(e){if(alive)M(e.message)}};update();let id=setInterval(update,pollInterval);return()=>{alive=false;clearInterval(id)}},[pollInterval]);
  async function submit(){W(true);M('');try{await api('/douyin/import',{method:'POST',body:JSON.stringify({share_text:text,rights_confirmed:rights})});T('');await refresh();M('下载任务已排队，完成后仍需在任务页明确启动模型处理。')}catch(e){M(e.message)}finally{W(false)}}
  const ready=status&&status.enabled&&status.cookie_configured&&status.resolver_configured;
  const configStatus=!status?'检查中':!status.enabled?'尚未启用':!status.cookie_configured?'缺少私密 Cookie 配置':!status.resolver_configured?'缺少独立解析环境':'配置存在，Cookie 有效性待实际下载验证';
  const checkMessage=checkResult==='checking'?'正在检查下载配置…'
    :checkResult==='failed'?'下载配置检查失败，请稍后重试。'
    :`${checkResult==='checked'?'配置检查完成':'配置检查'}：${configStatus}`;
  return <div className="management"><h3>抖音分享链接</h3><p>粘贴单条分享文本或链接。仅获取允许下载的作品；失败时可直接上传有权使用的 MP4。</p>
    <p role="status">{checkMessage}</p>
    <button type="button" disabled={checkResult==='checking'} onClick={checkDownloadConfig}>重新检查下载配置</button>
    <label>抖音分享文本<textarea value={text} onChange={e=>T(e.target.value)} placeholder="https://v.douyin.com/.../"/></label><label><input type="checkbox" checked={rights} onChange={e=>R(e.target.checked)}/> 我确认有权处理此作品，并仅下载平台允许的内容</label>
    <button disabled={disabled||working||!ready||!rights||!text.trim()} onClick={submit}>创建下载任务</button><p>请在运行知识库服务的机器上配置私密 Cookie。下载后需手动启动模型处理。</p>
    {message&&<p role="status">{message}</p>}{jobs.map(j=><article key={j.id}><strong>下载任务 {j.work_id||j.id}</strong><p>{({queued:'排队中',running:'下载中',succeeded:'已导入，待启动处理',failed:'下载失败',needs_attention:'需要确认恢复'})[j.status]||j.status}</p>{j.error_code&&<p>{douyinErrorText(j.error_code)}；可上传 MP4 兜底。</p>}{['failed','needs_attention'].includes(j.status)&&<button disabled={working||!ready} onClick={async()=>{try{await api('/douyin/jobs/'+j.id+'/retry',{method:'POST',body:'{}'});await refresh()}catch(e){M(e.message)}}}>重试下载</button>}{j.source_id&&<button onClick={()=>opened(j.source_id)}>查看导入资料</button>}</article>)}
  </div>;
}
