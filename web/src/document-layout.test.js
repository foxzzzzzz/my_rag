import {test} from 'node:test';
import assert from 'node:assert/strict';
import {parseDocument,parseInline,safeLink} from './document-layout.js';
test('dangerous links are rejected',()=>{assert.equal(safeLink('javascript:alert(1)'),null);assert.equal(safeLink('data:text/html,x'),null);assert.equal(safeLink('https://example.com/a'),'https://example.com/a')});
test('HTML remains plain text and common blocks preserve structure',()=>{const b=parseDocument('# Title\n\n<script>alert(1)</script>\n\n- one\n- two\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\n```\n<x>\n```');assert.deepEqual(b.map(x=>x.type),['heading','paragraph','list','table','code']);assert.equal(b[1].text,'<script>alert(1)</script>');assert.equal(b[4].text,'<x>')});

test('旧摘要按明确枚举拆分并保留结论和取证边界的原文',()=>{
  const intro='作者的核心结论是分开三类判断：';
  const items=[
    '一是静态事实，样本为 decoded[28]（“引号内；二是样本，不能作为分隔。”）；',
    '二是实现差异，源码示例为 `x；三是代码`；',
    '三是能力判断，效果仍需运行评测。'
  ];
  const limit='作者强调 64 是数组项数（含空行与标签），并非产品相似率。';
  const summary=['开头概述。', [intro,...items,limit].join(' ')].join('\n\n');
  assert.deepEqual(parseDocument(summary,{structureSummary:true}),[
    {type:'paragraph',text:'开头概述。'},{type:'paragraph',text:intro},
    {type:'list',ordered:false,items:items.map(text=>({text,children:[]}))},{type:'paragraph',text:limit}
  ]);
  assert.equal(parseDocument(summary)[1].text,[intro,...items,limit].join(' '));
});

test('普通段落、引述里的枚举和已有 Markdown 列表保留结构',()=>{
  for(const text of [
    '这一项是一是的例子。作者强调取证范围。',
    '引述如下：“评估：一是静态；二是动态。”',
    "引用 'don't: 一是静态；二是动态'",
    '引用〈标题：一是甲；二是乙〉。',
    '引用［例子：一是甲；二是乙］。',
    '引用“外层‘内层“子引用”：一是甲；二是乙。’外层结束”。',
    '结论：一是静态；三是动态。',
    '结论：一是静态（引述未结束；二是动态。'
  ]){
    assert.deepEqual(parseDocument(text,{structureSummary:true}),parseDocument(text));
  }
  const markdown='一段概述。\n\n- 静态事实\n- 实现差异\n\n局限：仅验证所选样本。';
  assert.deepEqual(parseDocument(markdown,{structureSummary:true}),parseDocument(markdown));
});

test('段首枚举和带粗体或分号的取证边界仍可分开',()=>{
  for(const limit of ['**作者强调**仅测试样本。','材料存在多处字幕与画面不一致。','**局限**：仅验证样本。','作者强调两类限制：一是样本量；二是测试范围。']){
    const text='一是静态；二是动态；'+limit;
    assert.deepEqual(parseDocument(text,{structureSummary:true}),[
      {type:'list',ordered:false,items:['一是静态；','二是动态；'].map(text=>({text,children:[]}))},
      {type:'paragraph',text:limit}
    ]);
  }
});

test('行内粗体正确显示，代码、普通星号及不安全链接仍按原规则处理',()=>{
  const text='作者强调这是**静态文本比对**；示例 `**literal**`；** 空格 **；[链接](https://example.com)';
  const tokens=parseInline(text);
  assert.deepEqual(tokens.filter(token=>token.type==='strong'),[{type:'strong',children:[{type:'text',text:'静态文本比对'}]}]);
  assert.ok(tokens.some(token=>token.text==='`**literal**`'&&token.type==='text'));
  assert.ok(tokens.filter(token=>token.type==='text').map(token=>token.text).join('').includes('** 空格 **'));
  assert.ok(tokens.some(token=>token.type==='link'&&token.href==='https://example.com/'));
  assert.equal(parseInline('[不安全](data:text/html,x)').some(token=>token.type==='link'),false);
  assert.equal(parseInline('** 空格 **').some(token=>token.type==='strong'),false);
});

