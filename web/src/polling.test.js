import test from 'node:test';
import assert from 'node:assert/strict';
import {latestReads, serialPoll, waitForReads, affectsLibrary, mutationGuard} from './polling.js';

test('newer requests and mutation invalidation suppress older responses',()=>{
  const reads=latestReads(), old=reads.begin('detail:1'), other=reads.begin('detail:2');
  const fresh=reads.begin('detail:1');
  assert.equal(old(),false); assert.equal(fresh(),true); assert.equal(other(),true);
  reads.invalidate('detail:1'); assert.equal(fresh(),false); assert.equal(other(),true);
});
test('poll waits for completion and stops without applying after cleanup',async()=>{
  let resolve, calls=0, active;
  const stop=serialPoll(async isActive=>{calls++;active=isActive;await new Promise(r=>{resolve=r});},5);
  await new Promise(r=>setTimeout(r,25));
  assert.equal(calls,1);stop();assert.equal(active(),false);resolve();
  await new Promise(r=>setTimeout(r,20));assert.equal(calls,1);
});

test('a failed request does not end a refresh while a sibling is still running',async()=>{
  let finish, returned=false;
  const pending=new Promise(resolve=>{finish=resolve;});
  const completion=waitForReads([Promise.reject(Error('offline')),pending]).catch(error=>{
    returned=true;
    assert.equal(error.message,'offline');
  });
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(returned,false);
  finish();
  await completion;
  assert.equal(returned,true);
});


test('source mutation invalidates previous and concurrent reads, including overlapping writes',()=>{
  const guard=mutationGuard(), before=guard.current();
  const first=guard.begin(), during=guard.current(), second=guard.begin();
  assert.equal(before(),false);assert.equal(during(),false);assert.equal(guard.active(),true);
  first();assert.equal(guard.active(),true);second();second();
  assert.equal(guard.active(),false);assert.equal(during(),false);assert.equal(guard.current()(),true);
});
test('only writes affecting library and sources acquire mutation guard',()=>{
  for(const path of ['/sources/s1/classification','/classifications/bulk','/classification-suggestions/x/apply','/obsidian/apply','/tasks/x/retry'])assert.equal(affectsLibrary(path,'POST'),true,path);
  for(const path of ['/rag/stream','/obsidian/preview','/classification-suggestions/x/reject'])assert.equal(affectsLibrary(path,'POST'),false,path);
  assert.equal(affectsLibrary('/sources/s1','GET'),false);
});
