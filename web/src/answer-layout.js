import rules from '../../config/answer-layout.json' with {type:'json'};
export function splitParagraphs(answer) {
  const s=answer||'', out=[]; let start=0, visible=0, quotes=[], code='', i=0;
  function refs(end){while(true){const m=s.slice(end).match(/^\s*\[[a-fA-F0-9]{64}\]/);if(!m)break;end+=m[0].length}return end}
  while(i<s.length) {
    const citation=s.slice(i).match(/^\[[a-fA-F0-9]{64}\]/);
    if(citation){i+=citation[0].length;continue}
    const c=s[i];
    if(!quotes.length&&(c==='`'||c==='~')){const run=s.slice(i).match(c==='`'?/^`+/:/^~+/)[0];if(c==='`'||run.length>=3){if(!code)code=run;else if(code===run)code='';i+=run.length;visible+=run.length;continue}}
    if(!code && !((c==="'"||c==='’')&&/[A-Za-z0-9]/.test(s[i-1]||'')&&/[A-Za-z0-9]/.test(s[i+1]||''))){const top=quotes.at(-1);if(c==='“'||c==='‘')quotes.push(c);else if((c==='”'&&top==='“')||(c==='’'&&top==='‘'))quotes.pop();else if((c==='"'||c==="'")&&s[i-1]!=='\\'){if(top===c)quotes.pop();else if(c==='"'||!(/[A-Za-z0-9]/.test(s[i-1]||'')&&/[A-Za-z0-9]/.test(s[i+1]||'')))quotes.push(c)}}
    const cp=s.codePointAt(i);const width=cp>0xffff?2:1;i+=width;visible++;
    if(code||quotes.length)continue;
    if(c==='\n'&&/^\r?\n/.test(s.slice(i))){const m=s.slice(i).match(/^\r?\n/);i+=m[0].length;i=refs(i);if(i<s.length){out.push(s.slice(start,i));start=i;visible=0}continue}
    if(!rules.sentence_endings.includes(c)&&!rules.semicolon_endings.includes(c))continue;
    let end=i;while(end<s.length&&rules.sentence_endings.includes(s[end]))end++;end=refs(end);
    const next=s.slice(end).trimStart();
    const boundary=rules.sentence_endings.includes(c)?visible>=rules.min_paragraph_chars||(visible>=rules.transition_min_chars&&rules.transition_starts.some(x=>next.startsWith(x))):visible>=rules.semicolon_break_chars;
    if(boundary&&next){out.push(s.slice(start,end));start=end;visible=0;i=end}
  }
  if(start<s.length||!out.length)out.push(s.slice(start));return out;
}

