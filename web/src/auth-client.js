export async function guardedJson(response, epoch, current, onLoginRequired) {
  const data = await response.json().catch(error => { if (response.ok) throw error; return {}; });
  if (epoch !== current()) throw Error('LOGIN_REQUIRED');
  if (response.status === 401 && data.error === 'login_required') { onLoginRequired(); throw Error('LOGIN_REQUIRED'); }
  return data;
}
export async function logoutLocal(token, clear, fetcher=fetch) {
  clear();
  const response = await fetcher('/api/auth/logout',{method:'POST',credentials:'same-origin',headers:{'X-CSRF-Token':token}});
  if (!response.ok) throw Error('logout_unconfirmed');
}
export function acquireWriter(ref) {if(ref.current)return null; const owner={}; ref.current=owner; return owner;}
export function releaseWriter(ref,owner) {if(ref.current!==owner)return false; ref.current=null; return true;}
export function epochCurrent(epoch,ref) {return epoch===ref.current;}
