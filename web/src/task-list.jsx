import React, {useEffect, useMemo, useRef, useState} from 'react';
import {compareTime, TimeSortButton} from './time-sort';
import {errorText, formatDate, progressText, statusText, taskControls, taskActionLabel, uploadRecoveryText} from './helpers';

const emptyFilters={query:'',status:'',kind:''};
const statusOptions={
  waiting:'待开始',queued:'已排队',running:'处理中',completed:'已完成',
  attention:'失败／需要关注',cancelled:'已取消',
};
const actionNames={start:'开始',resume:'恢复',retry:'重试',cancel:'取消'};
const htmlModes={preview:'离线正文预览',model:'模型摘要与笔记'};
const failureReasons={
  source_deleted:'来源已移入回收站',
  source_integrity:'原始文件校验失败',
  missing_model_credentials:'缺少模型凭据',
  media_tool_missing:'未找到视频检测工具',
  empty_output:'未提取到有效正文',
  invalid_summary_json:'模型返回格式无效',
  invalid_size:'文件大小超出限制',
  disk_low:'磁盘空间不足',
  recovery_media_missing:'原任务的音频和画面缓存缺失，无法继续。',
  provider_timeout:'等待模型响应超时',
  provider_network_error:'模型请求连接中断',
  provider_dns_failed:'无法解析模型服务地址',
  provider_response_invalid:'模型响应无法解析',
  budget_invalid_or_exceeded:'任务或累计预算不足，无法自动重试。',
  favorites_budget_exceeded:'收藏转换预算不足，无法自动重试。',
  empty_or_truncated_model_output:'模型输出为空或被截断，旧记录无法区分',
  model_output_empty:'模型输出为空',
  model_output_truncated:'模型输出被截断',
  model_output_invalid:'模型响应格式无效',
};

function taskStatus(task, queuedForProcessing) {
  if(task.status==='queued'||task.status==='pending')return queuedForProcessing?'queued':'waiting';
  if(task.status==='succeeded')return 'completed';
  if(task.status==='failed'||task.status==='needs_attention')return 'attention';
  return task.status;
}

