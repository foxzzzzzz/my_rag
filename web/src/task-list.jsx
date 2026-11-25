import React, {useEffect, useMemo, useRef, useState} from 'react';
import {canReauthorize, ReauthorizationDialog} from './budget-panel';
import {compareTime, TimeSortButton} from './time-sort';
import {MediaTypeBadge} from './media-type-badge';
import {errorText, formatDate, formatMediaSize, progressText, statusText, taskControls, taskActionLabel, uploadRecoveryText} from './helpers';

const emptyFilters={query:'',status:'',kind:''};
const statusOptions={
  waiting:'待开始',queued:'已排队',running:'处理中',completed:'已完成',
  attention:'失败／需要关注',cancelled:'已取消',
};
const actionNames={start:'开始',resume:'恢复',retry:'重试',cancel:'取消'};
const htmlModes={preview:'离线正文预览',model:'模型摘要与笔记'};
const failureReasons={
  asr_upload_limit_exceeded:'音频大小超过当前上传上限',
  file_too_large:'音频文件超过上传大小限制',
  invalid_frame:'画面帧无效，视频抽帧失败。',
  media_workdir_unverified:'视频抽帧未完成，媒体缓存不完整。',
  media_cache_changed:'媒体缓存发生变化，请检查缓存后再处理。',
  media_command_failed:'媒体处理命令失败，请检查文件和处理环境。',
  media_timeout:'媒体准备超时，请检查后台负载后再处理。',
  resource_limit:'服务器剩余磁盘空间或可用内存不足。',
  media_workdir_busy:'媒体准备尚未释放工作目录。',
  media_rebuild_interrupted:'媒体缓存重建中断。',
  media_missing_video:'原文件中没有可用的画面轨。',
  media_missing_duration:'无法读取原视频的时长。',
  media_video_timeline_invalid:'无法确定画面轨的有效时间范围。',
  audio_not_full_length:'提取的音频与原音轨时长不符。',
  empty_frames:'未提取到可用于分析的画面。',
  asr_remote_failed:'语音识别服务未返回可用转录。',
  asr_subtask_failed:'语音识别未生成可用转录。',
  asr_pending:'语音识别仍在处理，可继续查询结果。',
  asr_no_speech:'未检测到有效语音，可仅按画面和原文继续。',
  asr_empty:'语音识别返回了空转录。',
  attempts_exhausted:'重试次数已用尽，请检查失败原因。',
  source_deleted:'来源已移入回收站',
  source_integrity:'原始文件校验失败',
  missing_model_credentials:'缺少模型凭据',
  media_tool_missing:'未找到视频检测工具',
  empty_output:'未提取到有效正文',
  invalid_summary_json:'模型返回格式无效',
  invalid_summary_json_syntax:'模型返回的摘要 JSON 语法无效',
  invalid_summary_schema:'模型返回的摘要结构不符合要求',
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
  if(queuedForProcessing)return 'queued';
  if(task.status==='queued'||task.status==='pending')return queuedForProcessing?'queued':'waiting';
  if(task.status==='succeeded')return 'completed';
  if(task.status==='failed'||task.status==='needs_attention')return 'attention';
  return task.status;
}

function RetryConsentHint({taskId,label='重试',prompt='重试前，请在「处理设置」勾选同意模型费用。'}) {
  const hint=useRef(null);
  const hintId='task-retry-hint-'+taskId;

  function show(event) {
    if(!hint.current.matches(':popover-open'))hint.current.showPopover({source:event.currentTarget});
  }

  function hide() {
    if(hint.current.matches(':popover-open'))hint.current.hidePopover();
  }

  return <span className="task-retry-with-hint">
    <button type="button" disabled aria-describedby={hintId}>{label}</button>
    <span className="task-retry-hint-target" onPointerLeave={event=>{
      if(event.pointerType==='mouse'&&!event.currentTarget.querySelector(':focus-visible'))hide();
    }}>
      <button type="button" className="task-retry-hint-icon" aria-label="查看重试提示" aria-describedby={hintId}
        popoverTarget={hintId}
        onPointerEnter={event=>{if(event.pointerType==='mouse')show(event);}}
        onFocus={event=>{if(event.currentTarget.matches(':focus-visible'))show(event);}} onBlur={hide}>
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
          <circle cx="8" cy="8" r="6.25"/>
          <path d="M8 4.75v3.75m0 2.5v.25" strokeLinecap="round"/>
        </svg>
      </button>
      <span ref={hint} id={hintId} className="task-retry-hint" role="tooltip" popover="auto">
        {prompt}
      </span>
    </span>
  </span>;
}

