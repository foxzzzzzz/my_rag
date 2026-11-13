export function safeLink(url) {
  try { const u = new URL(url); return ['http:', 'https:'].includes(u.protocol) ? u.href : null; } catch { return null; }
}

function escapedAt(text, index) {
  let start=index;
  while(text[start-1]==='\\')start--;
  return (index-start)%2!==0;
}

function codeSpanEnds(text) {
  const ends=new Map(), nextRun=new Map();
  for(const run of [...text.matchAll(/`+/g)].reverse()){
    const length=run[0].length;
    if(nextRun.has(length))ends.set(run.index,nextRun.get(length));
    nextRun.set(length,run.index+length);
  }
  return ends;
}

export function parseInline(text) {
  text=String(text);
  const tokens=[];
  const codeEnds=codeSpanEnds(text);

  let bold=null;
  let cursor=0;
  const pattern=/`+|!?\[[^\]]*\]\([^)]*\)|(?<!\*)\*\*(?!\*)/g;
  function appendText(end){
    if(end>cursor)(bold??tokens).push({type:'text',text:text.slice(cursor,end)});
  }
  for(let match; (match=pattern.exec(text)); ){
    const [token]=match;
    const start=match.index;
    const codeEnd=token[0]==='`'&&!escapedAt(text,start)?codeEnds.get(start):undefined;
    if(codeEnd!==undefined){
      appendText(start);
      cursor=start;
      appendText(codeEnd);
      cursor=pattern.lastIndex=codeEnd;
      continue;
    }
    if(token==='**'&&!escapedAt(text,start)){
      if(bold&&/\S/.test(text[start-1]||'')){
        appendText(start);
        tokens.push({type:'strong',children:bold});
        bold=null;
      }else if(!bold&&/\S/.test(text[pattern.lastIndex]||'')){
        appendText(start);
        bold=[];
      }else{
        continue;
      }
      cursor=pattern.lastIndex;
      continue;
    }
    const link=token.match(/^(!?)\[([^\]]*)\]\(([^)]*)\)$/);
    if(link){
      appendText(start);
      const href=link[1]?null:safeLink(link[3]);
      (bold??tokens).push(href
        ?{type:'link',children:parseInline(link[2]),href}
        :{type:'text',text:link[2]});
      cursor=pattern.lastIndex;
    }
  }
  appendText(text.length);
  return bold?tokens.concat({type:'text',text:'**'},bold):tokens;
}

const brackets = {'(':')','（':'）','[':']','［':'］','【':'】','{':'}','｛':'｝','《':'》','〈':'〉','〔':'〕'};
const quotes = {'“':'”','‘':'’','「':'」','『':'』','"':'"',"'":"'"};
const ordinals = '一二三四五六七八九十';
const caveat = /^(?:\*\*)?(?:作者(?:特别|还|同时)?强调|(?:需要|值得)注意|(?:取证边界|局限(?:性)?)(?:\*\*)?[：:]|材料(?:存在|仍有)(?:多处)?(?:字幕与画面不一致|文字遮挡|拼写异常|不确定性|局限|限制|缺失))/;

