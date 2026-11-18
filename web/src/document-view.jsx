import React, {useId, useMemo, useState} from 'react';
import {parseDocument,parseInline,structuredSummaryBlocks} from './document-layout';
import {hideVideoNoteTimeBlocks} from './video-note-times';
function renderInline(tokens) {
  return tokens.map((token,index)=>{
    if(token.type==='strong')return <strong key={index}>{renderInline(token.children)}</strong>;
    if(token.type==='link')return <a key={index} href={token.href} target="_blank" rel="noopener noreferrer">{renderInline(token.children)}</a>;
    return <React.Fragment key={index}>{token.text}</React.Fragment>;
  });
}
function Inline({text}) {return renderInline(parseInline(text));}
function List({block}) {
  const Tag=block.ordered?'ol':'ul';
  const circled=block.marker==='circled';
  return <Tag start={block.ordered?block.start:undefined} className={circled?'circled-list':undefined}
    role={circled?'list':undefined}>{block.items.map((item,i)=>
    <li key={i}><Inline text={item.text}/>{item.children.map((child,j)=><List key={j} block={child}/>)}</li>)}</Tag>;
}
function Blocks({blocks}) {
  return blocks.map((block,i)=>{
    if(block.type==='heading') return React.createElement('h'+Math.max(2,block.level),{key:i},<Inline text={block.text}/>);
    if(block.type==='code') return <pre key={i}>
<code>{block.text}</code>
</pre>;
    if(block.type==='list') return <List key={i} block={block}/>;
    if(block.type==='quote') return <blockquote key={i}><Blocks blocks={block.blocks}/></blockquote>;
    if(block.type==='table') return <div className="table-scroll" key={i}>
<table>
<thead>
<tr>{block.rows[0].map((x,j)=>
<th key={j}>
<Inline text={x}/>
</th>)}</tr>
</thead>
<tbody>{block.rows.slice(1).map((row,j)=>
<tr key={j}>{row.map((x,k)=>
<td key={k}>
<Inline text={x}/>
</td>)}</tr>)}</tbody>
</table>
</div>;
    return <p key={i}>
<Inline text={block.text}/>
</p>;
  });
}
export function DocumentView({value,structureSummary,summaryStructure}) {
  const blocks=structureSummary && structuredSummaryBlocks(summaryStructure);
  return <div className="document-reader"><Blocks blocks={blocks||parseDocument(value,{structureSummary})}/></div>;
}

export function VideoNoteView({value}) {
  const [showTimes,setShowTimes]=useState(false);
  const contentId=useId();
  const blocks=useMemo(()=>parseDocument(value),[value]);
  const readingBlocks=useMemo(()=>hideVideoNoteTimeBlocks(blocks),[blocks]);
  const hasTimes=JSON.stringify(blocks)!==JSON.stringify(readingBlocks);
  const visible=showTimes?blocks:readingBlocks;
  return <div className="document-reader">
    {hasTimes&&<button type="button" className="note-times-toggle" aria-controls={contentId} aria-expanded={showTimes}
      onClick={()=>setShowTimes(value=>!value)}>{showTimes?'收起时间定位':'显示时间定位'}</button>}
    <div id={contentId}>
      {visible.length?<Blocks blocks={visible}/>:<p>时间定位已收起。</p>}
    </div>
  </div>;
}