function TaskRow({task,item,controls,config,busy,paid,open,onAction,onBudget,onProcessingSettings,onReauthorize,expanded,toggle}) {
  const [recoveryAgreement,setRecoveryAgreement]=useState(null);
  const {mode,action:defaultAction,queuedForProcessing}=controls;
  const video=['video','mp4'].includes(item?.kind);
  const album=item?.kind==='douyin_album';
  const action=album&&defaultAction==='start'&&!task.dispatch?undefined:defaultAction;
  const html=item?.kind==='html';
  const knownKind=video||album||html;
  const metadata=[task.reprocess&&'重新转写',item?.deleted&&'来源在回收站'].filter(Boolean).join(' · ');
  const title=item?.title||item?.original_name||'来源资料不可用';
  const paidNeeded=video||(!album&&mode==='model');
  const enabled=video||album?config.live_video_enabled:mode!=='model'||config.live_html_enabled;
  const showAction=action&&(action==='cancel'||item&&!item.deleted);
  const retryNeedsConsent=showAction&&action==='retry'&&paidNeeded&&enabled&&!paid;
  const status=taskStatus(task,queuedForProcessing);
  const label=status==='attention'?statusText(task.status):statusOptions[status]||statusText(task.status);
  const progress=progressText(task.progress,task.status);
  const stageText=value=>album&&/^vision-\d+$/.test(value)?`图文识别 · 图 ${value.slice(7)}`:statusText(value);
  const stage=task.stage?stageText(task.stage):'';
  const diagnostic=task.model_diagnostic;
  const currentError=task.dispatch?.error_code||task.error_code;
  const recoveryLimit=task.resume_blocked_reason;
  const problem=task.failure_code||(currentError&&currentError!=='unknown_submission'?currentError:diagnostic?.code||currentError||recoveryLimit);
  const reason=problem&&(uploadRecoveryText(task,problem)||failureReasons[problem]||errorText(400,problem));
  const previousModelError=diagnostic?.code&&diagnostic.code!==problem?diagnostic.code:null;
  const audioFits=task.processing_limit?.actual!=null&&task.processing_limit.actual<=task.processing_limit.limit;
  const summary=audioFits?'音频符合当前上传上限':reason&&reason.startsWith('操作失败：')&&diagnostic?.code!==problem?'查看详情了解原因':reason;
  const budgetBlocked=problem==='budget_invalid_or_exceeded'||problem==='favorites_budget_exceeded';
  const budgetBlock=task.budget_block;
  const detailId='task-detail-'+task.id;
  const recovery=task.model_recovery;
  const albumTextRetry=recovery?.mode==='retry-album-text';
  const videoRecovery=!queuedForProcessing&&['visual-only','rebuild-media'].includes(task.video_recovery?.mode)?task.video_recovery:null;
  const visualOnly=videoRecovery?.mode==='visual-only';
  const recoveryAction=visualOnly?'仅按画面和原文继续':'重建缓存并重试';
  const reauthorization=task.favorites_reauthorization;
  const showReauthorization=task.status==='failed'&&video&&enabled&&!item.deleted&&!task.archived&&canReauthorize(reauthorization);
  const videoNextStep=albumTextRetry?null:videoRecovery?(visualOnly
    ? '可以用已提取的画面和来源原文生成待审核内容，语音栏会说明转录未完成。若原片应有人声，请先检查音轨。'
    : '确认后会保留原片及旧缓存，并重新提取可用画面。')
    :showReauthorization?'请确认这条视频的新授权金额。'
    :task.retry_blocked_reason==='favorites_budget_exceeded'?null
    :task.retry_blocked_reason==='attempts_exhausted'?'已达到常规尝试上限，请根据当前原因检查原片或处理环境。'
    :task.retry_blocked_reason==='unknown_submission'?'先核对原模型请求的状态和费用预留。'
    :task.retry_blocked_reason?'检查原片是否能完整播放。如需更换原片，请重新导入可用版本。':null;
  const recoveryKey=recovery&&JSON.stringify([task.id,recovery.stage,recovery.attempt,recovery.amount,recovery.mode,recovery.quote_key]);
  return <article className="task-grid task-item">
    <div className="task-identity">
      <strong>{title}</strong>
      {(knownKind||item?.deleted)&&<span className="muted">
        <MediaTypeBadge kind={item?.kind} includeWeb={html} variant="text"/>
        {knownKind&&metadata?' · ':null}{metadata}
      </span>}
    </div>
    <div className="task-state">
      <strong data-status={status}>{label}</strong>
      {status==='attention'&&summary?<span className={`task-line${videoNextStep?' task-line--diagnosis':''}`} title={summary}>{summary}</span>
        :status==='running'?<span>{[stage,progress].filter(Boolean).join(' · ')}</span>
        :stage&&status==='completed'?<span className="muted">{stage}</span>:null}
      {task.conversion_wait&&<span className="muted">{task.conversion_wait.code==='favorites_daily_count_limit'?'等待每日转换名额':task.conversion_wait.code==='favorites_daily_budget_limit'?'等待每日转换预算':'等待转换'}{task.conversion_wait.required_cny!=null&&` · 需要 ¥${task.conversion_wait.required_cny}，可用 ¥${task.conversion_wait.available_cny}`}</span>}
      {task.favorites_reauthorization&&<span className="muted">原授权 ¥{task.favorites_reauthorization.authorized_cny}
        {task.favorites_reauthorization.required_cny!=null&&<> · 所需预留 ¥{task.favorites_reauthorization.required_cny}</>}
      </span>}
      {status==='attention'&&task.attempts>=task.max_attempts&&task.retry_blocked_reason&&
        <span className="muted">已尝试 {task.attempts} 次 · 常规上限 {task.max_attempts} 次</span>}
      {status==='attention'&&budgetBlocked&&budgetBlock&&<span className="muted">本次需预留 ¥{budgetBlock.required_cny}，项目当前可用 ¥{budgetBlock.available_cny}</span>}
    </div>
    <div className="task-updated muted">
      <span className="task-mobile-label">更新时间 </span>
      {task.updated_at?<time dateTime={task.updated_at}>{formatDate(task.updated_at,config.display_timezone)}</time>:'—'}
    </div>
    <div className="task-actions">
      {recovery&&!expanded&&item&&!item.deleted&&!task.archived&&<button type="button" onClick={toggle}>{albumTextRetry?'仅重试文本汇总':'处理模型请求'}</button>}
      {showReauthorization&&<button type="button" disabled={busy}
        onClick={()=>onReauthorize({...reauthorization,task_id:task.id,title})}>重新授权并重试</button>}
      {(task.conversion_wait||reauthorization||(status==='attention'&&budgetBlocked))&&
        <button type="button" onClick={onBudget}>查看预算</button>}
      {videoRecovery&&item&&!item.deleted&&!task.archived&&(enabled&&!paid
        ?<RetryConsentHint taskId={task.id} label={recoveryAction} prompt="继续处理前，请在「处理设置」勾选同意模型费用。"/>
        :<button type="button" disabled={busy||!enabled} onClick={()=>onAction(task.id,videoRecovery.mode,{allow_paid:true})}>{recoveryAction}</button>)}
      {retryNeedsConsent?<RetryConsentHint taskId={task.id}/>:showAction&&<button type="button" disabled={busy||(action!=='cancel'&&paidNeeded&&(!paid||!enabled))}
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
      {(stage||task.failure_stage)&&<><dt>{task.failure_stage?'失败阶段':'阶段'}</dt><dd>{task.failure_stage?stageText(task.failure_stage):stage}</dd></>}
      <dt>进度</dt><dd>{queuedForProcessing||task.dispatch?.state==='pending'?'已加入处理队列':progress}</dd>
      {item?.kind==='html'&&<><dt>处理方式</dt><dd>{htmlModes[mode]}</dd></>}
      {problem&&<><dt>{audioFits?'上次失败原因':'当前原因'}</dt><dd>{reason} <code>{problem}</code></dd></>}
      {task.processing_limit&&<><dt>转写音频上限</dt><dd>
        {task.processing_limit.actual != null && <>音频 {formatMediaSize(task.processing_limit.actual)} · </>}
        当前上限 {formatMediaSize(task.processing_limit.limit)}
        {task.processing_limit.actual != null && (task.processing_limit.actual > task.processing_limit.limit ? ' · 超过当前上限' : ' · 当前上限允许此音频')}{' '}
        <button type="button" onClick={()=>onProcessingSettings(task.processing_limit.key)}>查看音频上限</button>
      </dd></>}
      {videoNextStep&&<><dt>下一步</dt><dd>{videoNextStep}</dd></>}
      {previousModelError&&<><dt>上次模型失败原因</dt><dd>{failureReasons[previousModelError]||errorText(400,previousModelError)}</dd></>}
      {recoveryLimit&&recoveryLimit!==problem&&!(task.processing_limit&&recoveryLimit==='asr_upload_limit_exceeded')&&!(albumTextRetry&&recoveryLimit==='unknown_submission')&&
        <><dt>恢复限制</dt><dd>{uploadRecoveryText(task,recoveryLimit)||errorText(400,recoveryLimit)} <code>{recoveryLimit}</code></dd></>}
      {!albumTextRetry&&task.retry_blocked_reason&&task.retry_blocked_reason!==problem&&<><dt>重试限制</dt><dd>{failureReasons[task.retry_blocked_reason]||errorText(400,task.retry_blocked_reason)} <code>{task.retry_blocked_reason}</code></dd></>}
      {task.attempts!=null&&<><dt>尝试次数</dt><dd>{task.attempts} 次{task.max_attempts!=null&&` · 常规上限 ${task.max_attempts} 次`}</dd></>}
      {videoRecovery&&<><dt>恢复费用</dt><dd>{videoRecovery.amount_cny?`剩余步骤预计预留 ¥${videoRecovery.amount_cny}。`:'沿用项目和来源已有预算限制。'}{!paid&&' 请先在「处理设置」勾选同意模型费用。'}</dd></>}
      {task.asr_provider_code&&<><dt>转录服务错误码</dt><dd><code>{task.asr_provider_code}</code></dd></>}
      {diagnostic&&<><dt>结束原因</dt><dd>{diagnostic.finish_reason??'未记录'}</dd>
        <dt>输出字符数</dt><dd>{diagnostic.output_chars??'未记录'}</dd>
        <dt>Token 用量</dt><dd>{[
          diagnostic.usage?.prompt_tokens!=null&&`输入 ${diagnostic.usage.prompt_tokens}`,
          diagnostic.usage?.completion_tokens!=null&&`输出 ${diagnostic.usage.completion_tokens}`,
          diagnostic.usage?.total_tokens!=null&&`合计 ${diagnostic.usage.total_tokens}`,
        ].filter(Boolean).join(' · ')||'未记录'}</dd></>}
      {diagnostic?.provider_request_id&&<><dt>模型请求号</dt><dd>{diagnostic.provider_request_id}</dd></>}
      {recovery&&item&&!item.deleted&&!task.archived&&<><dt>继续处理</dt><dd>
        <p>中断步骤 {stageText(recovery.stage)}{!diagnostic&&recovery.reason&&recovery.reason!==problem&&` · ${failureReasons[recovery.reason]||recovery.reason}`}</p>
        {albumTextRetry?<><p>复用已保存的 {recovery.image_count} 张图片识别结果，仅重新生成精简文本汇总。</p>
          <p>本次额外费用上限 ¥{recovery.ceiling_cny}。</p>
          <p>原请求的费用预留仍保留。</p>
          <label><input type="checkbox" checked={recoveryAgreement===recoveryKey} onChange={event=>setRecoveryAgreement(event.target.checked?recoveryKey:null)}/> 我同意本次文本汇总的额外费用</label>
        </>:recovery.mode==='restore'?<p>{recovery.authorized_amount
          ?`此步骤已授权重试，额外费用上限 ¥${recovery.authorized_amount}。`
          :'已保存模型结果，可以从该步骤继续。后续步骤按原预算处理。'}</p>:<>
          <p>当前没有可用的模型结果，原请求可能已计费。重试此步骤会增加最高 ¥{recovery.amount} 的费用预留，后续步骤按原预算处理。</p>
          <label><input type="checkbox" checked={recoveryAgreement===recoveryKey} onChange={event=>setRecoveryAgreement(event.target.checked?recoveryKey:null)}/> 我同意重新请求此步骤产生的费用</label>
        </>}
        <button type="button" disabled={busy||!enabled||((recovery.mode==='retry'||albumTextRetry)&&recoveryAgreement!==recoveryKey)} onClick={()=>{
          setRecoveryAgreement(null);
          onAction(task.id,'recover-model',{stage:recovery.stage,attempt:recovery.attempt,mode:recovery.mode,allow_paid:recovery.mode==='retry'||albumTextRetry,amount:recovery.amount,...(albumTextRetry?{quote_key:recovery.quote_key}:{})});
        }}>{albumTextRetry?'确认费用并仅重试文本汇总':recovery.mode==='restore'?(recovery.authorized_amount?'继续已授权的重试':'使用已保存结果继续'):'确认费用并重试此步骤'}</button>
      </dd></>}
    </dl>}
  </article>;
}

