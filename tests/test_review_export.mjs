import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const script=fs.readFileSync('tools/review_export.js','utf8');
function setup({run='run', hash='sha', count=1, throws=false, storage=new Map()}={}) {
 const bindings=Array.from({length:count},(_,i)=>({question_id:'q'+i,output_sha256:hash+i}));
 const data={run_id:run,bindings,feedback_filename:'reviews.json',draft_enabled:true,revoke_delay_ms:4000};
 const elements={data:{textContent:JSON.stringify(data)},export:{events:{},addEventListener(k,f){this.events[k]=f}},status:{textContent:''},fallback:{value:''}};
 const sections=bindings.map(()=>{const f=Object.fromEntries(['score','decision','note','reviewer'].map(x=>[x,{value:x==='reviewer'?'本人':''}]));return {f,events:{},querySelector(s){return f[s.match(/"(.*?)"/)[1]]},addEventListener(k,v){this.events[k]=v},scrollIntoView(){}}});
 let downloaded,delay,clicked=false;
 const ctx={document:{getElementById:id=>elements[id],querySelectorAll:()=>sections,body:{appendChild(){}},createElement:()=>({click(){clicked=true},remove(){}})},localStorage:{getItem(k){if(throws) throw Error();return storage.get(k)||null},setItem(k,v){if(throws)throw Error();storage.set(k,v)}},Blob:class {constructor(parts){downloaded=parts[0]}},URL:{createObjectURL:()=> 'blob:test',revokeObjectURL(){}},setTimeout:(f,ms)=>{delay=ms},Date,JSON,Number};
 vm.runInNewContext(script,ctx); return {elements,sections,click:()=>elements.export.events.click(),result:()=>({downloaded,delay,clicked}),storage};
}
let a=setup(); a.click(); assert.match(a.elements.status.textContent,/至少/); assert.equal(a.elements.fallback.value,'');
a.sections[0].f.score.value='0'; a.click(); assert.match(a.elements.status.textContent,/题目/); assert.equal(a.elements.fallback.value,'');
a.sections[0].f.decision.value='approve'; a.click(); let result=JSON.parse(a.elements.fallback.value); assert.equal(result.reviews[0].score,0); assert.equal(a.result().downloaded,a.elements.fallback.value); assert.equal(a.result().delay,4000); assert(a.result().clicked);
a=setup({count:9,throws:true}); for(const s of a.sections){s.f.score.value='100';s.f.decision.value='approve';s.f.note.value='  note  ';s.events.input()} a.click(); result=JSON.parse(a.elements.fallback.value);assert.equal(result.reviews.length,9);assert.equal(result.reviews[0].note,'  note  ');
const storage=new Map();a=setup({storage});a.sections[0].f.score.value='12';a.sections[0].events.input();let b=setup({storage,run:'other'});assert.equal(b.sections[0].f.score.value,'');b=setup({storage,hash:'other'});assert.equal(b.sections[0].f.score.value,'');b=setup({storage});assert.equal(b.sections[0].f.score.value,'12');
console.log('review export behavior OK');
