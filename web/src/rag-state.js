export function sourceSignature(sources, reviewEpoch=0) {
 return JSON.stringify([reviewEpoch, sources.map(s=>[s.id,s.current_version_id,s.eligible,s.content_status,s.deleted,s.classification?.revision,s.review_revision]).sort((a,b)=>String(a[0]).localeCompare(String(b[0])))]);
}
export function isCurrentRequest(token, current, connected, signature, currentSignature) {
 return token===current && connected && signature===currentSignature;
}

export function hasOlderSourceReviews(previous, incoming) {
 const byId=new Map(previous.map(source=>[source.id,source]));
 return incoming.some(source=>{
  const prior=byId.get(source.id);
  return prior?.current_version_id===source.current_version_id
   && (prior?.review_revision??0)>(source.review_revision??0);
 });
}

export function availableSources(sources) {
 return sources.filter(source=>source.eligible && !source.deleted);
}

export function unavailableSourceIds(selected, available) {
 const ids=new Set(available.map(source=>source.id));
 return selected.filter(id=>!ids.has(id));
}
