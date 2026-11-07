import React from 'react';
import {parseDocument,safeLink} from './document-layout';
function Inline({text}) {
  const parts=String(text).split(/(!?\[[^\]]*\]\([^)]*\))/g);
  return parts.map((part,i)=>{const m=part.match(/^(!?)\[([^\]]*)\]\(([^)]*)\)$/);
    if(!m)return <React.Fragment key={i}>{part}</React.Fragment>; const href=safeLink(m[3]); return m[1]||!href?<React.Fragment key={i}>{m[2]}</React.Fragment>:<a key={i} href={href} target="_blank" rel="noopener noreferrer">{m[2]}</a>});
}
export function DocumentView({value}) {
  return <div className="document-reader">{parseDocument(value).map((block,i)=>{
    if(block.type==='heading') return React.createElement('h'+Math.max(2,block.level),{key:i},<Inline text={block.text}/>);
    if(block.type==='code') return <pre key={i}>
<code>{block.text}</code>
</pre>;
    if(block.type==='list') return <ul key={i}>{block.items.map((x,j)=>
<li key={j}>
<Inline text={x}/>
</li>)}</ul>;
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
  })}</div>;
}
