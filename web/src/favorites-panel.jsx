import React, {useEffect, useState} from 'react';

const states = {scan_queued:'等待读取收藏', scanning:'正在读取收藏', confirm_account:'等待确认账号',
  baseline_pending:'正在建立基线', idle:'等待读取收藏', ready:'收藏已同步', paused:'同步暂停'};
const itemStates = {baseline:'可导入', queued:'等待下载', downloading:'下载中', imported:'已导入', download_failed:'下载失败', existing:'资料已存在', deleted:'资料在回收站', skipped:'已跳过'};
const reasons = {missing_douyin_cookie:'缺少 Cookie', login_required:'需要重新登录', account_unverified:'无法核实登录账号',
  collection_http_error:'抖音拒绝收藏请求', collection_timeout:'收藏读取超时', pagination_incomplete:'收藏翻页未完成',
  baseline_incomplete:'未读满基线且未到末页', snapshot_gap:'未找到上次同步位置',
  snapshot_rebased:'未找到上次同步位置，已重新建立基线', browser_dependency_missing:'服务器缺少浏览器组件',
  douyin_resolver_failed:'下载解析失败，请核对登录状态'};

export function FavoritesPanel({api, pollInterval, disabled}) {
  const [open,setOpen]=useState(false);
  const [data,setData]=useState(null);
  const [selected,setSelected]=useState([]);
  const [rights,setRights]=useState(false);
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
      await api(path,{method:'POST',body:JSON.stringify(body)});
      await refresh();setMessage(success);return true;
    }catch(e){setMessage(e.message);return false;}
    finally{setBusy(false);}
  }
  const eligible=(data?.items||[]).filter(item=>item.selectable);
  const eligibleIds=eligible.map(item=>item.work_id);
  const selectedIds=selected.filter(id=>eligibleIds.includes(id));
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
      {data?.enabled&&<p>每日下载上限 {data.download_limit} 条。所选作品会依次排队，下载完成后可在任务页处理。</p>}
      {data?.queue_counts&&<p>等待下载 {data.queue_counts.queued||0} 条，下载失败 {data.queue_counts.download_failed||0} 条，等待转换 {data.queue_counts.conversion_queued||0} 条。</p>}
      {data?.last_scan&&<p>最近读取 {data.last_scan.day}，读到 {data.last_scan.read_count} 条，新增排队 {data.last_scan.queued_count} 条。</p>}
      {!!data?.items?.length&&<fieldset disabled={blocked||data.state!=='ready'}>
        <legend>收藏视频</legend>
        <div className="actions">
          <button type="button" disabled={!eligible.length} onClick={()=>setSelected(eligibleIds)}>全选可导入视频</button>
          <button type="button" disabled={!selectedIds.length} onClick={()=>setSelected([])}>清空选择</button>
        </div>
        <p>已选 {selectedIds.length} 条</p>
        {data.items.map(item=><label key={item.work_id} style={{display:'block'}}>
          <input type="checkbox" disabled={!item.selectable} checked={selectedIds.includes(item.work_id)}
            onChange={e=>setSelected(previous=>e.target.checked?[...previous,item.work_id]:previous.filter(id=>id!==item.work_id))}/>
          {item.title||item.work_id} · {itemStates[item.status||'baseline']||item.status}
        </label>)}
        <label><input type="checkbox" checked={rights} onChange={e=>setRights(e.target.checked)}/> 我确认有权下载和处理所选作品</label>
        <button type="button" disabled={!selectedIds.length||!rights} onClick={async()=>{
          if(await action('/douyin/favorites/import',{account_id:data.active_account?.id,work_ids:selectedIds,rights_confirmed:true},'所选作品已排队等待下载。'))setSelected([]);
        }}>下载并导入所选视频</button>
      </fieldset>}
      {message&&<p role="status">{message}</p>}
    </div>}
  </details>;
}
