export function labelIds(items=[]) {return items.map(x=>x.id);}
export function splitAliases(value) {return value.split(/[,，\n]/).map(x=>x.trim()).filter(Boolean);}
export const UNCLASSIFIED_TOPIC = Symbol('unclassified');
export function isUnclassifiedSource(source) {return !source.deleted&&!source.classification?.topics?.length;}
export function filterSources(sources,filters) {
  const q=(filters.q||'').trim().toLocaleLowerCase();
  return sources.filter(s=>!s.deleted&&(!filters.unclassified||isUnclassifiedSource(s))&&(!filters.kind||s.kind===filters.kind||(filters.kind==='video'&&s.kind==='mp4'))&&(!filters.review||(s.review_status||'pending')===filters.review)&&(!q||(s.original_name+' '+(s.title||'')).toLocaleLowerCase().includes(q))&&['topics','tags'].every(kind=>!(filters[kind]||[]).length||(s.classification?.[kind]||[]).some(x=>filters[kind].includes(x.id))));
}

export function douyinErrorText(code) {
  switch (code) {
    case 'media_tool_missing': return '未找到视频检测工具，请检查配置';
    case 'download_denied': return '平台禁止下载该作品';
    case 'download_permission_unknown': return '无法确认该作品的下载权限';
    case 'douyin_resolver_failed': return '作品解析失败，请稍后重试';
    default: return '下载失败，请稍后重试';
  }
}

export function suggestionSelection(s={}) {return {existing_topics:[...(s.existing_topics||[])],existing_tags:[...(s.existing_tags||[])],confirmed_new_topics:[],confirmed_new_tags:[]};}
export function suggestionError(code='') {
  if (/conflict|刷新/.test(code)) return '资料或分类目录已变化，请刷新后重新生成建议。';
  if (/worker_busy/.test(code)) return '系统正忙，其他任务正在执行，请稍后再试。';
  if (/suggestions_disabled|invalid_config|missing_model_credentials/.test(code)) return '分类建议尚未启用或配置不完整。';
  if (/budget|reservation/.test(code)) return '模型预算不足，无法生成建议。';
  return '分类建议操作未完成，请稍后查看状态。';
}

