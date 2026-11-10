export function validReview(score, decision, target, reviewer) { const n=Number(score); return score !== '' && Number.isFinite(n) && n>=0 && n<=100 && !!reviewer.trim() && (decision !== 'approve' || n>=target); }
export function errorText(status, code) {
  if (code==='trash_expired') return '这份资料已过撤销期限，等待定期维护清理。';
  if (code==='worker_busy') return '后台正在处理任务，请稍后再试。';
  if (code==='unknown_submission') return '模型请求结果未知，系统已阻止重发。原预算预留已保留。';
  if (code==='task_archived') return '任务已归档，请先取消归档。';
  return status===409 ? '内容已有更新，请刷新后重新操作。' : `操作失败：${code || status || '网络连接异常'}`;
}
export function textValue(v) { return typeof v === 'string' ? v : v == null ? '' : JSON.stringify(v,null,2); }
export function uploadError(file, config) { let html=/\.html?$/i.test(file.name); if(!html&&!/\.mp4$/i.test(file.name)) return '仅支持 HTML 和 MP4 文件'; if(file.size>config.max_upload_bytes || (html&&file.size>config.max_html_bytes)) return '文件超过大小限制'; return ''; }
export function progressText(p, status) { const terminal={succeeded:'处理完成',completed:'处理完成',failed:'处理失败',cancelled:'已取消',needs_attention:'等待确认'}; if(terminal[status]&&(!p||(p.completed_frames==null&&p.completed_stages==null)))return terminal[status]; if(status==='queued' && (!p || (p.completed_frames==null && p.completed_stages==null))) return '待开始'; if(!p)return '等待进度'; let a=[]; if(p.completed_frames!=null)a.push(`帧 ${p.completed_frames}${p.total_frames==null?'':` / ${p.total_frames}`}`); if(p.completed_stages!=null)a.push(`阶段 ${p.completed_stages}${p.total_stages==null?'':` / ${p.total_stages}`}`); return a.join(' · ')||'处理中'; }
export function statusText(s) { if (/^vision-\d+$/.test(s || '')) return `视觉分析 · 帧 ${s.slice(7)}`; return ({succeeded:'已完成',preparing_video:'准备视频',extracting_html:'提取网页',asr_submit:'提交转录',asr_result:'获取转录结果',text:'生成文本','html-text':'整理网页文本',verifying_source:'校验来源',loading_provider_result:'读取处理结果',queued:'排队中',pending:'待处理',running:'处理中',completed:'已完成',failed:'失败',cancelled:'已取消',needs_attention:'需要关注',approve:'批准',reject:'拒绝',rework:'返工',extract:'提取',extracting:'提取中',transcribe:'转录',visual:'视觉分析',summarize:'生成摘要'})[s]||s||'等待处理'; }

export function formatDate(value, timeZone) { if (!value) return ''; const date = new Date(value); if (Number.isNaN(date.getTime())) return value; try { return new Intl.DateTimeFormat('zh-CN', {timeZone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(date); } catch { return value; } }

export function connectionText(state) { return ({connecting:'正在连接服务…',connected:'服务已连接',disconnected:'服务未连接'})[state]; }

const bodyPreviewPrefix = '正文预览：';
const sentenceSegmenter = typeof Intl.Segmenter === 'function'
  ? new Intl.Segmenter('zh', {granularity:'sentence'}) : null;
const sentenceEnd = /[。！？.!?]["'”’」』）】》)\]]*$/u;
const fallbackSentenceEnd = /[。！？]+["'”’」』）】》)\]]*|[.!?]+["'”’」』）】》)\]]*(?=\s|$)/gu;
const abbreviation = /(?:\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|e\.g|i\.e)|\b[A-Z])$/u;

function endsWithAbbreviation(body, punctuation, mark) {
  return mark === '.' && abbreviation.test(body.slice(0, punctuation));
}

export function htmlBodyPreview(kind, {body, summary, provenance}) {
  if (kind !== 'html' || !['local_extraction', 'human_edited'].includes(provenance)
      || typeof body !== 'string' || typeof summary !== 'string'
      || !summary.startsWith(bodyPreviewPrefix)) return null;
  // The stored extract carries the length used when this version was created.
  const extract = summary.slice(bodyPreviewPrefix.length);
  if (!extract || !body.startsWith(extract)) return null;
  if (extract === body) return {text:body, omitted:false};

  let boundary = 0;
  for (const {segment, index} of sentenceSegmenter?.segment(body) ?? []) {
    const sentence = segment.trimEnd();
    const end = index + sentence.length;
    if (end > extract.length) break;
    const ending = sentence.match(sentenceEnd);
    if (ending && !endsWithAbbreviation(body, index + ending.index, ending[0][0])) boundary = end;
  }
  // ICU can join sentences when the next word begins with a lower-case letter, as in iPhone.
  for (const match of body.matchAll(fallbackSentenceEnd)) {
    const end = match.index + match[0].length;
    if (end > extract.length) break;
    if (end <= boundary) continue;
    if (sentenceSegmenter && !/^\s+["'“‘「『]*[a-z][A-Z]/u.test(body.slice(end))) continue;
    if (endsWithAbbreviation(body, match.index, match[0][0])) continue;
    boundary = end;
  }
  return {text:boundary ? body.slice(0, boundary) : extract.trimEnd(), omitted:true};
}

export function taskControls(task, selectedMode) {
  const actions = {queued:'start', needs_attention:'resume', failed:'retry', cancelled:'retry', running:'cancel'};
  const queuedForProcessing = task.status === 'queued' && ['pending', 'working'].includes(task.dispatch?.state);
  const mode = actions[task.status] === 'start' && !queuedForProcessing
    ? selectedMode : task.dispatch?.processing_mode || selectedMode;
  const action = queuedForProcessing ? 'cancel' : actions[task.status];
  return {mode, action: task.archived || (action === 'resume' && task.resume_blocked_reason) ? undefined : action, queuedForProcessing};
}