function summaryBlocks(paragraph) {
  const text=paragraph.text;
  const markers=[];
  const limits=[];
  const closers=[];
  const quoteClosers=[];
  let code='';
  if(text.trimStart().startsWith('一是')){
    markers.push({offset:text.length-text.trimStart().length,ordinal:0,separator:''});
  }

  for(let index=0;index<text.length;index++){
    const char=text[index];
    if(char==='\\'){index++;continue;}
    if(char==='`'&&!quoteClosers.length){
      const run=text.slice(index).match(/^`+/)[0];
      if(!code||code===run)code=code?'':run;
      index+=run.length-1;
      continue;
    }
    if(code)continue;
    const contraction=/['’]/.test(char)&&/\w/.test(text[index-1]||'')&&/\w/.test(text[index+1]||'');
    const opensQuote=Object.hasOwn(quotes,char)&&!(char==="'"&&/\w/.test(text[index-1]||''));
    if(quoteClosers.length){
      if(contraction)continue;
      if(char===quoteClosers.at(-1))quoteClosers.pop();
      else if(opensQuote)quoteClosers.push(quotes[char]);
      continue;
    }
    if(opensQuote){
      quoteClosers.push(quotes[char]);
      continue;
    }
    if(Object.hasOwn(brackets,char)){
      closers.push(brackets[char]);
      continue;
    }
    if(char===closers.at(-1)){closers.pop();continue;}
    if(closers.length||!/[：:；;。！？]/.test(char))continue;

    const rest=text.slice(index+1);
    const next=rest.trimStart();
    const offset=index+1+rest.length-next.length;
    if(/[；;。！？]/.test(char)&&caveat.test(next))limits.push(offset);
    if(next[1]==='是'&&ordinals.includes(next[0]||' ')&&next.length>2){
      markers.push({offset,ordinal:ordinals.indexOf(next[0]),separator:char});
    }
  }

  const first=markers.findIndex(marker=>marker.ordinal===0&&(!marker.separator||/[：:]/.test(marker.separator)));
  if(first<0||!markers[first+1]||quoteClosers.length||code||closers.length)return [paragraph];
  const listEnd=limits.find(offset=>offset>markers[first+1].offset)??text.length;
  const entries=markers.slice(first).filter(marker=>marker.offset<listEnd);
  if(entries.length<2||entries.some((marker,index)=>marker.ordinal!==index||index>0&&/[：:]/.test(marker.separator)))return [paragraph];
  const intro=text.slice(0,entries[0].offset).trimEnd();
  const items=entries.map((marker,index)=>text.slice(marker.offset,entries[index+1]?.offset??listEnd).trimEnd());
  const blocks=[];
  if(intro)blocks.push({type:'paragraph',text:intro});
  blocks.push({type:'list',ordered:false,items:items.map(text=>({text,children:[]}))});
  if(listEnd<text.length)blocks.push({type:'paragraph',text:text.slice(listEnd)});
  return blocks;
}

const listMarker = line => line.match(/^( *)([-*+]|(\d{1,9})[.)])\s+(.+)$/);
// Limit nested blocks to prevent hostile input exhausting the JavaScript stack.
const MAX_BLOCK_DEPTH=32;
function cells(line) {
  const text=line.trim(), parts=[];
  const closingRun=codeSpanEnds(text);
  let start=0;
  for(let i=0;i<text.length;i++){
    if(text[i]==='`'&&!escapedAt(text,i)){
      const end=closingRun.get(i);
      if(end!==undefined){i=end-1;continue;}
    }
    if(text[i]==='|'&&!escapedAt(text,i)){parts.push(text.slice(start,i));start=i+1;}
  }
  parts.push(text.slice(start));
  const framed=parts.length>1&&(parts[0]===''||parts.at(-1)==='');
  const delimited=parts.length>1;
  if(parts.length>1&&parts[0]==='')parts.shift();
  if(parts.length>1&&parts.at(-1)==='')parts.pop();
  return {framed,delimited,values:parts.map(part=>part.trim().replace(/(\\+)\|/g,(match,slashes)=>slashes.length%2?slashes.slice(1)+'|':match))};
}
function isTable(lines,i) {
  if(i+1>=lines.length||!lines[i].includes('|'))return false;
  const header=cells(lines[i]), separator=cells(lines[i+1]);
  return header.delimited&&header.values.length===separator.values.length&&separator.values.every(cell=>/^:?-{3,}:?$/.test(cell));
}
function readList(lines, start, indent, depth=0) {
  const first=listMarker(lines[start]);
  const ordered=!!first[3], items=[]; let i=start;
  while(i<lines.length){
    const marker=listMarker(lines[i]);
    if(!marker||marker[1].length!==indent||!!marker[3]!==ordered)break;
    const item={text:marker[4],children:[]}; i++;
    while(i<lines.length){
      let next=i;while(next<lines.length&&!lines[next].trim())next++;
      const child=listMarker(lines[next]||'');
      if(!child)break;
      if(child[1].length===indent&&!!child[3]===ordered){i=next;break;}
      if(child[1].length<=indent||depth>=MAX_BLOCK_DEPTH)break;
      const result=readList(lines,next,child[1].length,depth+1);item.children.push(result.block);i=result.next;
    }
    items.push(item);
  }
  return {block:{type:'list',ordered,start:ordered?Number(first[3]):undefined,items},next:i};
}
export function parseDocument(value, {structureSummary=false, depth=0}={}) {
  const lines = String(value || '').replace(/\r\n?/g, '\n').split('\n');
  const blocks = []; let i = 0;
  const beginsBlock = index => /^(#{1,6}\s|```)/.test(lines[index])||/^\s*>/.test(lines[index])&&depth<MAX_BLOCK_DEPTH||!!listMarker(lines[index])||isTable(lines,index);
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    if (/^```/.test(line)) { const code=[]; i++; while(i<lines.length && !/^```/.test(lines[i])) code.push(lines[i++]); if(i<lines.length)i++; blocks.push({type:'code',text:code.join('\n')}); continue; }
    const heading = line.match(/^(#{1,6})\s+(.+)$/); if(heading) { blocks.push({type:'heading',level:heading[1].length,text:heading[2]}); i++; continue; }
    if(isTable(lines,i)) {
      const header=cells(line), rows=[header.values];
      i+=2;
      while(i<lines.length&&lines[i].trim()&&!beginsBlock(i)){
        const row=cells(lines[i]);
        if(!row.delimited||header.framed&&!row.framed||row.values.length!==header.values.length)break;
        rows.push(row.values);
        i++;
      }
      blocks.push({type:'table',rows});
      continue;
    }
    if(/^\s*>/.test(line)&&depth<MAX_BLOCK_DEPTH) {const quoted=[];while(i<lines.length&&/^\s*>/.test(lines[i]))quoted.push(lines[i++].replace(/^\s*> ?/,''));blocks.push({type:'quote',blocks:parseDocument(quoted.join('\n'),{depth:depth+1})});continue;}
    const marker=listMarker(line);if(marker){const result=readList(lines,i,marker[1].length);blocks.push(result.block);i=result.next;continue;}
    const paragraph=[line]; i++; while(i<lines.length && lines[i].trim() && !beginsBlock(i)) paragraph.push(lines[i++]); blocks.push({type:'paragraph',text:paragraph.join('\n')});
  }
  return structureSummary?blocks.flatMap(block=>block.type==='paragraph'?summaryBlocks(block):[block]):blocks;
}
