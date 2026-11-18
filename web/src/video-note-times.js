const clock=String.raw`\d{1,3}:[0-5]\d:[0-5]\d(?:[.,]\d+)?`;
const frame=String.raw`\d+(?:\.\d+)?\s*(?:s|秒)`;
const bracketed=String.raw`(?:\[|【|［)(?:${clock}(?:\s*[-–—~～]\s*${clock})?|${frame})(?:\]|】|］)`;
const frameList=String.raw`(?:抽样画面|抽帧|关键帧)(?:的)?时间点[：:\s]*${frame}(?:[、,，；;\s]+${frame})+`;
const locatorGroup=String.raw`${bracketed}(?:\s*(?:[、,，；;]|与|和|及)\s*${bracketed})*`;
const enclosing=String.raw`[（(]\s*(?:${frameList}|${locatorGroup})\s*[）)]`;
const locator=new RegExp(String.raw`\s*(?:${enclosing}|${frameList}|${locatorGroup})|(?<![\w.])${frame}\s*(?=画面|截图|关键帧)|[（(]\s*${frame}\s*(?:画面|截图|关键帧)?\s*[）)]`,'gu');
const bracketedSeconds=new RegExp(String.raw`(?:\[|【|［)${frame}(?:\]|】|］)`,'u');
const protectedInline=/\x60+|\[[^\]\n]*\]\([^\n)]*\)/g;

function hideLocators(text) {
  const readingText=text.replace(locator,(match,offset,input)=>{
    const after=input.slice(offset+match.length);
    const before=input.slice(0,offset);
    if(bracketedSeconds.test(match)){
      const context=before.split(/[。！？；;\n]/).at(-1);
      if(!/(?:画面|截图|关键帧|抽帧)/.test(context)||/(?:时长|耗时|超时|延迟|间隔|周期|持续|长度|等待)[^，,：:。！？；;\n]*$/.test(context))return match;
    }
    if (/^[（(]\s*\d/.test(match)&&!/(?:画面|截图|关键帧)$/.test(before)&&!/(?:画面|截图|关键帧)/.test(match)) return match;
    if (!/\S/.test(before)) return '';
    if (/^\s*(?:[，。；、：！？）)\],.;:!?]|$)/.test(after)) return '';
    return /^\s/.test(match)&&!/^\s/.test(after)?' ':'';
  });
  // A bare offset is only hidden in this example form when the sentence names the sampled frames.
  return readingText.replace(/((?:抽样画面|抽帧|关键帧)[^。！？；\n]*[（(](?:例如|如))\s*\d+\.\d+s\s*的\s*/gu,'$1');
}

export function hideVideoNoteTimes(text) {
  let result='', cursor=0;
  protectedInline.lastIndex=0;
  for(let match; (match=protectedInline.exec(text)); ){
    let end=protectedInline.lastIndex;
    if(match[0][0]==='\x60'){
      const delimiter=match[0];
      let close=text.indexOf(delimiter,end);
      while(close!==-1&&(text[close-1]==='\x60'||text[close+delimiter.length]==='\x60')){
        close=text.indexOf(delimiter,close+delimiter.length);
      }
      if(close===-1)continue;
      end=close+delimiter.length;
      protectedInline.lastIndex=end;
    }
    result+=hideLocators(text.slice(cursor,match.index))+text.slice(match.index,end);
    cursor=end;
  }
  const updated=result+hideLocators(text.slice(cursor));
  return updated===text?text:updated.trim();
}

export function hideVideoNoteTimeBlocks(blocks) {
  return blocks.flatMap(block=>{
    if(block.type==='list'){
      const items=block.items.flatMap(item=>{
        const text=hideVideoNoteTimes(item.text);
        const children=hideVideoNoteTimeBlocks(item.children);
        return text.trim()||children.length?[{...item,text,children}]:[];
      });
      return items.length?[{...block,items}]:[];
    }
    if(block.type==='quote'){
      const children=hideVideoNoteTimeBlocks(block.blocks);
      return children.length?[{...block,blocks:children}]:[];
    }
    if(block.type==='table') return [{...block,rows:block.rows.map(row=>row.map(hideVideoNoteTimes))}];
    if(block.type==='code') return [block];
    const text=hideVideoNoteTimes(block.text);
    return text.trim()?[{...block,text}]:[];
  });
}
