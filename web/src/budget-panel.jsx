import React, {useEffect, useRef, useState} from 'react';
import {errorText, formatDate} from './helpers';
import './budget.css';

function scaled(value) {
  const match = /^(\d+)(?:\.(\d+))?$/.exec(String(value));
  if (!match) return null;
  const fraction = match[2] || '';
  return {number: BigInt(match[1] + fraction), scale: fraction.length};
}

function remaining(limit, used) {
  const left = scaled(limit), right = scaled(used);
  if (!left || !right) return null;
  const scale = Math.max(left.scale, right.scale);
  const amount = left.number * 10n ** BigInt(scale - left.scale) - right.number * 10n ** BigInt(scale - right.scale);
  const digits = (amount > 0n ? amount : 0n).toString().padStart(scale + 1, '0');
  return scale ? `${digits.slice(0, -scale)}.${digits.slice(-scale)}` : digits;
}

function money(value) {
  return value == null ? '待核对' : `¥${value}`;
}

function validMoney(value) {
  return /^(?:0|[1-9]\d*)(?:\.\d{1,2})?$/.test(value);
}

function canonicalMoney(value) {
  const [whole, fraction=''] = value.split('.');
  return [whole, fraction.padEnd(2, '0')].join('.');
}

function wholeNumber(value) {
  return /^(0|[1-9]\d*)$/.test(value) && Number.isSafeInteger(Number(value));
}

