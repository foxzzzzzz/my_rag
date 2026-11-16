import React, {useEffect, useId, useRef, useState} from 'react';
import {albumQuoteErrors} from './helpers.js';
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
const reasons = {missing_douyin_cookie:'缺少 Cookie', login_required:'需要重新登录', account_unverified:'无法核实登录账号',
  collection_http_error:'抖音拒绝收藏请求', collection_timeout:'收藏读取超时', pagination_incomplete:'收藏翻页未完成',
  baseline_incomplete:'未读满基线且未到末页', snapshot_gap:'未找到上次同步位置',
  snapshot_rebased:'未找到上次同步位置，已重新建立基线', browser_dependency_missing:'服务器缺少浏览器组件',
  douyin_resolver_failed:'下载解析失败，请核对登录状态'};
const imageDownloadErrors = {douyin_http_failed:'图片地址不可用，请读取收藏刷新后重试', douyin_timeout:'图片下载超时',
  album_image_limit:'图片数量超出上限', album_size_limit:'图片总大小超出上限', douyin_size_limit:'图片大小超出上限',
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

function FavoriteRow({item, checked, canSelect, onChange, onRetry}) {
  const title = item.title || item.work_id;
  const titleId = useId();
  const titleRef = useRef(null);
  const [expanded, setExpanded] = useState(false);
  const [truncated, setTruncated] = useState(false);
  const Title = item.selectable ? 'label' : 'div';
  const checkboxId = `${titleId}-checkbox`;
  const status = item.status || 'baseline';
  const quoteError = albumQuoteErrors[item.image_quote_error];
  const [statusText, tone] = quoteError&&['baseline','downloaded'].includes(status)
    ? [quoteError, 'neutral']
    : status==='baseline'&&!item.selectable
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
    {item.selectable && <input id={checkboxId} className="favorites-checkbox" type="checkbox" disabled={!canSelect}
      checked={checked} onChange={event => onChange(item.work_id, event.target.checked)}/>}
    <div className="favorites-video">
      <Title id={titleId} htmlFor={item.selectable ? checkboxId : undefined}
        ref={titleRef} className="favorites-title" data-expanded={expanded || undefined}>{title}</Title>
      <div className="muted">{item.kind === 'image' ? `图文 · ${item.image_count ?? '未知'} 张 · ${item.image_quote_cny ? '费用上限 ¥' + item.image_quote_cny : '报价不可用'}` : '视频'}</div>
      {(truncated || expanded) && <button type="button" className="favorites-expand" aria-expanded={expanded}
        aria-controls={titleId} onClick={() => setExpanded(value => !value)}>{expanded ? '收起' : '展开'}</button>}
    </div>
    <span className="favorites-status" data-tone={tone}>{statusText}
      {item.image_download_error&&status==='download_failed'&&<small>{imageDownloadErrors[item.image_download_error]||item.image_download_error}</small>}
      {item.kind==='image'&&status==='download_failed'&&<button type="button" disabled={!canSelect}
        onClick={()=>onRetry(item.work_id)}>重新下载</button>}
    </span>
  </li>;
}

export function FavoritesPanel({api, pollInterval, disabled}) {
  const [open,setOpen]=useState(false);
  const [data,setData]=useState(null);
  const [filter,setFilter]=useState('all');
  const [selected,setSelected]=useState([]);
  const [rights,setRights]=useState(false);
  const [paidAgreement,setPaidAgreement]=useState(null);
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState('');
  async function refresh(){const result=await api('/douyin/favorites/sync');setData(result);}
  useEffect(()=>{
    if(!open)return;
    let active=true;
    const update=async()=>{try{const value=await api('/douyin/favorites/sync');if(active)setData(value);}catch(e){if(active)setMessage(e.message);}};
    update();
    const timer=setInterval(update,pollInterval);
    return()=>{active=false;clearInterval(timer);};
  },[open,pollInterval]);
  useEffect(()=>{setFilter('all');setSelected([]);setRights(false);},[data?.active_account?.id]);
  async function action(path,body,success){
    setBusy(true);setMessage('');
    try{
      const result=await api(path,{method:'POST',body:JSON.stringify(body)});
      setMessage(typeof success==='function'?success(result):success);
      try{await refresh();}catch{}
      return true;
    }catch(e){setMessage(e.message);return false;}
    finally{setBusy(false);}
  }
  const items=data?.items||[];
  const eligible=items.filter(item=>item.selectable && (item.kind !== 'image' || batchAmount([item.image_quote_cny]) !== null));
  const imported=items.filter(item=>itemStates[item.status]?.[1]==='imported');
  const filters=[
    {key:'all',label:'全部',items},
    {key:'available',label:'可导入',items:eligible},
    {key:'imported',label:'已导入',items:imported},
  ];
  const visibleItems=filters.find(option=>option.key===filter).items;
  const eligibleIds=eligible.map(item=>item.work_id);
  const selectedIds=selected.filter(id=>eligibleIds.includes(id));
  function selectItem(id, checked) {
    setSelected(previous=>checked?[...previous,id]:previous.filter(value=>value!==id));
  }
  const price=data?.manual_video_budget_cny;
  const selectedItems=eligible.filter(item=>selectedIds.includes(item.work_id));
  const imageQuotes=Object.fromEntries(selectedItems.filter(item=>item.kind==='image').map(item=>[item.work_id,item.image_quote_cny]));
  const total=batchAmount(selectedItems.map(item=>item.kind==='image'?item.image_quote_cny:price));
  const selectionKey=JSON.stringify([data?.active_account?.id, price, imageQuotes, ...selectedIds]);
  const paid=paidAgreement===selectionKey;
  useEffect(()=>{setPaidAgreement(null);},[selectionKey]);
  const blocked=disabled||busy;
  const canSelect=!blocked&&data?.state==='ready';
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
      {!!items.length&&<fieldset className="favorites-fieldset">
        <legend>收藏作品</legend>
        <div className="favorites-toolbar">
          <div className="favorites-filters" role="group" aria-label="按导入状态筛选">
            {filters.map(option=><button key={option.key} type="button" aria-pressed={filter===option.key}
              onClick={()=>setFilter(option.key)}>{option.label} <span>{option.items.length}</span></button>)}
          </div>
          <div className="favorites-selection">
            {filter!=='imported'&&<button type="button" disabled={!canSelect||!eligible.length||selectedIds.length===eligible.length}
              onClick={()=>setSelected(eligibleIds)}>全选可导入作品</button>}
            <button type="button" disabled={blocked||!selectedIds.length} onClick={()=>setSelected([])}>清空选择</button>
            <span className="muted" role="status">已选 {selectedIds.length} 条</span>
          </div>
        </div>
        {visibleItems.length ? <>
          <div className="favorites-heading" aria-hidden="true"><span>作品标题</span><span>导入状态</span></div>
          <ul className="favorites-list" role="list">
            {visibleItems.map(item=><FavoriteRow key={item.work_id} item={item} checked={selectedIds.includes(item.work_id)}
              canSelect={canSelect && (item.status==='download_failed' || eligibleIds.includes(item.work_id))} onChange={selectItem}
              onRetry={work_id=>action('/douyin/favorites/retry-image',{account_id:data.active_account?.id,work_id},'已重新排队下载。')}/>)}
          </ul>
        </> : <p className="favorites-empty muted">当前没有{filter==='available'?'可导入':'已导入'}的作品。</p>}
        <div className="favorites-submit">
          {!!selectedIds.length&&total!==null&&<p>本次费用上限 ¥{total}。执行时逐条预留费用，仍受系统累计预算约束。</p>}
          {!data.manual_conversion_available&&<p>当前无法启动手动付费转换。</p>}
          <label><input type="checkbox" checked={rights} disabled={!canSelect}
            onChange={e=>setRights(e.target.checked)}/> 我确认有权下载和处理所选作品</label>
          <label><input type="checkbox" checked={paid} disabled={!canSelect||!selectedIds.length||total===null}
            onChange={e=>setPaidAgreement(e.target.checked?selectionKey:null)}/> 我同意所选作品转换产生费用，按上述上限执行</label>
          <button type="button" className="primary" disabled={!canSelect||!selectedIds.length||!rights||!paid||!data.manual_conversion_available||total===null} onClick={async()=>{
            if(await action('/douyin/favorites/import',{account_id:data.active_account?.id,work_ids:selectedIds,rights_confirmed:true,allow_paid:true,video_budget_cny:price,image_quotes:imageQuotes},
              ({queued})=>queued? `已将 ${queued} 条作品排队下载和转换。`:'所选作品已导入或已在队列中。')){setSelected([]);setPaidAgreement(null);}
          }}>下载并转换所选作品</button>
        </div>
      </fieldset>}
      {message&&<p role="status">{message}</p>}
    </div>}
  </details>;
}
