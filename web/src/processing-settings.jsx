import React, {useEffect, useRef, useState} from 'react';

const mediaFields = [
  ['asr_upload_bytes', '转写音频大小上限', 'size'],
  ['video_upload_bytes', '本地视频大小上限', 'size'],
  ['html_upload_bytes', '网页文件大小上限', 'size'],
  ['douyin_video_download_bytes', '抖音视频下载上限', 'size'],
  ['douyin_image_bytes', '抖音单张图片上限', 'size'],
  ['douyin_album_bytes', '抖音图文总大小上限', 'size'],
];
const scheduleFields = [
  ['daily_at', '每日读取时间', 'time'],
  ['schedule_enabled', '每天定时读取收藏', 'bool'],
  ['auto_download', '自动下载收藏', 'bool'],
  ['conversion_enabled', '自动转换收藏（产生模型费用）', 'bool'],
];
const editableFields = [...mediaFields, ...scheduleFields];
const mib = 1024 * 1024;

function formValues(settings) {
  return Object.fromEntries(editableFields.filter(([key]) => settings[key]).map(([key,,type]) =>
    [key, type === 'size' ? String(settings[key].value / mib) : settings[key].value]));
}

export function ProcessingSettings({api, onBack, onSaved, focusKey, titleProps}) {
  const apiRef = useRef(api);
  const focused = useRef(false);
  apiRef.current = api;
  const [data, setData] = useState(null);
  const [values, setValues] = useState({});
  const [message, setMessage] = useState('');
  const [errorMessage, setErrorMessage] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let live = true;
    apiRef.current('/processing-settings', {headers:{'X-PKB-Activity':'user'}}).then(result => {
      if (!live) return;
      setData(result);
      setValues(formValues(result.settings));
    }).catch(error => {if (live) setErrorMessage(error.message);});
    return () => {live = false;};
  }, []);
  useEffect(() => {
    if (data && focusKey && !focused.current) {
      document.getElementById('processing-'+focusKey)?.focus();
      focused.current = true;
    }
  }, [data, focusKey]);
  async function save(event) {
    event.preventDefault();
    const changed = {};
    for (const [key,,type] of editableFields) {
      const setting = data.settings[key];
      if (!setting || setting.editable === false) continue;
      const value = type === 'size' ? Number(values[key]) * mib : values[key];
      if (type === 'size' && (!Number.isSafeInteger(value) || value <= 0)) {
        setErrorMessage('请输入有效的大小上限。'); return;
      }
      if (value !== setting.value) changed[key] = value;
    }
    if (!Object.keys(changed).length) {setErrorMessage(''); setMessage('设置没有变化。'); return;}
    if (('auto_download' in changed || 'conversion_enabled' in changed) && values.conversion_enabled && !values.auto_download) {
      setErrorMessage('启用自动转换需要同时启用自动下载。');
      return;
    }
    setBusy(true); setMessage(''); setErrorMessage('');
    try {
      const result = await api('/processing-settings', {method:'PATCH', body:JSON.stringify({expected_revision:data.revision, values:changed})});
      setData(result);
      setValues(formValues(result.settings));
      try {await onSaved(); setMessage('设置已保存。');} catch {setMessage('设置已保存，工作区需要刷新。');}
    } catch (error) {setErrorMessage(error.code === 'revision_conflict' ? '设置已在其他窗口修改，请返回后重新打开并确认。' : error.code === 'invalid_request' ? '设置无效，请检查数值和允许范围。' : error.message);}
    finally {setBusy(false);}
  }
  function renderField([key,label,type]) {
    const setting = data.settings[key];
    if (!setting) return null;
    if (type === 'bool') return <label key={key} className="processing-setting-toggle"><input type="checkbox" checked={!!values[key]} disabled={busy || setting.editable === false} onChange={e=>setValues({...values,[key]:e.target.checked})}/>{label}</label>;
    const min = type === 'size' && setting.min != null ? setting.min / mib : undefined;
    const max = type === 'size' && setting.max != null ? setting.max / mib : undefined;
    return <label key={key}>{label}{type === 'size' ? '（MiB）' : ''}
      <input id={'processing-'+key} type={type === 'time' ? 'time' : 'number'} min={min} max={max} step={type === 'size' ? 'any' : undefined} value={values[key] ?? ''} disabled={busy || setting.editable === false} onChange={e=>setValues({...values,[key]:e.target.value})}/>
      {(min != null || max != null) && <small className="muted">允许范围 {min ?? '—'}–{max ?? '—'} MiB</small>}
    </label>;
  }
  return <>
    <div className="page-heading"><h1 {...titleProps}>导入与转换设置</h1><button type="button" onClick={onBack}>返回</button></div>
    <section className="import-panel processing-settings-panel">
      <p className="muted">失败任务需要手动恢复。</p>
      {!data && !errorMessage && <p role="status">正在读取设置…</p>}
      {data && <form onSubmit={save}>
        <section className="budget-section"><h2>媒体大小</h2><div className="processing-settings-sizes">{mediaFields.map(renderField)}</div></section>
        <section className="budget-section"><h2>抖音定时处理</h2>
          {data.timezone && <p className="muted">时区 {data.timezone}</p>}
          {!data.settings.schedule_enabled?.editable && <p className="muted">当前部署未启用抖音收藏同步。</p>}
          <div className="processing-settings-schedule">{scheduleFields.map(renderField)}</div>
          {data.settings.schedule_enabled?.editable && <p className="muted">已排队的收藏由自动下载和自动转换开关控制。</p>}
        </section>
        {data.settings.max_attempts && <p className="muted">常规尝试上限 {data.settings.max_attempts.value} 次</p>}
        <button className="primary" disabled={busy}>{busy ? '保存中…' : '保存设置'}</button>
      </form>}
      {errorMessage && <p role="alert">{errorMessage}</p>}
      {message && <p role="status">{message}</p>}
    </section>
  </>;
}
