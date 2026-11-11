import React from 'react';
import {parseDocument,parseInline} from './document-layout';
function renderInline(tokens) {
  return tokens.map((token,index)=>{
    if(token.type==='strong')return <strong key={index}>{renderInline(token.children)}</strong>;
    if(token.type==='link')return <a key={index} href={token.href} target="_blank" rel="noopener noreferrer">{renderInline(token.children)}</a>;
    return <React.Fragment key={index}>{token.text}</React.Fragment>;
  });
}
function Inline({text}) {return renderInline(parseInline(text));}
export function DocumentView({value,structureSummary}) {
  return <div className="document-reader">{parseDocument(value,{structureSummary}).map((block,i)=>{
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
