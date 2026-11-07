import test from 'node:test';
import assert from 'node:assert/strict';
import {guardedJson, logoutLocal} from './auth-client.js';

test('delayed response body cannot restore state after logout', async()=>{
 let epoch=0, state='private', resolve;
 const body=new Promise(r=>resolve=r);
 const request=guardedJson({ok:true,status:200,json:()=>body},epoch,()=>epoch,()=>{}).then(data=>{state=data;});
 await logoutLocal('csrf',()=>{epoch++;state=null},async()=>({ok:true}));
 resolve('old session'); await assert.rejects(request,/LOGIN_REQUIRED/); assert.equal(state,null);
});
test('logout clears before an unknown network outcome',async()=>{
 let state='private';
 await assert.rejects(logoutLocal('csrf',()=>{state=null},async()=>{assert.equal(state,null);throw Error('offline')}));
 assert.equal(state,null);
 await assert.rejects(logoutLocal('csrf',()=>{state=null},async()=>({ok:false,json:()=>{throw Error('bad json')}})));
 assert.equal(state,null);
});
test('stream authentication failure invokes shared handler',async()=>{
 let called=0;
 await assert.rejects(guardedJson({ok:false,status:401,json:async()=>({error:'login_required'})},0,()=>0,()=>called++),/LOGIN_REQUIRED/);
 assert.equal(called,1);
});

test('old writer cannot release a new session writer',async()=>{
 const {acquireWriter,releaseWriter,epochCurrent}=await import('./auth-client.js');
 const ref={current:null}, epoch={current:0}; let resolve;
 const old=acquireWriter(ref), pending=new Promise(r=>resolve=r);
 const completion=pending.then(()=>releaseWriter(ref,old));
 epoch.current++; ref.current=null;
 const fresh=acquireWriter(ref); assert.ok(fresh); assert.equal(epochCurrent(0,epoch),false);
 resolve(); assert.equal(await completion,false); assert.equal(acquireWriter(ref),null);
 assert.equal(releaseWriter(ref,fresh),true); assert.ok(acquireWriter(ref));
});