function TaskRow({task,item,controls,config,busy,paid,open,onAction,expanded,toggle}) {
  const [recoveryAgreement,setRecoveryAgreement]=useState(null);
  const {mode,action,queuedForProcessing}=controls;
  const video=['video','mp4'].includes(item?.kind);
  const kind=video?'视频':item?.kind==='html'?'网页':'';
  const title=item?.title||item?.original_name||'来源资料不可用';
  const paidNeeded=video||mode==='model';
  const enabled=video?config.live_video_enabled:mode!=='model'||config.live_html_enabled;
  const status=taskStatus(task,queuedForProcessing);
  const label=status==='attention'?statusText(task.status):statusOptions[status]||statusText(task.status);
  const progress=progressText(task.progress,task.status);
  const stage=task.stage?statusText(task.stage):'';
  const problem=task.resume_blocked_reason||task.error_code||task.dispatch?.error_code;
  const reason=problem&&(uploadRecoveryText(task,problem)||failureReasons[problem]||errorText(400,problem));
  const diagnostic=task.model_diagnostic;
  const diagnosticReason=diagnostic && (failureReasons[diagnostic.code] || errorText(400,diagnostic.code));
  const summary=diagnosticReason||(problem?(reason.startsWith('操作失败：')?'查看详情了解原因':reason):'');
  const detailId='task-detail-'+task.id;
  const recovery=task.model_recovery;
  const recoveryKey=recovery&&JSON.stringify([task.id,recovery.stage,recovery.attempt,recovery.amount,recovery.mode]);
  return <article className="task-grid task-item">
    <div className="task-identity">
      <strong>{title}</strong>
      {(kind||item?.deleted)&&<span className="muted">{[kind,task.reprocess&&'重新转写',item?.deleted&&'来源在回收站'].filter(Boolean).join(' · ')}</span>}
    </div>
    <div className="task-state">
      <strong data-status={status}>{label}</strong>
      {summary?<span className="task-line" title={summary}>{summary}</span>
        :status==='running'?<span>{[stage,progress].filter(Boolean).join(' · ')}</span>
        :stage&&status==='completed'?<span className="muted">{stage}</span>:null}
    </div>
    <div className="task-updated muted">
      <span className="task-mobile-label">更新时间 </span>
      {task.updated_at?<time dateTime={task.updated_at}>{formatDate(task.updated_at,config.display_timezone)}</time>:'—'}
    </div>
    <div className="task-actions">
      {recovery&&!expanded&&item&&!item.deleted&&!task.archived&&<button type="button" onClick={toggle}>处理模型请求</button>}
      {action&&(action==='cancel'||item&&!item.deleted)&&<button type="button" disabled={busy||(action!=='cancel'&&paidNeeded&&(!paid||!enabled))}
        onClick={()=>onAction(task.id,action,action==='cancel'?{}:{allow_paid:paid,processing_mode:video?'preview':mode})}>{taskActionLabel(task,action)||actionNames[action]}</button>}
      {item&&!item.deleted&&<button type="button" onClick={()=>open(item.id,{versionId:task.view_version_id})}>{task.viewing_history?'查看旧版本':task.view_version_id||task.status!=='succeeded'?'查看资料':'查看当前资料'}</button>}
      {(task.archived||task.can_archive)&&<button type="button" disabled={busy}
        onClick={()=>onAction(task.id,task.archived?'unarchive':'archive',{})}>{task.archived?'取消归档':'归档'}</button>}
      <button type="button" aria-expanded={expanded} aria-controls={expanded?detailId:undefined} onClick={toggle}>{expanded?'收起详情':'详情'}</button>
    </div>
    {expanded&&<dl className="task-details" id={detailId}>
      {item?.original_name&&<><dt>原文件名</dt><dd>{item.original_name}</dd></>}
      <dt>任务 ID</dt><dd>{task.id}</dd>
      <dt>创建时间</dt><dd>{formatDate(task.created_at,config.display_timezone)||'—'}</dd>
      {stage&&<><dt>阶段</dt><dd>{stage}</dd></>}
      <dt>进度</dt><dd>{queuedForProcessing||task.dispatch?.state==='pending'?'已加入处理队列':progress}</dd>
      {item?.kind==='html'&&<><dt>处理方式</dt><dd>{htmlModes[mode]}</dd></>}
      {problem&&<><dt>原因</dt><dd>{reason} <code>{problem}</code></dd></>}
      {diagnosticReason&&<><dt>模型失败原因</dt><dd>{diagnosticReason}</dd></>}
      {diagnostic&&<><dt>结束原因</dt><dd>{diagnostic.finish_reason??'未记录'}</dd>
        <dt>输出字符数</dt><dd>{diagnostic.output_chars??'未记录'}</dd>
        <dt>Token 用量</dt><dd>{[
          diagnostic.usage?.prompt_tokens!=null&&`输入 ${diagnostic.usage.prompt_tokens}`,
          diagnostic.usage?.completion_tokens!=null&&`输出 ${diagnostic.usage.completion_tokens}`,
          diagnostic.usage?.total_tokens!=null&&`合计 ${diagnostic.usage.total_tokens}`,
        ].filter(Boolean).join(' · ')||'未记录'}</dd></>}
      {diagnostic?.provider_request_id&&<><dt>模型请求号</dt><dd>{diagnostic.provider_request_id}</dd></>}
      {recovery&&item&&!item.deleted&&!task.archived&&<><dt>继续处理</dt><dd>
        <p>中断步骤 {statusText(recovery.stage)}{!diagnosticReason&&recovery.reason&&` · ${failureReasons[recovery.reason]||recovery.reason}`}</p>
        {['budget_invalid_or_exceeded','favorites_budget_exceeded'].includes(task.error_code)&&<p>{failureReasons[task.error_code]}</p>}
        {recovery.mode==='restore'?<p>{recovery.authorized_amount
          ?`此步骤已授权重试，额外费用上限 ¥${recovery.authorized_amount}。`
          :'已保存模型结果，可以从该步骤继续。后续步骤按原预算处理。'}</p>:<>
          <p>当前没有可用的模型结果，原请求可能已计费。重试此步骤会增加最高 ¥{recovery.amount} 的费用预留，后续步骤按原预算处理。</p>
          <label><input type="checkbox" checked={recoveryAgreement===recoveryKey} onChange={event=>setRecoveryAgreement(event.target.checked?recoveryKey:null)}/> 我同意重新请求此步骤产生的费用</label>
        </>}
        <button type="button" disabled={busy||!enabled||(recovery.mode==='retry'&&recoveryAgreement!==recoveryKey)} onClick={()=>{
          setRecoveryAgreement(null);
          onAction(task.id,'recover-model',{stage:recovery.stage,attempt:recovery.attempt,mode:recovery.mode,allow_paid:recovery.mode==='retry',amount:recovery.amount});
        }}>{recovery.mode==='restore'?(recovery.authorized_amount?'继续已授权的重试':'使用已保存结果继续'):'确认费用并重试此步骤'}</button>
      </dd></>}
    </dl>}
  </article>;
}

