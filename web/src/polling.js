export function latestReads() {
  const versions = new Map();
  return {
    invalidate(key) { versions.set(key, (versions.get(key) || 0) + 1); },
    begin(key) {
      const version = (versions.get(key) || 0) + 1;
      versions.set(key, version);
      return () => versions.get(key) === version;
    }
  };
}

export async function waitForReads(requests) {
  const settled = await Promise.allSettled(requests);
  return settled.map(result => {
    if (result.status === 'rejected') throw result.reason;
    return result.value;
  });
}

export function serialPoll(task, interval, immediate = true) {
  let active = true, timer;
  const run = async () => {
    try { await task(() => active); }
    finally { if (active) timer = setTimeout(run, interval); }
  };
  if (immediate) run(); else timer = setTimeout(run, interval);
  return () => { active = false; clearTimeout(timer); };
}

// Only writes that can change the library or source metadata pause these reads.
export function affectsLibrary(path, method='GET') {
  if (!['POST','PUT','PATCH','DELETE'].includes(method.toUpperCase())) return false;
  const pathname=path.split('?')[0];
  return /^\/(sources|classifications|tasks|trash|imports)(?:\/|$)/.test(pathname)
    || /^\/classification-suggestions\/[^/]+\/apply$/.test(pathname)
    || pathname==='/obsidian/apply';
}

export function mutationGuard() {
  let count=0, generation=0;
  return {
    begin() { count++; generation++; let ended=false; return ()=>{if(!ended){ended=true;count--;}}; },
    active() {return count>0;},
    current() {const started=generation, busy=count>0;return ()=>!busy&&started===generation&&!count;}
  };
}
