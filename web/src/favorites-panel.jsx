import {latestReads, serialPoll} from './polling';
import React, {useEffect, useId, useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import {albumQuoteErrors} from './helpers.js';
import {MediaTypeBadge} from './media-type-badge';
import './favorites.css';

const states = {scan_queued:'等待读取收藏', scanning:'正在读取收藏', confirm_account:'等待确认账号',
  baseline_pending:'正在建立基线', idle:'等待读取收藏', ready:'收藏已同步', paused:'同步暂停'};
const itemStates = {
  baseline:['可导入', 'available'],
  imported:['已导入', 'imported'],
  existing:['资料已存在', 'imported'],
  converted:['转换完成', 'imported'],
  queued:['等待下载', 'pending'],
  downloading:['下载中', 'pending'],
  downloaded:['已下载，等待转换', 'pending'],
  conversion_queued:['转换已排队', 'pending'],
  conversion_failed:['转换异常，请查看任务详情', 'failed'],
  download_failed:['下载失败', 'failed'],
  deleted:['资料在回收站', 'neutral'],
  skipped:['已跳过', 'neutral'],
};
const filterLabels = {all:'全部',available:'可导入',imported:'已导入',other:'其他状态'};
const reasons = {missing_douyin_cookie:'缺少 Cookie', login_required:'需要重新登录', account_unverified:'无法核实登录账号',
  collection_http_error:'抖音拒绝收藏请求', collection_timeout:'收藏读取超时', pagination_incomplete:'收藏翻页未完成',
  baseline_incomplete:'未读满基线且未到末页', snapshot_gap:'未找到上次同步位置',
  snapshot_rebased:'未找到上次同步位置，已重新建立基线', browser_dependency_missing:'服务器缺少浏览器组件',
  douyin_resolver_failed:'下载解析失败，请核对登录状态'};
const imageDownloadErrors = {douyin_http_failed:'图片地址不可用，请读取收藏刷新后重试', douyin_timeout:'图片下载超时',
  album_image_limit:'图片数量超出上限', album_size_limit:'图片总大小超出上限', douyin_size_limit:'图片大小超出上限',
  favorites_price_changed:'图片数量或费用已变化，请查看限制并重新确认',
  album_invalid_image:'图片格式无效', douyin_unsafe_url:'图片地址不在允许的图床范围内'};

export function batchAmount(values) {
  let total = 0n;
  for (const value of values) {
    if (typeof value !== 'string' || !/^\d+(?:\.\d{1,2})?$/.test(value)) return null;
    const [whole, fraction = ''] = value.split('.');
    total += BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'));
  }
  return `${total / 100n}.${(total % 100n).toString().padStart(2, '0')}`;
}

function FavoriteType({item, onLimits}) {
  const image = item.kind==='image';
  const quoteAvailable = image && batchAmount([item.image_quote_cny])!==null;
  return <div className="favorites-type">
    <MediaTypeBadge kind={image?'douyin_album':'video'} variant="text"/>
    {image&&<small className="favorites-type-detail">
      {item.image_count==null?'张数未知':`${item.image_count} 张`}
      {quoteAvailable?` · 上限 ¥${item.image_quote_cny}`:!item.image_limits?' · 报价不可用':null}
    </small>}
    {item.image_limits&&<button type="button" className="favorites-expand" onClick={()=>onLimits(item)}>查看限制</button>}
  </div>;
}

function FavoriteRow({item, checked, selectable, canSelect, onChange, onRetry, onLimits}) {
  const title = item.title || item.work_id;
  const titleId = useId();
  const titleRef = useRef(null);
  const [expanded, setExpanded] = useState(false);
  const [truncated, setTruncated] = useState(false);
  const Title = selectable ? 'label' : 'div';
  const checkboxId = `${titleId}-checkbox`;
  const status = item.status || 'baseline';
  const quoteError = albumQuoteErrors[item.image_quote_error];
  const [statusText, tone] = quoteError&&['baseline','downloaded'].includes(status)
    ? [quoteError, 'neutral']
    : status==='baseline'&&!selectable
    ? ['暂不可导入', 'neutral']
    : itemStates[status] || [status, 'neutral'];

  useEffect(() => {
    if (expanded) return;
    const element = titleRef.current;
    const measure = () => setTruncated(element.scrollHeight > element.clientHeight);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [expanded, title, Title]);

  return <li className="favorites-row" data-selected={checked || undefined}>
    {selectable && <input id={checkboxId} className="favorites-checkbox" type="checkbox" disabled={!canSelect}
      checked={checked} onChange={event => onChange(item.work_id, event.target.checked)}/>}
    <div className="favorites-video">
      <Title id={titleId} htmlFor={selectable ? checkboxId : undefined}
        ref={titleRef} className="favorites-title" data-expanded={expanded || undefined}>{title}</Title>
      {(truncated || expanded) && <button type="button" className="favorites-expand" aria-expanded={expanded}
        aria-controls={titleId} onClick={() => setExpanded(value => !value)}>{expanded ? '收起' : '展开'}</button>}
    </div>
    <FavoriteType item={item} onLimits={onLimits}/>
    <span className="favorites-status" data-tone={tone}>{statusText}
      {item.image_download_error&&status==='download_failed'&&<small>{imageDownloadErrors[item.image_download_error]||item.image_download_error}</small>}
      {item.kind==='image'&&status==='download_failed'&&item.image_download_error!=='favorites_price_changed'&&<button type="button" disabled={!canSelect}
        onClick={()=>onRetry(item.work_id)}>重新下载</button>}
    </span>
  </li>;
}

export function FavoritesPanel({api, pollInterval, disabled, dock}) {
  const [open,setOpen]=useState(false);
  const [data,setData]=useState(null);
  const [filter,setFilter]=useState('all');
  const [selected,setSelected]=useState([]);
  const [rights,setRights]=useState(false);
  const [paidAgreement,setPaidAgreement]=useState(null);
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState('');
  const [batchMessage,setBatchMessage]=useState('');
  const [batchError,setBatchError]=useState('');
  const dialogRef=useRef(null);
  const batchFeedbackRef=useRef(null);
  const limitsRef=useRef(null);
  const [preview,setPreview]=useState(null);
  const [limitRights,setLimitRights]=useState(false);
  const [limitPaid,setLimitPaid]=useState(false);
  const [limitMessage,setLimitMessage]=useState('');
  const dialogTitle=useId();
  const limitsTitle=useId();
  const reads=useRef(latestReads()), actionPending=useRef(false);
  async function refresh(active=()=>true){
    const current=reads.current.begin('favorites'), valid=()=>active()&&current();
    try {const result=await api('/douyin/favorites/sync',{isCurrent:valid});if(valid())setData(result);}
    catch(e){if(valid())throw e;}
  }
  useEffect(()=>{
    if(!open)return;
    const stop=serialPoll(async active=>{if(actionPending.current)return;try{await refresh(()=>active()&&!actionPending.current);}catch(e){if(active())setMessage(e.message);}},pollInterval);
    return ()=>{stop();reads.current.invalidate('favorites');};
  },[open,pollInterval]);
  useEffect(()=>{setFilter('all');setSelected([]);setRights(false);setBatchMessage('');},[data?.active_account?.id]);
  async function action(path,body,success,report=setMessage){
    actionPending.current=true;reads.current.invalidate('favorites');
    setBusy(true);report('');
    try{
      const result=await api(path,{method:'POST',body:JSON.stringify(body)});
      report(typeof success==='function'?success(result):success);
      try{await refresh();}catch{}
      return true;
    }catch(e){report(e.message);return false;}
    finally{actionPending.current=false;setBusy(false);}
  }
  const items=data?.items||[];
  const groups={all:items,available:[],imported:[],other:[]};
  for (const item of items) {
    if (itemStates[item.status]?.[1]==='imported') groups.imported.push(item);
    else if (item.selectable && (item.kind!=='image' || batchAmount([item.image_quote_cny])!==null)) groups.available.push(item);
    else groups.other.push(item);
  }
  const visibleItems=groups[filter];
  const eligible=groups.available;
  const eligibleIds=new Set(eligible.map(item=>item.work_id));
  const selectedIds=selected.filter(id=>eligibleIds.has(id));
  function selectItem(id, checked) {
    setSelected(previous=>checked?[...previous,id]:previous.filter(value=>value!==id));
  }
  const price=data?.manual_video_budget_cny;
  const selectedItems=eligible.filter(item=>selectedIds.includes(item.work_id));
  const imageQuotes=Object.fromEntries(selectedItems.filter(item=>item.kind==='image').map(item=>[item.work_id,item.image_quote_cny]));
  const imageCount=Object.keys(imageQuotes).length;
  const selectedCount=selectedIds.length;
  const total=batchAmount(selectedItems.map(item=>item.kind==='image'?item.image_quote_cny:price));
  const selectionKey=JSON.stringify([data?.active_account?.id, price, imageQuotes, ...selectedIds]);
  const paid=paidAgreement===selectionKey;
  useEffect(()=>{setPaidAgreement(null);},[selectionKey]);
  const blocked=disabled||busy;
  const canSelect=!blocked&&data?.state==='ready';
  const canSubmitBatch=canSelect&&!!selectedCount&&rights&&paid&&data?.manual_conversion_available&&total!==null;
  useEffect(()=>{
    if(!selectedCount&&dialogRef.current?.open)dialogRef.current.close();
  },[selectedCount]);
  function openBatch(){
    setBatchError('');
    setRights(false);
    setPaidAgreement(null);
    dialogRef.current.showModal();
  }
  async function submitBatch(event){
    event.preventDefault();
    if(!canSubmitBatch)return;
    setBatchMessage('');
    if(await action('/douyin/favorites/import',{account_id:data.active_account?.id,work_ids:selectedIds,rights_confirmed:true,
      allow_paid:true,video_budget_cny:price,image_quotes:imageQuotes},
      ({queued})=>{
        setBatchMessage(queued?`已将 ${queued} 条作品排队下载和转换。`:'所选作品已导入或已在队列中。');
        return '';
      },setBatchError)){
      dialogRef.current?.close();
      setSelected([]);
      setRights(false);
      setPaidAgreement(null);
      requestAnimationFrame(()=>batchFeedbackRef.current?.focus());
    }
  }
  function openLimits(item){
    setPreview({item, account:data?.active_account?.id, budget:price});
    setLimitRights(false); setLimitPaid(false); setLimitMessage('');
    limitsRef.current.showModal();
  }
  const latestPreviewItem=preview&&items.find(item=>item.work_id===preview.item.work_id);
  const previewCurrent=preview&&data?.active_account?.id===preview.account&&price===preview.budget&&
    latestPreviewItem?.image_count===preview.item.image_count&&latestPreviewItem.image_limits?.can_import&&
    latestPreviewItem.image_limits.manual_quote_cny===preview.item.image_limits.manual_quote_cny;
  const canSubmitLimit=canSelect&&previewCurrent&&limitRights&&limitPaid;
  async function submitLimit(){
    if(!canSubmitLimit)return;
    const {item,account,budget}=preview;
    const reconfirm=item.status==='download_failed'&&item.image_download_error==='favorites_price_changed';
    const submitMessage=({queued})=>queued?(reconfirm?'已重新确认费用，作品已排队下载和转换。':'作品已提交下载和转换。'):'作品已导入或已在队列中。';
    let resultMessage='';
    if(await action('/douyin/favorites/import',{account_id:account,work_ids:[item.work_id],rights_confirmed:true,
      allow_paid:true,video_budget_cny:budget,image_quotes:{[item.work_id]:item.image_limits.manual_quote_cny},extended_image_count:item.image_count},
      result=>{resultMessage=submitMessage(result);return resultMessage;},setLimitMessage)) {
      limitsRef.current?.close();
      setMessage(resultMessage);
    }
  }
  const selectedKinds=`视频 ${selectedCount-imageCount} · 图文 ${imageCount}`;
  return <details onToggle={event=>setOpen(event.currentTarget.open)}>
    <summary>抖音收藏</summary>
    {open&&<div className="management">
      {data?.enabled&&<p>首次确认账号后记录最近 {data.baseline_limit ?? 100} 条收藏，选择作品后可排队下载并导入。</p>}
      {data&&!data.enabled&&<p>收藏同步尚未启用。</p>}
      {(!data||data.enabled)&&<p role="status">{data?states[data.state]||data.state:'正在读取状态…'}{data?.error_code&&' · '+(reasons[data.error_code]||data.error_code)}</p>}
      {data?.active_account&&<p>当前账号 {data.active_account.label||data.active_account.id}</p>}
      {data?.pending_account&&<div>
        <p>待确认账号 {data.pending_account.label||data.pending_account.id}</p>
        <button type="button" disabled={blocked} onClick={()=>action('/douyin/favorites/confirm',{account_id:data.pending_account.id},'已确认账号，正在建立或恢复基线。')}>确认使用此账号</button>
      </div>}
      <button type="button" disabled={blocked||!data?.enabled||['scan_queued','scanning'].includes(data?.state)}
        onClick={()=>action('/douyin/favorites/scan',{},'已提交收藏读取任务。')}>读取收藏</button>
      {data?.enabled&&<p>每日新增收藏下载上限 {data.download_limit} 条。手动选择的作品整批入队，依次下载和转换，转换结果待审核，不占每日定时额度。</p>}
      {data?.queue_counts&&<p>等待下载 {data.queue_counts.queued||0} 条，下载失败 {data.queue_counts.download_failed||0} 条，等待转换 {data.queue_counts.conversion_queued||0} 条。</p>}
      {data?.last_scan&&<p>最近读取 {data.last_scan.day}，读到 {data.last_scan.read_count} 条，新增排队 {data.last_scan.queued_count} 条。</p>}
      {batchMessage&&<p className="favorites-batch-feedback" ref={batchFeedbackRef} role="status" tabIndex={-1}>{batchMessage}</p>}
      {!!items.length&&<fieldset className="favorites-fieldset">
        <legend>收藏作品</legend>
        <div className="favorites-toolbar">
          <div className="favorites-filters" role="group" aria-label="按导入状态筛选">
            {Object.entries(filterLabels).map(([key,label])=><button key={key} type="button" aria-pressed={filter===key}
              onClick={()=>setFilter(key)}>{label} <span>{groups[key].length}</span></button>)}
          </div>
          <div className="favorites-selection">
            {(filter==='all'||filter==='available')&&<button type="button" disabled={!canSelect||!eligible.length||selectedIds.length===eligible.length}
              onClick={()=>setSelected([...eligibleIds])}>全选可导入作品</button>}
            <button type="button" disabled={blocked||!selectedIds.length} onClick={()=>setSelected([])}>清空选择</button>
          </div>
        </div>
        {visibleItems.length ? <>
          <div className="favorites-heading" aria-hidden="true"><span>作品标题</span><span>类型</span><span>导入状态</span></div>
          <ul className="favorites-list" role="list">
            {visibleItems.map(item=><FavoriteRow key={item.work_id} item={item} checked={selectedIds.includes(item.work_id)}
              selectable={eligibleIds.has(item.work_id)} canSelect={canSelect} onChange={selectItem}
              onLimits={openLimits} onRetry={work_id=>action('/douyin/favorites/retry-image',{account_id:data.active_account?.id,work_id},'已重新排队下载。')}/>)}
          </ul>
        </> : <p className="favorites-empty muted">当前没有{filterLabels[filter]}的作品。</p>}
      </fieldset>}
      {dock&&!!selectedCount&&createPortal(
        <section className="favorites-batch-bar" aria-label="已选作品">
          <div className="favorites-batch-copy" role="status">
            <span><strong>已选 {selectedCount} 条</strong> <small>{selectedKinds}</small></span>
            <span className="favorites-batch-total">{total===null?'费用上限暂不可用':<>费用上限 <strong>¥{total}</strong></>}</span>
          </div>
          <button type="button" className="primary" aria-haspopup="dialog" disabled={blocked} onClick={openBatch}>确认导入</button>
        </section>,dock)}
      <dialog ref={dialogRef} className="favorites-dialog favorites-batch-dialog" aria-labelledby={dialogTitle}
        onCancel={event=>{if(busy)event.preventDefault();}}>
        <div className="favorites-dialog-heading">
          <h2 id={dialogTitle}>导入确认</h2>
          <button type="button" disabled={busy} onClick={()=>dialogRef.current.close()}>关闭</button>
        </div>
        <form className="favorites-submit" onSubmit={submitBatch}>
          <p className="muted">已选 {selectedCount} 条 · {selectedKinds}</p>
          <ul className="favorites-batch-items" role="list" aria-label="本次导入作品" tabIndex={0}>
            {selectedItems.map(item=>{
              const itemPrice=item.kind==='image'?item.image_quote_cny:price;
              return <li key={item.work_id}><span>{item.title||item.work_id}</span>
                <small>{itemPrice==null?'报价不可用':`¥${itemPrice}`}</small></li>;
            })}
          </ul>
          <p className="favorites-fee"><span>本次费用上限</span><strong>{total===null?'暂不可用':`¥${total}`}</strong></p>
          {total!==null&&<p className="muted">每条作品分别预留费用，使用项目累计预算。转换结果待审核。</p>}
          {!data?.manual_conversion_available&&<p className="muted">当前无法启动手动付费转换。</p>}
          <div className="favorites-consents">
            <label><input type="checkbox" checked={rights} disabled={!canSelect}
              onChange={e=>setRights(e.target.checked)}/> 我确认有权下载和处理所选作品</label>
            <label><input type="checkbox" checked={paid} disabled={!canSelect||total===null}
              onChange={e=>setPaidAgreement(e.target.checked?selectionKey:null)}/> 我同意所选作品转换产生费用，按上述上限执行</label>
          </div>
          <p role="alert" className="error">{batchError}</p>
          <div className="favorites-batch-actions">
            <button type="button" disabled={busy} onClick={()=>dialogRef.current.close()}>返回列表</button>
            <button type="submit" className="primary" disabled={!canSubmitBatch}>{busy?'正在提交…':'下载并转换所选作品'}</button>
          </div>
        </form>
      </dialog>
      <dialog ref={limitsRef} className="favorites-dialog" aria-labelledby={limitsTitle} onCancel={event=>{if(busy)event.preventDefault();}}>
        <div className="favorites-dialog-heading"><h2 id={limitsTitle}>收藏处理限制</h2><button type="button" disabled={busy} onClick={()=>limitsRef.current.close()}>关闭</button></div>
        {preview&&<><p>{preview.item.title||preview.item.work_id}</p>
          <p>图片 {preview.item.image_count} 张 · 常规上限 {preview.item.image_limits.max_images} 张{preview.item.image_limits.manual_max_images!=null&&` · 手动上限 ${preview.item.image_limits.manual_max_images} 张`}</p>
          {preview.item.image_quote_error&&<p>{albumQuoteErrors[preview.item.image_quote_error]||preview.item.image_quote_error}</p>}
          {preview.item.image_limits.can_import ? <>
            <p><strong>本次费用上限 ¥{preview.item.image_limits.manual_quote_cny}</strong></p>
            <p className="muted">手动导入使用项目预算，独立于定时下载和转换额度。转换结果待审核。</p>
            <div className="favorites-consents"><label><input type="checkbox" checked={limitRights} onChange={e=>setLimitRights(e.target.checked)}/> 我确认有权下载和处理此作品</label>
            <label><input type="checkbox" checked={limitPaid} onChange={e=>setLimitPaid(e.target.checked)}/> 我同意按上述费用上限进行转换</label></div>
            {!previewCurrent&&!busy&&<p role="status">作品状态或报价已更新，请关闭并重新查看限制。</p>}
            <button type="button" className="primary" disabled={!canSubmitLimit} onClick={submitLimit}>{busy?'正在提交…':preview.item.image_download_error==='favorites_price_changed'?'重新确认并导入':'确认导入此作品'}</button>
          </> : preview.item.image_limits.manual_quote_cny!=null ? <>
            <p>单篇费用上限 ¥{preview.item.image_limits.manual_quote_cny}</p>
            <p>{preview.item.status?'此作品已有导入记录。':'当前无法启动单篇手动导入，请在收藏同步后重新查看。'}</p>
          </> : <>
            <p>此作品暂未开放单篇手动导入。</p>
            {preview.item.image_limits.estimate_cny!=null&&<p>整篇单次处理的理论费用上限 ¥{preview.item.image_limits.estimate_cny}。分批处理费用需另行报价。</p>}
          </>}
          <p role="status">{limitMessage}</p></>}
      </dialog>
      {message&&<p role="status">{message}</p>}
    </div>}
  </details>;
}