export function TaskList({active,loaded,tasks,sources,config,busy,open,onAction,onBudget,onProcessingSettings,api,onSaved}) {
  const [authorization,setAuthorization]=useState(null);
  const [authorizationMessage,setAuthorizationMessage]=useState('');
  const [archived,setArchived]=useState(false);
  const [timeDirection,setTimeDirection]=useState('desc');
  const [filters,setFilters]=useState(emptyFilters);
  const [paid,setPaid]=useState(false);
  const [htmlMode,setHtmlMode]=useState('preview');
  const [expandedId,setExpandedId]=useState(null);
  const listRef=useRef(null);
  useEffect(()=>{if(!active)setAuthorization(null);},[active]);
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

  function openAuthorization(quote) {
    setAuthorization(quote);
    setAuthorizationMessage('');
  }

  function authorizationSucceeded(_,message) {
    setAuthorizationMessage(message);
    onSaved().catch(()=>setAuthorizationMessage(message+'暂时无法刷新列表，请稍后刷新。'));
  }

  return <section className="list-page" hidden={!active}>
    {active&&authorization&&<ReauthorizationDialog authorization={authorization} api={api} disabled={busy}
      onClose={()=>setAuthorization(null)} onSuccess={authorizationSucceeded}/>}
    <div className="list-page-controls task-list-controls">
      <div className="page-heading">
        <h1 data-page-title tabIndex={-1}>任务</h1>
        <div className="task-archive-options" role="group" aria-label="任务范围">
          <button type="button" aria-pressed={!archived} onClick={()=>setArchived(false)}>未归档</button>
          <button type="button" aria-pressed={archived} onClick={()=>setArchived(true)}>已归档</button>
        </div>
      </div>
      {authorizationMessage&&<p role="status">{authorizationMessage}</p>}
      <div className="task-filters">
        <label className="task-search">查找<input type="search" value={filters.query}
          onChange={event=>setFilter('query',event.target.value)} placeholder="资料标题、原文件名或任务 ID"/></label>
        <label>状态<select value={filters.status} onChange={event=>setFilter('status',event.target.value)}>
          <option value="">全部状态</option>
          {Object.entries(statusOptions).map(([value,label])=><option key={value} value={value}>{label}</option>)}
        </select></label>
        <label>类型<select value={filters.kind} onChange={event=>setFilter('kind',event.target.value)}>
          <option value="">全部类型</option><option value="video">视频</option><option value="html">网页</option><option value="douyin_album">图文</option>
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
        config={config} busy={busy} paid={paid} open={open} onAction={onAction} onBudget={onBudget} onProcessingSettings={onProcessingSettings} onReauthorize={openAuthorization}
        expanded={expandedId===task.id} toggle={()=>setExpandedId(id=>id===task.id?null:task.id)}/>)}
    </div>
  </section>;
}
