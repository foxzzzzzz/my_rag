import React, {useEffect, useRef, useState} from 'react';
import {formatDate} from './helpers';
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
      setData(previous => ({...result, favorites_limits:previous.favorites_limits}));
      setAmount(result.limit_cny);
      setMessage('预算上限已保存。');
      onSaved().catch(()=>{});
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(null);
    }
  }

  const favoritesValid = wholeNumber(maxImages) && Number(maxImages) > 0 && wholeNumber(downloadLimit);
  const favorites = data?.favorites_limits;
  const favoritesChanged = favorites && (Number(maxImages)!==favorites.max_images || Number(downloadLimit)!==favorites.download_limit);
  async function saveFavorites(event) {
    event.preventDefault();
    if (!favoritesValid || !favoritesChanged || disabled || busy || loading) return;
    setSaving('favorites');
    setFavoritesError('');
    setFavoritesMessage('');
    try {
      const result = await apiRef.current('/budget/favorites-limits', {method:'PATCH', body:JSON.stringify({max_images:Number(maxImages), download_limit:Number(downloadLimit), expected_revision:favorites.revision})});
      setData(previous => ({...previous, favorites_limits:result}));
      setMaxImages(String(result.max_images));
      setDownloadLimit(String(result.download_limit));
      setFavoritesMessage('收藏处理限制已保存。');
      onSaved().catch(()=>{});
    } catch (err) {
      setFavoritesError(err.message);
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
        <p className="muted">今日（{favorites.day}）定时下载已用 {favorites.downloads_used} / {favorites.download_limit} 条。已派发的下载继续执行。</p>
        <form onSubmit={saveFavorites} className="budget-form budget-favorites-form">
          <label>图文常规上限（张/篇）<input type="number" inputMode="numeric" min="1" step="1" value={maxImages} onChange={event=>setMaxImages(event.target.value)} disabled={disabled||busy||loading} aria-describedby="favorites-preview" /></label>
          <label>定时下载上限（条/天）<input type="number" inputMode="numeric" min="0" step="1" value={downloadLimit} onChange={event=>setDownloadLimit(event.target.value)} disabled={disabled||busy||loading} aria-describedby="favorites-preview" /></label>
          <button className="primary" disabled={disabled||busy||loading||!favoritesValid||!favoritesChanged}>{saving==='favorites'?'保存中…':'保存限制'}</button>
        </form>
        <p id="favorites-preview" className="muted">{favoritesValid
          ? `${favoritesChanged?'保存后每篇最多 '+maxImages+' 张，':''}今日剩余 ${Math.max(0, Number(downloadLimit)-favorites.downloads_used)} 个定时下载名额。设为 0 可暂停派发新的定时下载。`
          : '图片上限至少为 1，下载名额可以为 0。两项均须为整数。'}</p>
        {favoritesError && <p className="error" role="alert">{favoritesError}</p>}
        {favoritesMessage && <p role="status">{favoritesMessage}</p>}
        <h3>收藏限制调整记录</h3>
        {favorites.changes?.length ? <ul className="budget-changes">{favorites.changes.map((change,index)=><li key={`${change.changed_at}-${index}`}><time dateTime={change.changed_at}>{formatDate(change.changed_at,displayTimezone)}</time>　每篇图片 {change.previous_max_images} → {change.max_images} 张 · 每日下载 {change.previous_download_limit} → {change.download_limit} 条</li>)}</ul> : <p className="muted">暂无调整记录。</p>}
      </section>}
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