export function BudgetPanel({api, disabled, titleProps, displayTimezone, onSaved}) {
  const apiRef = useRef(api);
  apiRef.current = api;
  const [data, setData] = useState(null);
  const [amount, setAmount] = useState('');
  const [saving, setSaving] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [maxImages, setMaxImages] = useState('');
  const [downloadLimit, setDownloadLimit] = useState('');
  const [videoBudget, setVideoBudget] = useState('');
  const [dailyBudget, setDailyBudget] = useState('');
  const [authorization, setAuthorization] = useState(null);
  const [authAmount, setAuthAmount] = useState('');
  const [consent, setConsent] = useState(false);
  const requestId = useRef(null);
  const authorizationDialog = useRef(null);
  const [authorizationError, setAuthorizationError] = useState('');
  const [authorizationMessage, setAuthorizationMessage] = useState('');
  const [favoritesError, setFavoritesError] = useState('');
  const [favoritesMessage, setFavoritesMessage] = useState('');
  const busy = saving !== null;

  async function refresh() {
    setLoading(true);
    setError('');
    setMessage('');
    try {
      const result = await apiRef.current('/budget', {headers:{'X-PKB-Activity':'user'}});
      setData(result);
      setAmount(result.limit_cny);
      if (result.favorites_limits) {
        setMaxImages(String(result.favorites_limits.max_images));
        setDownloadLimit(String(result.favorites_limits.download_limit));
        setVideoBudget(String(result.favorites_limits.video_budget_cny ?? ""));
        setDailyBudget(String(result.favorites_limits.daily_budget_cny ?? ""));
      }
      setFavoritesError('');
      setFavoritesMessage('');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { refresh(); }, []);

  const valid = /^(?:0|[1-9]\d*)(?:\.\d{1,2})?$/.test(amount) && scaled(amount)?.number > 0n;
  const projected = data && valid ? remaining(amount, data.reserved_cny) : null;

  async function save(event) {
    event.preventDefault();
    if (!valid || !data || busy || loading || disabled) return;
    setSaving('amount');
    setError('');
    setMessage('');
    try {
      const result = await apiRef.current('/budget', {method:'PATCH', body:JSON.stringify({limit_cny:amount, expected_revision:data.revision})});
      setData(result);
      setAmount(result.limit_cny);
      setMessage('预算上限已保存。');
      onSaved().catch(()=>{});
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(null);
    }
  }

  const favoritesValid = wholeNumber(maxImages) && Number(maxImages) > 0 && wholeNumber(downloadLimit) &&
    validMoney(videoBudget) && Number(videoBudget)>0 && validMoney(dailyBudget);
  const favorites = data?.favorites_limits;
  const videoBudgetChanged = favorites && validMoney(videoBudget) && canonicalMoney(videoBudget)!==favorites.video_budget_cny;
  const dailyBudgetChanged = favorites && validMoney(dailyBudget) && canonicalMoney(dailyBudget)!==favorites.daily_budget_cny;
  const favoritesChanged = favorites && (Number(maxImages)!==favorites.max_images ||
    Number(downloadLimit)!==favorites.download_limit || videoBudgetChanged || dailyBudgetChanged);
  async function saveFavorites(event) {
    event.preventDefault();
    if (!favoritesValid || !favoritesChanged || disabled || busy || loading) return;
    setSaving('favorites');
    setFavoritesError('');
    setFavoritesMessage('');
    try {
      const payload = {max_images:Number(maxImages), download_limit:Number(downloadLimit), expected_revision:favorites.revision};
      if (videoBudgetChanged) payload.video_budget_cny = canonicalMoney(videoBudget);
      if (dailyBudgetChanged) payload.daily_budget_cny = canonicalMoney(dailyBudget);
      const result = await apiRef.current('/budget/favorites-limits', {method:'PATCH', body:JSON.stringify(payload)});
      setData(previous => ({...previous, favorites_limits:result}));
      setMaxImages(String(result.max_images));
      setDownloadLimit(String(result.download_limit));
      setVideoBudget(String(result.video_budget_cny));
      setDailyBudget(String(result.daily_budget_cny));
      setFavoritesMessage('收藏处理限制已保存。');
      onSaved().catch(()=>{});
    } catch (err) {
      setFavoritesError(err.message);
    } finally {
      setSaving(null);
    }
  }

  function openAuthorization(item) {
    setAuthorization(item);
    setAuthAmount(item.required_cny);
    setConsent(false);
    setAuthorizationError('');
    setAuthorizationMessage('');
    requestId.current = crypto.randomUUID();
  }

  function closeAuthorization() {
    authorizationDialog.current?.close();
    setAuthorization(null);
    requestId.current = null;
  }

  const authorizationValid = authorization && validMoney(authAmount) &&
    Number(authAmount)>=Number(authorization.required_cny) &&
    (authorization.available_cny==null || Number(authAmount)<=Number(authorization.available_cny));

  async function authorize(event) {
    event.preventDefault();
    if (disabled || !consent || !authorizationValid || busy) return;
    setSaving('authorization');
    setAuthorizationError('');
    try {
      const payload = {allow_paid:true, amount_cny:canonicalMoney(authAmount),
        expected_ceiling_cny:authorization.authorized_cny, expected_required_cny:authorization.required_cny,
        request_id:requestId.current};
      await apiRef.current('/tasks/'+authorization.task_id+'/reauthorize-favorites', {
        method:'POST', body:JSON.stringify(payload),
      });
      setData(previous=>({...previous, favorites_reauthorizations:previous.favorites_reauthorizations
        .filter(item=>item.task_id!==authorization.task_id)}));
      closeAuthorization();
      setAuthorizationMessage('已重新授权，任务已排队。');
      onSaved().catch(()=>{});
    } catch (err) {
      setAuthorizationError(err.message);
    } finally {
      setSaving(null);
    }
  }
  return <section className="budget-page">
    <div className="page-heading"><h1 {...titleProps}>预算</h1><button type="button" disabled={loading||busy} onClick={refresh}>刷新预算</button></div>
    {error && <p className="error" role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
    {!data ? <p role="status">{error ? '预算暂不可用。' : '正在读取预算…'}</p> : <>
      <dl className="budget-overview">
        <div><dt>项目累计上限</dt><dd>{money(data.limit_cny)}</dd></div>
        <div><dt>账本占用</dt><dd>{money(data.reserved_cny)}</dd></div>
        <div><dt>可用额度</dt><dd>{money(data.available_cny)}</dd></div>
        <div><dt>已知消耗预估</dt><dd>{money(data.estimated_cost_cny)}</dd><small>待核对 {data.unknown_count} 项</small></div>
      </dl>
      <p className="muted">账本占用包含历史预留及已核算金额。实际费用以模型服务账单为准。</p>
      <section className="budget-section"><h2>调整累计上限</h2>
        <form onSubmit={save} className="budget-form">
          <label>项目累计上限（元）<input inputMode="decimal" value={amount} onChange={event=>setAmount(event.target.value)} disabled={disabled||busy||loading} aria-describedby="budget-preview" /></label>
          <button className="primary" disabled={disabled||busy||loading||!valid||amount===data.limit_cny}>{saving==='amount'?'保存中…':'保存上限'}</button>
        </form>
        <p id="budget-preview" className="muted">{valid ? `当前上限 ${money(data.limit_cny)}，调整后 ${money(amount)}，预计可用 ${money(projected)}。` : '请输入大于零、最多两位小数的金额。'}</p>
      </section>
      <section className="budget-section"><h2>常规单次上限</h2>
        <p className="muted">视频和图文 {money(data.run_limits.video)} · 网页 {money(data.run_limits.html)} · 问答 {money(data.run_limits.rag)} · 分类建议 {money(data.run_limits.classification)}</p>
      </section>
      {favorites&&<section className="budget-section"><h2>收藏处理限制</h2>
        <p className="muted">今日（{favorites.day}）定时下载已用 {favorites.downloads_used} / {favorites.download_limit} 条，转换已用 {favorites.conversions_used ?? 0} / {favorites.download_limit} 条。转换预算已预留 {money(favorites.conversion_reserved_cny)}，剩余 {money(favorites.conversion_remaining_cny)}。</p>
        <form onSubmit={saveFavorites} className="budget-form budget-favorites-form">
          <label>图文常规上限（张/篇）<input type="number" inputMode="numeric" min="1" step="1" value={maxImages} onChange={event=>setMaxImages(event.target.value)} disabled={disabled||busy||loading} aria-describedby="favorites-preview" /></label>
          <label>每日定时处理上限（条/天）<input type="number" inputMode="numeric" min="0" step="1" value={downloadLimit} onChange={event=>setDownloadLimit(event.target.value)} disabled={disabled||busy||loading} aria-describedby="favorites-preview" /></label>
          <label>单视频预留上限（元）<input inputMode="decimal" value={videoBudget} onChange={e=>setVideoBudget(e.target.value)} disabled={disabled||busy||loading}/></label>
          <label>每日转换预算（元）<input inputMode="decimal" value={dailyBudget} onChange={e=>setDailyBudget(e.target.value)} disabled={disabled||busy||loading}/></label>
          <button className="primary" disabled={disabled||busy||loading||!favoritesValid||!favoritesChanged}>{saving==='favorites'?'保存中…':'保存限制'}</button>
        </form>
        <p id="favorites-preview" className="muted">{favoritesValid
          ? '按表单设置，今日还可派发 '+Math.max(0, Number(downloadLimit)-favorites.downloads_used)+' 条下载、'+
            Math.max(0, Number(downloadLimit)-favorites.conversions_used)+' 条转换。转换另受当日预算限制。'
          : '图片上限至少为 1，每日条数可为 0。单视频金额须大于 0，每日预算可为 0，金额最多两位小数。'}</p>
        {favoritesError && <p className="error" role="alert">{favoritesError}</p>}
        {favoritesMessage && <p role="status">{favoritesMessage}</p>}
        <h3>收藏限制调整记录</h3>
        {favorites.changes?.length ? <ul className="budget-changes">{favorites.changes.map((change,index)=><li key={`${change.changed_at}-${index}`}><time dateTime={change.changed_at}>{formatDate(change.changed_at,displayTimezone)}</time>　每篇图片 {change.previous_max_images} → {change.max_images} 张 · 每日名额 {change.previous_download_limit} → {change.download_limit} 条{change.video_budget_cny != null && <> · 单视频 {money(change.previous_video_budget_cny)} → {money(change.video_budget_cny)}</>}{change.daily_budget_cny != null && <> · 每日转换 {money(change.previous_daily_budget_cny)} → {money(change.daily_budget_cny)}</>}</li>)}</ul> : <p className="muted">暂无调整记录。</p>}
      </section>}
      {(favorites || data.favorites_reauthorizations?.length>0 || authorizationMessage)&&<section className="budget-section">
        <h2>需要重新授权的任务</h2>
        {authorizationMessage&&<p role="status">{authorizationMessage}</p>}
        {data.favorites_reauthorizations?.length ? <ul className="budget-authorization-list">
          {data.favorites_reauthorizations.map(item=><li key={item.task_id}>
            <div>
              <strong>{item.title || item.task_id}</strong>
              <div className="muted">已授权 {money(item.authorized_cny)}
                {item.required_cny!=null&&<> · 所需预留 {money(item.required_cny)}</>}
                {item.blocked_reason&&<> · {errorText(400,item.blocked_reason)}</>}
              </div>
            </div>
            <button type="button" disabled={disabled||busy||!!item.blocked_reason||item.required_cny==null}
              onClick={()=>openAuthorization(item)}>重新授权</button>
          </li>)}
        </ul> : <p className="muted">暂无需要重新授权的任务。</p>}
      </section>}
      {authorization&&<dialog ref={node=>{authorizationDialog.current=node; if(node&&!node.open) node.showModal();}}
        aria-labelledby="reauthorize-title" className="favorites-dialog budget-authorization-dialog" onCancel={event=>{
          event.preventDefault();
          if (!busy) closeAuthorization();
        }}>
        <h2 id="reauthorize-title">确认重新授权</h2>
        <p>{authorization.title || authorization.task_id}</p>
        <p>原授权 {money(authorization.authorized_cny)} · 本次至少需预留 {money(authorization.required_cny)}</p>
        <form onSubmit={authorize}>
          <label>本次授权上限（元）<input inputMode="decimal" value={authAmount} disabled={busy} onChange={event=>{
            setAuthAmount(event.target.value);
            requestId.current=crypto.randomUUID();
          }}/></label>
          {authorization.available_cny!=null&&<p className="muted">当前最多可授权 {money(authorization.available_cny)}。</p>}
          <label className="budget-authorization-consent"><input type="checkbox" checked={consent} disabled={busy}
            onChange={event=>setConsent(event.target.checked)}/> 我同意本次转换可能产生的模型费用</label>
          {authorizationError&&<p role="alert" className="error">{authorizationError}</p>}
          <div className="budget-authorization-actions">
            <button type="button" disabled={busy} onClick={closeAuthorization}>取消</button>
            <button type="submit" className="primary" disabled={disabled||busy||!consent||!authorizationValid}>确认授权</button>
          </div>
        </form>
      </dialog>}
      <section className="budget-section"><h2>账本明细</h2>
        {data.entries.length ? <div className="budget-table-wrap"><table className="budget-table"><thead><tr><th>任务 / 请求</th><th>步骤</th><th>账本占用</th><th>消耗预估</th></tr></thead><tbody>
          {data.entries.map(entry=><tr key={entry.request_id}>
            <td title={entry.request_id}>{entry.label || entry.run_id}</td><td>{entry.stage || '—'}</td>
            <td>{money(entry.reserved_cny)}{entry.reserved_limit_cny!=null&&<small className="budget-reservation">预留上限 {money(entry.reserved_limit_cny)}</small>}</td>
            <td>{money(entry.estimated_cost_cny)}</td>
          </tr>)}
        </tbody></table></div> : <p className="muted">暂无账本记录。</p>}
      </section>
      <section className="budget-section"><h2>上限调整记录</h2>
        {data.changes.length ? <ul className="budget-changes">{data.changes.map((change,index)=><li key={`${change.changed_at}-${index}`}><time dateTime={change.changed_at}>{formatDate(change.changed_at,displayTimezone)}</time>　{money(change.previous_limit_cny)} → {money(change.limit_cny)}</li>)}</ul> : <p className="muted">暂无调整记录。</p>}
      </section>
    </>}
  </section>;
}
