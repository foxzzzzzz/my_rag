export function sourceSignature(sources, reviewEpoch=0) {
 return JSON.stringify([reviewEpoch, sources.map(s=>[s.id,s.current_version_id,s.eligible,s.content_status,s.deleted,s.classification?.revision]).sort((a,b)=>String(a[0]).localeCompare(String(b[0])))]);
}
export function isCurrentRequest(token, current, connected, signature, currentSignature) {
 return token===current && connected && signature===currentSignature;
}
