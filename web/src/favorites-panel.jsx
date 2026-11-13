import React, {useEffect, useState} from 'react';

const states = {scan_queued:'等待读取收藏', scanning:'正在读取收藏', confirm_account:'等待确认账号',
  baseline_pending:'正在建立基线', idle:'等待读取收藏', ready:'收藏已同步', paused:'同步暂停'};
const itemStates = {baseline:'可导入', queued:'等待下载', downloading:'下载中', imported:'已导入', downloaded:'已下载，等待转换',
  conversion_queued:'转换已排队', converted:'转换完成', conversion_failed:'转换异常，请查看任务详情',
  download_failed:'下载失败', existing:'资料已存在', deleted:'资料在回收站', skipped:'已跳过'};
const reasons = {missing_douyin_cookie:'缺少 Cookie', login_required:'需要重新登录', account_unverified:'无法核实登录账号',
  collection_http_error:'抖音拒绝收藏请求', collection_timeout:'收藏读取超时', pagination_incomplete:'收藏翻页未完成',
  baseline_incomplete:'未读满基线且未到末页', snapshot_gap:'未找到上次同步位置',
  snapshot_rebased:'未找到上次同步位置，已重新建立基线', browser_dependency_missing:'服务器缺少浏览器组件',
  douyin_resolver_failed:'下载解析失败，请核对登录状态'};

function batchAmount(value, count) {
  if (typeof value !== 'string' || !/^\d+(?:\.\d+)?$/.test(value)) return null;
  const [whole, fraction=''] = value.split('.');
  const scale = Math.max(2, fraction.length);
  const units = BigInt(whole + fraction.padEnd(scale, '0')) * BigInt(count);
  const digits = units.toString().padStart(scale + 1, '0');
  return `${digits.slice(0, -scale)}.${digits.slice(-scale)}`;
}

export function FavoritesPanel({api, pollInterval, disabled}) {
  const [open,setOpen]=useState(false);
  const [data,setData]=useState(null);
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
  useEffect(()=>{setSelected([]);setRights(false);},[data?.active_account?.id]);
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
  const eligible=(data?.items||[]).filter(item=>item.selectable);
  const eligibleIds=eligible.map(item=>item.work_id);
  const selectedIds=selected.filter(id=>eligibleIds.includes(id));
  const price=data?.manual_video_budget_cny;
  const total=batchAmount(price, selectedIds.length);
  const selectionKey=JSON.stringify([data?.active_account?.id, price, ...selectedIds]);
  const paid=paidAgreement===selectionKey;
  useEffect(()=>{setPaidAgreement(null);},[selectionKey]);
  const blocked=disabled||busy;
  return <details onToggle={event=>setOpen(event.currentTarget.open)}>
    <summary>抖音收藏</summary>
    {open&&<div className="management">
      {data?.enabled&&<p>首次确认账号后记录最近 {data.baseline_limit ?? 100} 条收藏，选择视频后可排队下载并导入。</p>}
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
      {!!data?.items?.length&&<fieldset disabled={blocked||data.state!=='ready'}>
        <legend>收藏视频</legend>
        <div className="actions">
          <button type="button" disabled={!eligible.length} onClick={()=>setSelected(eligibleIds)}>全选可导入视频</button>
          <button type="button" disabled={!selectedIds.length} onClick={()=>setSelected([])}>清空选择</button>
        </div>
        <p>已选 {selectedIds.length} 条</p>
        {!!selectedIds.length&&total!==null&&<p>每条转换费用上限 ¥{price}，本次费用上限 ¥{total}。执行时逐条预留费用，仍受系统累计预算约束。</p>}
        {!data.manual_conversion_available&&<p>当前无法启动手动付费转换。</p>}
        {data.items.map(item=><label key={item.work_id} style={{display:'block'}}>
          <input type="checkbox" disabled={!item.selectable} checked={selectedIds.includes(item.work_id)}
            onChange={e=>setSelected(previous=>e.target.checked?[...previous,item.work_id]:previous.filter(id=>id!==item.work_id))}/>
          {item.title||item.work_id} · {itemStates[item.status||'baseline']||item.status}
        </label>)}
        <label><input type="checkbox" checked={rights} onChange={e=>setRights(e.target.checked)}/> 我确认有权下载和处理所选作品</label>
        <label><input type="checkbox" checked={paid} disabled={!selectedIds.length||total===null} onChange={e=>setPaidAgreement(e.target.checked?selectionKey:null)}/> 我同意所选视频转换产生费用，按上述上限执行</label>
        <button type="button" disabled={!selectedIds.length||!rights||!paid||!data.manual_conversion_available||total===null} onClick={async()=>{
          if(await action('/douyin/favorites/import',{account_id:data.active_account?.id,work_ids:selectedIds,rights_confirmed:true,allow_paid:true,video_budget_cny:price},
            ({queued})=>queued? `已将 ${queued} 条作品排队下载和转换。`:'所选作品已导入或已在队列中。')){setSelected([]);setPaidAgreement(null);}
        }}>下载并转换所选视频</button>
      </fieldset>}
      {message&&<p role="status">{message}</p>}
    </div>}
  </details>;
}
