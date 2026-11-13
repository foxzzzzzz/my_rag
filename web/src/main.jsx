import React, {useEffect, useMemo, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {RagPanel} from './rag';
import {hasOlderSourceReviews} from './rag-state';
import {guardedJson, logoutLocal, acquireWriter, releaseWriter, epochCurrent} from './auth-client';
import {ClassificationEditor, ObsidianPanel, DouyinPanel} from './management';
import {FavoritesPanel} from './favorites-panel';
import {CatalogManager} from './catalog-manager';
import {LibraryView} from './library-view';
import {TaskList} from './task-list';
import {isUnclassifiedSource, UNCLASSIFIED_TOPIC} from './management-helpers';
import {DocumentView} from './document-view';
import {connectionText, validReview, errorText, textValue, uploadError, statusText, formatDate, htmlBodyPreview} from './helpers';
import {draftKey, emptyReviewDraft, updateReviewDraft, saveReviewDraft, reviewDraftSaved, canSubmitReview} from './review-drafts';
import ui from './ui-config.json';
import './style.css';

const fields = {title:'标题', summary:'摘要', notes:'笔记', body:'正文', transcript:'语音转录', visual:'画面证据'};
const isVideo = kind => ['video','mp4'].includes(kind);
const inputDraft = () => emptyReviewDraft(ui.default_reviewer);
const emptyLibraryFilters = {q:'',kind:'',review:'',tags:[]};
const detailPath = (id, versionId) => '/sources/'+id+(versionId?'?version_id='+encodeURIComponent(versionId):'');

function App() {
  const [session, setSession] = useState(null), [connection, setConnection] = useState('connecting');
  const [loginRequired,setLoginRequired]=useState(false), [password,setPassword]=useState(''), [authEnabled,setAuthEnabled]=useState(false);
  const [page, setPage] = useState('library'), [sources, setSources] = useState([]), [tasks, setTasks] = useState([]), [catalog, setCatalog] = useState([]);
  const [trash, setTrash] = useState({items:[], retention_days:null});
  const [detail, setDetail] = useState(null), [topic, setTopic] = useState('');
  const [selectedVersion, setSelectedVersion] = useState(null);
  const [libraryFilters,setLibraryFilters]=useState(emptyLibraryFilters);
  const [dataLoaded,setDataLoaded] = useState(false);
  const [reviewEpoch,setReviewEpoch] = useState(0), [reviewPending,setReviewPending] = useState(false);
  const [error, setError] = useState(''), [busy, setBusy] = useState(false), [message, setMessage] = useState('');
  const [confirmation,setConfirmation] = useState(null);
  const dialogRef=useRef(null), dialogOpener=useRef(null);
  const [drafts, setDrafts] = useState({}), [edits, setEdits] = useState({}), [stale, setStale] = useState(false);
  const [tab, setTab] = useState('summary'), [sourcePaid, setSourcePaid] = useState(false);
  const videoReprocessRequest = useRef(null);
  const [sourceManagementOpen,setSourceManagementOpen]=useState(false);
  const [files, setFiles] = useState([]), [rights, setRights] = useState(false), [uploads, setUploads] = useState([]);
  const draftRef = useRef(drafts), editRef = useRef(edits), detailRef = useRef(detail);
  const authEpoch=useRef(0);
  const refreshOrder=useRef({issued:0,applied:0});
  const libraryScrollRef=useRef(null);
  const cache = useRef({}), openSequence = useRef(0), mainRef = useRef(null), videoRef = useRef(null), writing = useRef(null), lastSession = useRef(null);
  draftRef.current = drafts; editRef.current = edits; detailRef.current = detail;
  const source = detail?.source, current = detail?.current, result = current?.result || {};
  const hasUnclassified=sources.some(isUnclassifiedSource);
  const activeTopic=topic===UNCLASSIFIED_TOPIC&&!hasUnclassified?'':topic;
  const key = draftKey(source?.id, current?.id), draft = drafts[key] || inputDraft(), edit = edits[key];
  const renderNavigation = openSequence.current;
  const hasWork = k => !!editRef.current[k] || !!draftRef.current[k] && (
    draftRef.current[k].score !== '' || draftRef.current[k].note !== '' ||
    draftRef.current[k].reviewer !== ui.default_reviewer || draftRef.current[k].decision !== 'approve');

  function clearPrivate() {
    ++authEpoch.current; writing.current=null; setBusy(false); ++openSequence.current; lastSession.current=null; cache.current={}; detailRef.current=null;
    setSession(null); setSources([]); setTasks([]); setTrash({items:[], retention_days:null}); setCatalog([]); setDetail(null); setSelectedVersion(null); setDrafts({}); setEdits({});
    setDataLoaded(false); resetLibraryFilters(); setPage('library'); setFiles([]); setUploads([]); setRights(false);
    setSourcePaid(false); setConfirmation(null); setMessage('');
    setReviewEpoch(v=>v+1); setReviewPending(false); setStale(false);
  }
  async function login(event) {
    event.preventDefault(); setError(''); setBusy(true);
    try {
      const response=await fetch('/api/auth/login',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({password})});
      setPassword('');
      if(!response.ok) {setError(response.status===429?'尝试次数过多，请稍后再试。':'密码错误，请重试。'); return;}
      setAuthEnabled(true); setLoginRequired(false); await bootstrap();
    } catch {setConnection('disconnected');setError('无法连接服务。');} finally {setBusy(false);}
  }
  function requireLogin() {clearPrivate(); setAuthEnabled(true); setLoginRequired(true); setConnection('connected');}
  async function logout() {
    const token=session?.csrf_token;
    try {await logoutLocal(token,requireLogin);}
    catch {setError('退出请求未确认，请重新登录。');}
  }
  async function api(path, options={}) {
    const epoch=authEpoch.current;
    let response;
    try {
      response = await fetch('/api'+path, {credentials:'same-origin', ...options, headers:{
        ...(options.body && !(options.body instanceof File) ? {'Content-Type':'application/json'} : {}),
        ...(options.method ? {'X-CSRF-Token':session?.csrf_token} : {}), ...options.headers}});
    } catch {
      if(epoch!==authEpoch.current) throw Error('LOGIN_REQUIRED');
      setSession(null); setConnection('disconnected'); setStale(true); throw Error(errorText(0));
    }
    if(epoch!==authEpoch.current) throw Error('LOGIN_REQUIRED');
    if (!response.ok) {
      const data = await guardedJson(response,epoch,()=>authEpoch.current,requireLogin);
      if(response.status === 401) {setSession(null); setConnection('disconnected'); setStale(true);}
      throw Error(data.error==='login_required'?'LOGIN_REQUIRED':errorText(response.status, data.error));
    }
    return guardedJson(response,epoch,()=>authEpoch.current,requireLogin);
  }
  async function refresh() {
    const epoch=authEpoch.current;
    const order=++refreshOrder.current.issued;
    const lastApplied=refreshOrder.current.applied;
    const [s,t,c] = await Promise.all([api('/sources'), api('/tasks'), api('/classifications')]);
    if(epoch!==authEpoch.current||order<refreshOrder.current.applied) return;
    const overlapped=lastApplied!==refreshOrder.current.applied;
    refreshOrder.current.applied=order;
    setSources(previous=>overlapped&&hasOlderSourceReviews(previous,s.items)?previous:s.items);
    setTasks(t.items); setCatalog(c.items);setDataLoaded(true);
  }
  async function run(action) {
    const owner=acquireWriter(writing), epoch=authEpoch.current;
    if (!owner) return;
    setBusy(true); setError(''); setMessage('');
    try {await action();} catch (e) {if(epochCurrent(epoch,authEpoch)&&e.message!=='LOGIN_REQUIRED')setError(e.message);} finally {if(releaseWriter(writing,owner))setBusy(false);}
  }
  async function bootstrap() {
    setConnection('connecting'); setError('');
    const epoch=authEpoch.current;
    try {const value=await api('/session');if(epoch!==authEpoch.current)return;lastSession.current=value;setSession(value);setAuthEnabled(!!value.config.auth_enabled);setConnection('connected');}
    catch (e) {if(e.message!=='LOGIN_REQUIRED') {setConnection('disconnected'); setError(e.message);}}
  }
  function showDetail(value) {detailRef.current=value;setDetail(value);if(!value.viewing_history)cache.current[value.source.id]=value;}
  function syncDetail(value) {
    const previous=detailRef.current;
    if (!previous || previous.source.id!==value.source.id) return;
    if (previous.current?.id!==value.current?.id && hasWork(draftKey(previous.source.id,previous.current?.id))) {setStale(true);return;}
    showDetail(value);
  }
  async function open(id, options=false) {
    const discard=options===true, versionId=options?.versionId||null;
    const sequence=++openSequence.current;
    setBusy(true);setError('');setMessage('');
    try {
      const value=await api(detailPath(id,versionId));
      if (sequence!==openSequence.current) return;
      const prior=cache.current[id];
      const conflict=!discard && !versionId && prior?.current?.id!==value.current?.id && hasWork(draftKey(id,prior?.current?.id));
      if(page!=='detail'||detailRef.current?.source.id!==id)setSourceManagementOpen(false);
      showDetail(conflict?prior:value);setSelectedVersion(versionId);setStale(!!conflict);setTab('summary');setSourcePaid(false);setPage('detail');
    } catch(e) {if(sequence===openSequence.current)setError(e.message);}
    finally {if(sequence===openSequence.current)setBusy(!!writing.current);}
  }
  function navigate(next) {openSequence.current++;setBusy(!!writing.current);setPage(next);setError('');setMessage('');}
  function resetLibraryFilters() {
    setTopic('');
    setLibraryFilters({...emptyLibraryFilters});
  }
  async function changed() {
    const previous=detailRef.current, sequence=openSequence.current;
    await refresh();
    if(previous&&sequence===openSequence.current){
      const value=await api(detailPath(previous.source.id,selectedVersion));
      if(sequence===openSequence.current)syncDetail(value);
    }
  }
  const videoReprocessBusy = ['queued','running','needs_attention'].includes(detail?.task?.status)
    && detail?.task?.error_code !== 'version_conflict';
  async function obsidianApplied(id, originNavigation) {
    await refresh();
    if(!id)return;
    if(originNavigation===openSequence.current)await open(id);
    else cache.current[id]=await api('/sources/'+id);
  }
  function patchDraft(patch) {setDrafts(previous=>({...previous,[key]:updateReviewDraft(previous[key]||inputDraft(),patch)}));}
  function setEdit(value) {setEdits(previous=>({...previous,[key]:value}));}
  function confirmAction(title,text,action) {
    dialogOpener.current=document.activeElement;setConfirmation({title,text,action});
  }
  async function reloadDetail() {
    if(detail.viewing_history){await open(source.id,{versionId:current.id});return;}
    const action=async()=>{
      setDrafts(previous=>{const next={...previous};delete next[key];return next;});
      setEdits(previous=>{const next={...previous};delete next[key];return next;});
      await open(source.id,true);
    };
    if(hasWork(key))confirmAction('重新加载详情','这会放弃此版本尚未提交的评分和修订草稿。',action);
    else await action();
  }
  async function submitReview() {
    if (!canSubmitReview(draft,session.config.quality_target) || stale || edit) return;
    const epoch=authEpoch.current, sequence=openSequence.current, sourceId=source.id;
    const reviewId=draft.reviewId||crypto.randomUUID();patchDraft({reviewId});
    setReviewPending(true);setReviewEpoch(value=>value+1);
    try {
      await api('/sources/'+source.id+'/reviews',{method:'POST',body:JSON.stringify({
        version_id:current.id,content_sha256:current.content_sha256,score:Number(draft.score),decision:draft.decision,
        reviewer:draft.reviewer,review_id:reviewId,note:draft.note,tags:[]})});
      setDrafts(previous=>{const next={...previous};delete next[key];return next;});
      const fresh=await api('/sources/'+sourceId);cache.current[sourceId]=fresh;
      if(sequence===openSequence.current&&detailRef.current?.source.id===sourceId)showDetail(fresh);
      await refresh();setMessage('审核已提交。');
    } finally {
      // The response may be lost after the server committed; never retain pre-submit references.
      if(epochCurrent(epoch,authEpoch)){setReviewEpoch(value=>value+1);setReviewPending(false);}
    }
  }
  async function upload() {
    const epoch=authEpoch.current, messages=[];
    for(const file of files) {
      if(!epochCurrent(epoch,authEpoch))return;
      setUploads([...messages,file.name+'：上传中']);
      try {
        const problem=uploadError(file,session.config);if(problem)throw Error(problem);
        const value=await api('/imports?filename='+encodeURIComponent(file.name)+'&rights_confirmed=true',{
          method:'PUT',body:file,headers:{'Content-Type':'application/octet-stream'}});
        if(!epochCurrent(epoch,authEpoch))return;
        messages.push(file.name+'：'+(value.duplicate?'已存在':'已导入，请到任务页启动处理'));
      } catch(e) {if(!epochCurrent(epoch,authEpoch))return; messages.push(file.name+'：'+e.message);}
      setUploads([...messages]);
    }
    if(epochCurrent(epoch,authEpoch))await refresh();
  }
  useEffect(()=>{bootstrap();},[]);
  useEffect(()=>{
    if(!session)return;
    let alive=true;refresh().catch(e=>{if(alive)setError(e.message);});
    const timer=setInterval(()=>refresh().catch(e=>{if(alive)if(e.message!=='LOGIN_REQUIRED')setError(e.message);}),session.config.poll_interval_ms);
    return()=>{alive=false;clearInterval(timer);};
  },[session]);
  useEffect(()=>{
    if(page!=='detail'||!session||!source?.id)return;
    let alive=true;const path=detailPath(source.id,selectedVersion), sequence=openSequence.current;
    const timer=setInterval(async()=>{try{const value=await api(path);if(alive&&sequence===openSequence.current)syncDetail(value);}catch(e){if(alive&&sequence===openSequence.current&&e.message!=='LOGIN_REQUIRED')setError(e.message);}},session.config.poll_interval_ms);
    return()=>{alive=false;clearInterval(timer);};
  },[page,session,source?.id,selectedVersion,renderNavigation]);
  useEffect(()=>{
    [...(mainRef.current?.querySelectorAll('[data-page-title]')||[])].find(element=>!element.closest('[hidden]'))?.focus({preventScroll:true});
  },[page,source?.id]);
  useEffect(()=>{
    if(libraryScrollRef.current)libraryScrollRef.current.scrollTop=0;
  },[activeTopic,libraryFilters]);
  useEffect(()=>{
    if(topic!==activeTopic)setTopic(activeTopic);
  },[topic,activeTopic]);
  useEffect(()=>{
    if(confirmation){if(!dialogRef.current.open)dialogRef.current.showModal();}
    else if(dialogRef.current?.open){dialogRef.current.close();if(dialogOpener.current?.isConnected)dialogOpener.current.focus();}
  },[confirmation]);

  const titleProps={'data-page-title':true,tabIndex:-1};
  const preview=useMemo(()=>htmlBodyPreview(source?.kind,result),[source?.kind,result]);
  const offlineHtml=source?.kind==='html'&&result.provenance==='local_extraction';
  const duplicateNotes=offlineHtml&&!!result.body&&result.notes===result.body;
  const availableTabs=Object.keys(fields).filter(name=>name!=='title'
    &&(isVideo(source?.kind)||!['transcript','visual'].includes(name))
    &&!(name==='notes'&&duplicateNotes));
  const selectedTab=availableTabs.includes(tab)?tab:'summary';
  useEffect(()=>{
    const video=videoRef.current;
    if(selectedTab!=='visual'&&video&&!video.paused)video.pause();
  },[selectedTab]);
  const libraryActive=!!session&&page==='library';
  const tasksActive=!!session&&page==='tasks';
  const catalogActive=!!session&&page==='catalog';
  const sidebarTopics=catalog.filter(item=>item.kind==='topic');
  return <div className={libraryActive||tasksActive||catalogActive?'shell shell--list':'shell'}>
    <aside className="app-nav"><div className="app-brand"><span className="brand-mark" aria-hidden="true">知</span>个人知识库</div><nav aria-label="主导航">
      {ui.navigation.map(item=><button key={item.id} aria-current={(page===item.id||page==='detail'&&item.id==='library')?'page':undefined} onClick={()=>navigate(item.id)}><svg className="nav-icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d={({library:"M4 5h6a3 3 0 0 1 3 3v12a3 3 0 0 0-3-3H4z M20 5h-4a3 3 0 0 0-3 3v12a3 3 0 0 1 3-3h4z",ask:"M4 5h16v11H9l-5 4z",import:"M4 14v5h16v-5 M12 3v11 M8 10l4 4 4-4",tasks:"M5 5h2 M10 5h9 M5 12h2 M10 12h9 M5 19h2 M10 19h9",catalog:"M3 4h9l9 9-8 8-10-10z M7 8h.01"})[item.id]}/></svg>{item.label}</button>)}
    </nav>
    {session&&dataLoaded&&<div className="sidebar-topics" role="group" aria-label="主题筛选">
      <h2><button className="topics-heading" aria-label="主题，显示全部资料" title="显示全部资料"
        onClick={()=>{resetLibraryFilters();navigate('library');}}>主题</button></h2>
      {hasUnclassified&&<button aria-pressed={activeTopic===UNCLASSIFIED_TOPIC}
        onClick={()=>{setTopic(UNCLASSIFIED_TOPIC);navigate('library');}}>未分类</button>}
      {sidebarTopics.map(item=><button key={item.id} aria-pressed={activeTopic===item.id} onClick={()=>{setTopic(item.id);navigate('library');}}>{item.name}</button>)}
    </div>}
    <div className="sidebar-session">
      <span className="connection-status" data-connected={connection==='connected'&&!loginRequired} role="status">{loginRequired?'请登录':connectionText(connection)}</span>
      {authEnabled&&session&&<button className="logout-button" onClick={logout}>退出登录</button>}
    </div></aside>
    <main className="workspace" ref={mainRef}>
      {error&&<p className="error" role="alert">{error}</p>}{message&&<p role="status">{message}</p>}
      {lastSession.current&&<div hidden={page!=='ask'||!session}><RagPanel onLoginRequired={requireLogin} api={api} sources={sources} catalog={catalog} session={session||lastSession.current} connected={!!session} active={page==='ask'&&!!session} reviewEpoch={reviewEpoch} reviewPending={reviewPending}/></div>}
      {!session&&loginRequired?<section className="login-panel"><h1 {...titleProps}>登录个人知识库</h1><form onSubmit={login}><label>密码<input type="password" autoComplete="current-password" value={password} onChange={e=>setPassword(e.target.value)} required /></label><button className="primary" disabled={busy}>登录</button></form></section>:!session?<section><h1 {...titleProps}>连接服务</h1><p>{connectionText(connection)}</p>{connection==='disconnected'&&<button onClick={bootstrap}>重试连接</button>}</section>:<>
        <div className="list-page" hidden={!libraryActive}>{dataLoaded?<LibraryView sources={sources} catalog={catalog} api={api} open={open} changed={changed} disabled={busy} topicId={activeTopic} filters={libraryFilters} setFilters={setLibraryFilters} onResetFilters={resetLibraryFilters} onImport={()=>navigate('import')} onTrash={()=>run(async()=>{setTrash(await api('/trash'));navigate('trash');})} listRef={libraryScrollRef} displayTimezone={session.config.display_timezone}/>:<section><h2 {...titleProps}>资料库</h2><p role="status">正在读取资料与分类…</p></section>}</div>
        {page==='trash'&&<><div className="page-heading"><h1 {...titleProps}>回收站</h1></div><section>
          <button onClick={()=>navigate('library')}>返回资料库</button>
          <p className="muted">删除的资料保留 {trash.retention_days} 天，到期后由定期维护清理。已有备份副本按快照保留策略轮换。</p>
          {!trash.items.length&&<p>回收站为空。</p>}
          {trash.items.map(item=><article className="task-row" key={item.id}>
            <strong>{item.title||item.original_name}</strong>
            <p>删除时间 {formatDate(item.deleted_at,session.config.display_timezone)}</p>
            <p>到期时间 {formatDate(item.expires_at,session.config.display_timezone)}</p>
            {item.can_restore?<button disabled={busy} onClick={()=>run(async()=>{
              await api('/trash/'+item.id+'/restore',{method:'POST',body:'{}'});
              setTrash(await api('/trash'));await refresh();setMessage('资料已恢复。');
            })}>撤销删除</button>:<p className="muted">已到期，等待维护清理。</p>}
          </article>)}
        </section></>}
        {catalogActive&&<CatalogManager catalog={catalog} loaded={dataLoaded} api={api} changed={refresh} disabled={busy}/>}
        {page==='import'&&<><div className="page-heading"><h1 {...titleProps}>导入资料</h1></div><section className="import-panel">
          <p className="muted">上传HTML或视频后，到任务页明确启动处理。导入不会自动调用模型。</p>
          <div className="drop" onDragOver={event=>event.preventDefault()} onDrop={event=>{event.preventDefault();setFiles([...event.dataTransfer.files]);}}>
            <label>选择文件<input type="file" multiple accept=".html,.htm,.mp4" onChange={event=>setFiles([...event.target.files])}/></label><p>也可将文件拖到这里</p></div>
          {files.map((file,i)=><p key={i}>{file.name}</p>)}<label><input type="checkbox" checked={rights} onChange={event=>setRights(event.target.checked)}/>我确认有权导入并处理这些文件</label>
          <div className="actions"><button className="primary" disabled={busy||!rights||!files.length} onClick={()=>run(upload)}>上传文件</button><button onClick={()=>navigate('tasks')}>查看任务</button></div>
          <div role="status">{uploads.map((value,i)=><p key={i}>{value}</p>)}</div>
          <details><summary>抖音分享链接</summary><DouyinPanel api={api} opened={open} pollInterval={session.config.poll_interval_ms} disabled={busy}/></details>
          <FavoritesPanel api={api} pollInterval={session.config.poll_interval_ms} disabled={busy}/>
          <details><summary>上传Obsidian更新</summary><ObsidianPanel api={api} applied={id=>obsidianApplied(id,renderNavigation)} disabled={busy}/></details>
        </section></>}
        <TaskList active={tasksActive} loaded={dataLoaded} tasks={tasks} sources={sources} config={session.config} busy={busy}
          open={open} onAction={(id,action,body)=>run(async()=>{
            await api('/tasks/'+id+'/'+action,{method:'POST',body:JSON.stringify(body)});
            await refresh();
          })}/>
        {page==='detail'&&detail&&<>
          <div className="source-heading">
            <button className="detail-back" type="button" onClick={()=>navigate('library')}><span aria-hidden="true">← </span>返回资料库</button>
            <div className="source-title-row">
              <h1 {...titleProps}>{source.title||result.title||source.original_name}</h1>
              {current&&!detail.viewing_history&&<button type="button" aria-expanded={sourceManagementOpen} aria-controls="source-management"
                onClick={()=>setSourceManagementOpen(open=>!open)}>资料管理</button>}
            </div>
            <p className="muted">
              {isVideo(source.kind)?'视频':'HTML'} · {current?(!detail.viewing_history&&detail.eligible?'已批准，可用于知识库':detail.review?statusText(detail.review.decision):'待审核'):'待处理'}
              {detail.review&&` · ${detail.review.score} 分`} · {source.original_name}
            </p>
            {current&&detail.versions?.length>1&&<label>查看版本 <select disabled={busy} value={detail.viewing_history?current.id:''} onChange={event=>open(source.id,{versionId:event.target.value||null})}><option value="">当前版本</option>{detail.versions.filter(version=>version.id!==source.current_version_id).slice().reverse().map(version=><option key={version.id} value={version.id}>{formatDate(version.created_at,session.config.display_timezone)} · {version.output_kind==='human_edited'?'人工修订':'处理结果'}</option>)}</select></label>}
            {detail.viewing_history&&<p className="notice">正在查看历史版本，仅供阅读。 <a href={'/api/versions/'+current.id+'/export'}>下载此版本 Markdown 与证据</a></p>}
            {detail.media?.status==='removed'&&<p className="muted">原视频已超过保留期并清理，整理内容和证据仍可查看。</p>}
          </div>
          {!current?<section><p>尚未生成可审核内容。</p><button onClick={()=>navigate('tasks')}>到任务页处理</button></section>:<>
            {(stale||source.content_status&&source.content_status!=='synced')&&<p className="error" role="alert">{stale?'版本或连接状态已变化，旧草稿不会提交到新版本。':'长期内容尚未同步或校验失败，不能用于正式知识库。'} <button onClick={reloadDetail}>重新加载详情</button></p>}
            <div className="source-layout"><div className="source-reading">
              {!detail.viewing_history&&<section id="source-management" key={source.id} className="source-management" aria-label="资料管理" hidden={!sourceManagementOpen}>
                <div className="source-downloads"><a href={'/api/versions/'+current.id+'/export'}>下载Markdown与证据正文</a>{detail.original_url&&!isVideo(source.kind)&&<a href={detail.original_url}>下载原HTML</a>}</div>
                <details><summary>分类</summary><ClassificationEditor key={source.id+'-classification'} source={source} catalog={catalog} api={api} changed={changed} disabled={busy}/></details>
                <details><summary>Obsidian 导出与更新</summary><ObsidianPanel key={source.id} sourceId={source.id} api={api} applied={id=>obsidianApplied(id,renderNavigation)} disabled={busy||!!edit||hasWork(key)}/></details>
                <details open={!!edit}><summary>人工修订</summary>{edit?<>
                  {Object.keys(fields).filter(name=>isVideo(source.kind)||!['transcript','visual'].includes(name)).map(name=><label className="edit-field" key={name}>{fields[name]}<textarea disabled={busy} value={edit[name]} onChange={event=>setEdit({...edit,[name]:event.target.value})}/></label>)}
                  <button className="primary" disabled={busy||stale} onClick={()=>run(async()=>{
                    const sequence=openSequence.current,sourceId=source.id;
                    await api('/sources/'+sourceId+'/revisions',{method:'POST',body:JSON.stringify({expected_version_id:current.id,...edit})});setEdit(null);
                    const fresh=await api('/sources/'+sourceId);cache.current[sourceId]=fresh;
                    if(sequence===openSequence.current&&detailRef.current?.source.id===sourceId){showDetail(fresh);setSelectedVersion(null);setStale(false);setTab('summary');}
                    await refresh();setMessage('已生成新版本，请重新审核。');
                  })}>保存新版本</button>
                  <button disabled={busy} onClick={()=>confirmAction('放弃修订','此版本尚未保存的人工修订将被放弃。',()=>setEdit(null))}>放弃修订</button>
                </>:<button onClick={()=>setEdit(Object.fromEntries(Object.keys(fields).map(name=>[name,textValue(name==='title'&&isVideo(source.kind)&&result.title===source.original_name?source.title||result.title:result[name])])))}>编辑内容</button>}</details>
                {source.kind==='html'&&<details><summary>重新整理网页</summary><label><input type="checkbox" checked={sourcePaid} onChange={event=>setSourcePaid(event.target.checked)}/>我同意本次网页模型整理费用</label><p className="muted">保留旧版本与评分，新结果需要重新审核。</p>
                  <button disabled={busy||!sourcePaid||!session.config.live_html_enabled||stale||['queued','running','needs_attention'].includes(detail.task?.status)} onClick={()=>run(async()=>{await api('/sources/'+source.id+'/process',{method:'POST',body:JSON.stringify({allow_paid:true,expected_version_id:current.id})});setSourcePaid(false);await changed();})}>生成新的模型整理版本</button></details>}
                {isVideo(source.kind)&&<details><summary>重新转写视频</summary>
                  <label><input type="checkbox" checked={sourcePaid} onChange={event=>setSourcePaid(event.target.checked)}/>我同意本次转写、画面识别和整理产生的模型费用</label>
                  <p className="muted">使用原视频生成待审核版本，保留旧版本及审核记录。</p>
                  {!detail.original_url&&<p className="muted">原视频不可用，无法重新转写。</p>}
                  {!session.config.live_video_enabled&&<p className="muted">视频处理当前未启用。</p>}
                  {videoReprocessBusy&&<p className="muted">已有任务，请前往任务页查看进度或处理异常。</p>}
                  <button disabled={busy||!!edit||!sourcePaid||!detail.original_url||!session.config.live_video_enabled||stale||videoReprocessBusy} onClick={()=>run(async()=>{
                    if (videoReprocessRequest.current?.key !== key) videoReprocessRequest.current = {key, id:crypto.randomUUID()};
                    await api('/sources/'+source.id+'/process',{method:'POST',body:JSON.stringify({allow_paid:true,expected_version_id:current.id,request_id:videoReprocessRequest.current.id})});
                    videoReprocessRequest.current = null;
                    setSourcePaid(false);setSelectedVersion(null);await changed();setMessage('重新转写任务已提交，请在任务页查看进度。');
                  })}>重新转写并生成新版本</button></details>}
                <details><summary>版本与技术信息</summary><pre>{JSON.stringify({source_id:source.id,version_id:current.id,content_sha256:current.content_sha256,content_status:source.content_status},null,2)}</pre></details>
                <details><summary>删除资料</summary><p>删除后资料将退出检索与问答，现有引用会失效。可在回收站保留期限内撤销。</p><button className="danger" disabled={busy} onClick={()=>confirmAction('删除资料','删除“'+(source.title||source.original_name)+'”后将退出知识库，现有引用失效。可在回收站保留期限内撤销。',()=>run(async()=>{
                  const sequence=openSequence.current,sourceId=source.id;await api('/sources/'+sourceId,{method:'DELETE'});delete cache.current[sourceId];
                  if(sequence===openSequence.current&&detailRef.current?.source.id===sourceId){detailRef.current=null;setDetail(null);navigate('library');}await refresh();
                }))}>确认删除资料</button></details>
              </section>}
              {offlineHtml&&<p className="notice">离线正文预览，尚未调用模型整理。</p>}
              <div className="content-tabs" aria-label="阅读内容">{availableTabs.map(name=><button key={name} aria-pressed={selectedTab===name} className={selectedTab===name?'active':''} onClick={()=>setTab(name)}>{name==='summary'&&preview?'正文预览':fields[name]}</button>)}</div>
              {duplicateNotes&&<details key={current.id}><summary>笔记与正文相同</summary><button className="text-button" onClick={()=>setTab('body')}>查看完整正文</button></details>}
              {isVideo(source.kind)&&<section className="video-evidence" hidden={selectedTab!=='visual'} aria-label="视频原片与关键帧">
                <h2>视频原片</h2>
                {detail.original_url?<video ref={videoRef} controls preload={selectedTab==='visual'?'metadata':'none'} src={detail.original_url}
                  poster={selectedTab==='visual'?detail.frames?.[0]?.url:undefined}/>:<p className="muted">{detail.media?.status==='removed'?'原片已超过保留期并清理。':'原片已不可用。'}</p>}
                <h2>关键帧</h2>
                {detail.frames?.length?<div className="frame-list" role="region" aria-label="关键帧列表" tabIndex={0}>{detail.frames.map((frame,index)=>{
                  const seconds=frame.seconds??0;
                  const thumbnail=<img width={ui.frame_preview_width} loading="lazy" alt={'关键帧 '+(index+1)}
                    src={frame.url||('/api/sources/'+source.id+'/frames/'+(frame.index??index))}/>;
                  return detail.original_url
                    ? <button key={frame.index??index} type="button" onClick={()=>{if(videoRef.current)videoRef.current.currentTime=seconds;}}>{thumbnail}<span>{seconds} 秒</span></button>
                    : <figure key={frame.index??index}>{thumbnail}<figcaption>{seconds} 秒</figcaption></figure>;
                })}</div>:<p className="muted">暂无可查看的关键帧。</p>}
              </section>}
              {selectedTab==='visual'&&<h2 className="visual-text-heading">画面识别文字</h2>}
              <div className={['summary','notes'].includes(selectedTab)?'source-prose':undefined}>
                <DocumentView structureSummary={selectedTab==='summary'&&!preview}
                  value={(selectedTab==='summary'&&preview?preview.text:textValue(result[selectedTab]))||'暂无此项内容'}/>
                {selectedTab==='summary'&&preview?.omitted&&<p className="muted">… 后续内容已省略，可切换到「正文」查看。</p>}
              </div>
              {result.warnings&&<p className="notice">提示：{Array.isArray(result.warnings)?result.warnings.join('；'):textValue(result.warnings)}</p>}
            </div>
            <aside className="review-panel" aria-label={detail.viewing_history?'历史版本审核记录':'审核当前版本'}><h2>{detail.viewing_history?'审核记录':'审核'}</h2><p>{detail.review?`${statusText(detail.review.decision)} · ${detail.review.score} 分`:'尚未审核'}</p>
              {detail.media?.status==='removed'&&<p className="muted">原视频已超过保留期并清理，整理内容和证据仍可查看。</p>}
              {detail.review&&<><p className="muted">{detail.review.reviewer} · {formatDate(detail.review.created_at,session.config.display_timezone)}</p><p>审核意见：{detail.review.note||'无'}</p></>}
              {!detail.viewing_history&&<><p className="muted">批准门槛 {session.config.quality_target} 分。修改内容生成新版本后须重新审核。</p>
              <label>审核人<input disabled={busy} value={draft.reviewer} onChange={event=>patchDraft({reviewer:event.target.value})}/></label><label>评分<input disabled={busy} type="number" min="0" max="100" step={ui.review_score_step} value={draft.score} onChange={event=>patchDraft({score:event.target.value})}/></label>
              <label>决定<select disabled={busy} value={draft.decision} onChange={event=>patchDraft({decision:event.target.value})}><option value="approve">批准</option><option value="rework">返工</option><option value="reject">拒绝</option></select></label><label>审核意见<textarea disabled={busy} value={draft.note} onChange={event=>patchDraft({note:event.target.value})}/></label>
              <p className="muted">草稿仅保留在当前打开的页面，刷新会丢失；保存草稿不会批准资料。</p><div className="actions">
                <button disabled={busy||stale||!!edit||!validReview(draft.score,'rework',session.config.quality_target,draft.reviewer)} onClick={()=>{setDrafts(previous=>({...previous,[key]:saveReviewDraft(previous[key]||inputDraft())}));setMessage('评分草稿已保存，尚未提交审核。');}}>保存评分草稿</button>
                <button className="primary" disabled={busy||stale||!!edit||!canSubmitReview(draft,session.config.quality_target)} onClick={()=>run(submitReview)}>提交{statusText(draft.decision)}</button></div>
              <p className="muted" role="status">{edit?'人工修订尚未提交，请先保存新版本或放弃修订。':reviewDraftSaved(draft)?'评分草稿已保存，请核对后明确提交。':'评分或意见尚未保存。'}</p></>}
            </aside></div>
          </>}
        </>}
      </>}
    </main>
    <dialog ref={dialogRef} aria-labelledby="confirmation-title" onCancel={event=>{event.preventDefault();setConfirmation(null);}}>
      <h2 id="confirmation-title">{confirmation?.title}</h2><p>{confirmation?.text}</p>
      <div className="actions"><button autoFocus onClick={()=>setConfirmation(null)}>取消</button>
        <button className={confirmation?.title==='删除资料'?'danger':'primary'} onClick={()=>{const action=confirmation?.action;setConfirmation(null);action?.();}}>确认操作</button></div>
    </dialog>
  </div>;
}
createRoot(document.getElementById('root')).render(<App/>);