test('保留双反引号内的字面文本及加粗和链接的组合',()=>{
  const code='``a`**literal**`b``';
  assert.deepEqual(parseInline(code),[{type:'text',text:code}]);
  const evenEscape='\\\\`**literal**`';
  const escapedTokens=parseInline(evenEscape);
  assert.ok(escapedTokens.every(token=>token.type==='text'));
  assert.equal(escapedTokens.map(token=>token.text).join(''),evenEscape);
  const longRun='`'.repeat(16000);
  assert.deepEqual(parseInline(longRun),[{type:'text',text:longRun}]);
  const [strong]=parseInline('**见[文档](https://example.com)**');
  assert.equal(strong.type,'strong');
  assert.equal(strong.children[1].href,'https://example.com/');
  const [link]=parseInline('[**文档**](https://example.com)');
  assert.equal(link.href,'https://example.com/');
  assert.deepEqual(link.children,[{type:'strong',children:[{type:'text',text:'文档'}]}]);
});

test('有序列表保留起始编号、两空格缩进及父子层级',()=>{
  const [list]=parseDocument('3. 父项\n  1. 子项一\n  2. 子项二\n4. 第二项');
  assert.equal(list.ordered,true);assert.equal(list.start,3);assert.equal(list.items.length,2);
  assert.equal(list.items[0].children[0].items.length,2);assert.equal(list.items[0].children[0].start,1);assert.equal(list.items[1].text,'第二项');
});
test('引用块边界与紧跟正文的表格',()=>{
  const blocks=parseDocument('正文\n| 列一 | 列二 |\n| --- | :---: |\n| a | b |\n\n> 引用一\n> 引用二\n普通文本');
  assert.deepEqual(blocks.map(x=>x.type),['paragraph','table','quote','paragraph']);assert.deepEqual(blocks[1].rows,[['列一','列二'],['a','b']]);assert.equal(blocks[2].blocks[0].text,'引用一\n引用二');
});
test('引用内的列表保留层级，围栏内的列表和引用保持原样',()=>{
  const [quote,code]=parseDocument('> 引用\n>\n> 1. 第一项\n>   - 子项\n> 2. 第二项\n\n```\n1. 示例\n> 示例\n```');
  assert.equal(quote.type,'quote');
  assert.equal(quote.blocks[1].items[0].children[0].items[0].text,'子项');
  assert.deepEqual(code,{type:'code',text:'1. 示例\n> 示例'});
});
test('列表与引用中的 HTML 仍是纯文本',()=>{
  const blocks=parseDocument('1. <script>alert(1)</script>\n\n> <img src=x onerror=evil>');
  assert.equal(blocks[0].items[0].text,'<script>alert(1)</script>');assert.equal(blocks[1].blocks[0].text,'<img src=x onerror=evil>');
});

test('表格保留转义和代码中的竖线，遇到标题或下一张表停止',()=>{
  const blocks=parseDocument('A | B\n--- | ---\n`x|y` | a\\|b\n# 标题 | 内容\nC | D\n--- | ---\n1 | 2');
  assert.deepEqual(blocks.map(b=>b.type),['table','heading','table']);
  assert.deepEqual(blocks[0].rows[1],['`x|y`','a|b']);
  const even=parseDocument('A | B\n--- | ---\nx\\\\|y')[0];assert.deepEqual(even.rows[1],['x\\\\','y']);
});
test('带外侧竖线的表格保留单列表和后面的竖线正文',()=>{
  const blocks=parseDocument('| 表头 |\n| --- |\n| 内容 |\n正文 x | y\n| A | B |\n| --- | --- |\n| a | b |\n| 列数不符 |');
  assert.deepEqual(blocks.map(block=>block.type),['table','paragraph','table','paragraph']);
  assert.deepEqual(blocks[0].rows,[['表头'],['内容']]);
  assert.deepEqual(blocks[2].rows,[['A','B'],['a','b']]);
  assert.equal(blocks[1].text,'正文 x | y');
  assert.equal(blocks[3].text,'| 列数不符 |');
});
test('表格内未闭合的反引号保留为普通文本',()=>{
  const [table]=parseDocument('| A | B |\n| --- | --- |\n| 写法 ` | 说明 |');
  assert.deepEqual(table.rows[1],['写法 `','说明']);
});
test('空行后仍可连接同级和缩进的列表项',()=>{
 const [list]=parseDocument('1. 父\n\n  1. 子\n\n2. 后');assert.equal(list.items.length,2);assert.equal(list.items[0].children[0].items[0].text,'子');
});
test('过深引用和列表不会耗尽调用栈',()=>{
 assert.doesNotThrow(()=>parseDocument('>'.repeat(4000)+' text'));
 assert.doesNotThrow(()=>parseDocument(Array.from({length:100},(_,i)=>' '.repeat(i)+'- x').join('\n')));
});
