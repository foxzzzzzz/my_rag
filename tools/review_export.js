const data=JSON.parse(document.getElementById('data').textContent);
const sections=[...document.querySelectorAll('section')];
const fields=['score','decision','note','reviewer'];
const key=i=>'review-draft:'+JSON.stringify([data.run_id,data.bindings[i].question_id,data.bindings[i].output_sha256]);
sections.forEach((section,i)=>{
 const read=()=>Object.fromEntries(fields.map(name=>[name,section.querySelector('[data-field="'+name+'"]').value]));
 if(data.draft_enabled){
  try {const saved=JSON.parse(localStorage.getItem(key(i))); if(saved) fields.forEach(name=>{if(typeof saved[name]==='string') section.querySelector('[data-field="'+name+'"]').value=saved[name]});} catch(e) {}
  section.addEventListener('input',()=>{try {localStorage.setItem(key(i),JSON.stringify(read()))} catch(e) {}});
  section.addEventListener('change',()=>{try {localStorage.setItem(key(i),JSON.stringify(read()))} catch(e) {}});
 }
});
document.getElementById('export').addEventListener('click',()=>{
 const reviews=[], status=document.getElementById('status');
 document.getElementById('fallback').value='';
 for (const [i,section] of sections.entries()) {
  const get=name=>section.querySelector('[data-field="'+name+'"]').value.trim();
  const score=get('score'), decision=get('decision'), note=section.querySelector('[data-field="note"]').value, reviewer=get('reviewer');
  if(!score && !decision && !note) continue;
  if(score==='' || !Number.isInteger(Number(score)) || Number(score)<0 || Number(score)>100 || !['approve','rework','reject'].includes(decision) || !reviewer) {
   status.textContent='题目 '+data.bindings[i].question_id+'：请填写 0–100 的整数评分、决定和评审人'; section.scrollIntoView(); return;
  }
  reviews.push({...data.bindings[i],score:Number(score),decision,note,reviewer,reviewed_at:new Date().toISOString()});
 }
 if(!reviews.length) {status.textContent='请至少填写一题评分和决定。'; return;}
 const json=JSON.stringify({run_id:data.run_id,reviews},null,2);
 document.getElementById('fallback').value=json;
 try {
  const blob=new Blob([json],{type:'application/json'}), a=document.createElement('a');
  a.href=URL.createObjectURL(blob); a.download=data.feedback_filename; document.body.appendChild(a); a.click(); a.remove();
  const url=a.href; setTimeout(()=>URL.revokeObjectURL(url),data.revoke_delay_ms);
  status.textContent='已生成并发起下载；也可复制下方 JSON。';
 } catch(e) {status.textContent='下载未能发起，请复制下方 JSON。'}
});
if(typeof document.addEventListener==='function') document.addEventListener('click',event=>{
 const link=event.target.closest('a[href^="#q"]');
 if(!link) return;
 const id=link.getAttribute('href').slice(1);
 if(!/^q\d+-source-\d+$/.test(id)) return;
 const card=document.getElementById(id);
 if(card) card.open=true;
});