export function TaskList({active,loaded,tasks,sources,config,busy,open,onAction}) {
  const [archived,setArchived]=useState(false);
  const [timeDirection,setTimeDirection]=useState('desc');
  const [filters,setFilters]=useState(emptyFilters);
  const [paid,setPaid]=useState(false);
  const [htmlMode,setHtmlMode]=useState('preview');
  const [expandedId,setExpandedId]=useState(null);
  const listRef=useRef(null);
  const sourcesById=useMemo(()=>new Map(sources.map(source=>[source.id,source])),[sources]);
  const query=filters.query.trim().toLocaleLowerCase();
  const filtered=useMemo(()=>tasks
    .filter(task=>Boolean(task.archived)===archived)
    .map(task=>({
      task,item:task.source||sourcesById.get(task.source_id),
      controls:taskControls(task,htmlMode),
    }))
    .filter(({task,item,controls})=>{
      const kind=item?.kind==='mp4'?'video':item?.kind;
      return (!filters.status||taskStatus(task,controls.queuedForProcessing)===filters.status)
        &&(!filters.kind||kind===filters.kind)
        &&(!query||[item?.title,item?.original_name,task.id].some(text=>text?.toLocaleLowerCase().includes(query)));
    })
    .sort((a,b)=>compareTime(a.task.updated_at,b.task.updated_at,timeDirection)||b.task.id.localeCompare(a.task.id)),
    [tasks,sourcesById,archived,htmlMode,filters.status,filters.kind,query,timeDirection]);
  const filtering=!!(query||filters.status||filters.kind);

  useEffect(()=>{
    if(listRef.current)listRef.current.scrollTop=0;
  },[archived,filters]);

  function setFilter(key,value){setFilters(previous=>({...previous,[key]:value}));}
  function toggleTimeDirection(){
    setTimeDirection(value=>value==='asc'?'desc':'asc');
    if(listRef.current)listRef.current.scrollTop=0;
  }

  return <section className="list-page" hidden={!active}>
    <div className="list-page-controls task-list-controls">
      <div className="page-heading">
        <h1 data-page-title tabIndex={-1}>任务</h1>
        <div className="task-archive-options" role="group" aria-label="任务范围">
          <button type="button" aria-pressed={!archived} onClick={()=>setArchived(false)}>未归档</button>
          <button type="button" aria-pressed={archived} onClick={()=>setArchived(true)}>已归档</button>
        </div>
      </div>
      <div className="task-filters">
        <label className="task-search">查找<input type="search" value={filters.query}
          onChange={event=>setFilter('query',event.target.value)} placeholder="资料标题、原文件名或任务 ID"/></label>
        <label>状态<select value={filters.status} onChange={event=>setFilter('status',event.target.value)}>
          <option value="">全部状态</option>
          {Object.entries(statusOptions).map(([value,label])=><option key={value} value={value}>{label}</option>)}
        </select></label>
        <label>类型<select value={filters.kind} onChange={event=>setFilter('kind',event.target.value)}>
          <option value="">全部类型</option><option value="video">视频</option><option value="html">网页</option>
        </select></label>
        <button type="button" disabled={!filters.query&&!filtering} onClick={()=>setFilters(emptyFilters)}>清空筛选</button>
      </div>
      <div className="task-list-summary">
        <span className="muted" role="status">{loaded?`匹配 ${filtered.length} 条任务`:'正在读取任务…'}</span>
        {!!filtered.length&&<TimeSortButton label="更新时间" direction={timeDirection} onClick={toggleTimeDirection} mobile/>}
        {!archived&&<details className="task-processing">
          <summary>处理设置{paid?' · 已同意模型费用':''}</summary>
          <div className="actions task-processing-options">
            <label><input type="checkbox" checked={paid} onChange={event=>setPaid(event.target.checked)}/>我同意所选视频或网页模型处理产生费用</label>
            <label>HTML 处理方式<select value={htmlMode} onChange={event=>setHtmlMode(event.target.value)}>
              <option value="preview">离线正文预览（无模型费用）</option>
              <option value="model" disabled={!config.live_html_enabled}>模型摘要与笔记（需本人审核）</option>
            </select></label>
          </div>
          {!config.live_video_enabled&&<p className="muted">视频处理当前未启用。</p>}
          {!config.live_html_enabled&&<p className="muted">网页模型处理未启用，离线预览不产生 AI 摘要。</p>}
        </details>}
      </div>
    </div>
    <div className="list-scroll task-list" ref={listRef} role="region" aria-label={archived?'已归档任务列表':'未归档任务列表'} tabIndex={0}>
      {filtered.length>0&&<div className="task-grid task-table-heading">
        <span>资料名称</span><span>状态 / 进度</span>
        <TimeSortButton label="更新时间" direction={timeDirection} onClick={toggleTimeDirection}/>
        <span>操作</span>
      </div>}
      {loaded&&!filtered.length&&<p>{filtering?'没有符合筛选条件的任务。':archived?'暂无已归档任务。':'暂无任务，可先导入资料。'}</p>}
      {filtered.map(({task,item,controls})=><TaskRow key={task.id} task={task} item={item} controls={controls}
        config={config} busy={busy} paid={paid} open={open} onAction={onAction}
        expanded={expandedId===task.id} toggle={()=>setExpandedId(id=>id===task.id?null:task.id)}/>)}
    </div>
  </section>;
}
