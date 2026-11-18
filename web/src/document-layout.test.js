import {test} from 'node:test';
import assert from 'node:assert/strict';
import {parseDocument,parseInline,safeLink,structuredSummaryBlocks} from './document-layout.js';
import {hideVideoNoteTimes} from './video-note-times.js';

test('视频笔记默认隐藏转录定位和抽帧清单，保留正文数字、标点与 Markdown',()=>{
  const cases=[
    ['[00:00:00–00:00:05] **注意力**需要缓存 30 秒。','**注意力**需要缓存 30 秒。'],
    ['以135篇面经为分母（[00:00:08.330–00:00:14.790]）。','以135篇面经为分母。'],
    ['原句（[00:07:09.920–00:07:15.790]、[00:07:49.460]）。','原句。'],
    ['来源：语音转录 + 抽样画面（抽样画面时间点 0.100s、13.513s、27.026s）。','来源：语音转录 + 抽样画面。'],
    ['首屏与12.533s画面表格一致，缓存保留 12.533s。','首屏与画面表格一致，缓存保留 12.533s。'],
    ['画面 [67.566s]：顶部横条','画面：顶部横条'],
    ['画面 [189.184s] 与 [202.697s]：两幅示意图','画面：两幅示意图'],
    ['抽样画面中多处百分比（如 27.026s 的 40%）','抽样画面中多处百分比（如40%）'],
    ['画面（96.184s）三模块，耗时（30s）。','画面三模块，耗时（30s）。'],
    ['使用 `[00:12:09]` 作为示例，会议 09:30 开始。','使用 `[00:12:09]` 作为示例，会议 09:30 开始。'],
    ['[00:12:09](https://example.com) 是链接','[00:12:09](https://example.com) 是链接'],
    ['真实耗时为30秒，采样周期为0.1s。','真实耗时为30秒，采样周期为0.1s。'],
    ['片段长度 [30秒] 很短，超时设置为 [30s]。','片段长度 [30秒] 很短，超时设置为 [30s]。'],
    ['画面中的缓存时长 [30s]，长度 [2.5秒]。','画面中的缓存时长 [30s]，长度 [2.5秒]。'],
    ['画面 [67.566s] 与 [81.079s]','画面'],
  ];
  for(const [input,expected] of cases) assert.equal(hideVideoNoteTimes(input),expected,input);
});
test('结构化摘要按字段渲染并校验旧数据',()=>{
  assert.deepEqual(structuredSummaryBlocks({overview:'概述',key_points:['要点一','要点二'],limitations:'范围说明'}),[
    {type:'paragraph',text:'概述'},
    {type:'list',ordered:false,items:[{text:'要点一',children:[]},{text:'要点二',children:[]}]},
    {type:'paragraph',text:'范围说明'},
  ]);
  assert.deepEqual(structuredSummaryBlocks({overview:'概述',key_points:[],limitations:''}),[{type:'paragraph',text:'概述'}]);
  for(const value of [null,{}, {overview:'',key_points:[],limitations:''},{overview:'概述',key_points:[''],limitations:''}])
    assert.equal(structuredSummaryBlocks(value),null);
});
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

test('Pachat 摘要保留原有圈号和文字，按五项结论及作者说明排版',()=>{
  const intro='作者介绍并演示网页工具 Pachat：把多个 AI agent（含本人电脑上的 Cloud Code/Codex、Personal agent 如 Muse/WorkBuddy）拉进同一群聊，集中派活、协同完成任务。核心结论包括：';
  const items=[
    '①可在群内同时调度不同 agent 完成生图、做 PPT、查 GitHub 榜单并交叉核验；',
    '②作者设想把 agent 当"员工"互相借用（需对方允许），并认为存在付费/共享账号等商业想象空间；',
    '③作者更推荐 personal agent，因为不需要电脑保持开机，手机即可用；',
    '④作者批评当前"邀请本地 agent 仍需复制一段码"的交互不完善、反人类；',
    '⑤作者质疑官方指南里团餐报价、鲜花订阅等小场景是否需要多个 agent，认为会费 token 且混乱。',
  ];
  const tail='作者对借用 agent、共享账号等设想多为暗示性表述，并多次称"言尽于此"，自认机制"超模"、打破硬件壁垒；同时承认工具"还不是很完备"。';
  const text=intro+' '+items.join(' ')+tail;
  assert.deepEqual(parseDocument(text,{structureSummary:true}),[
    {type:'paragraph',text:intro},
    {type:'list',ordered:false,marker:'circled',items:items.map(text=>({text,children:[]}))},
    {type:'paragraph',text:tail},
  ]);
  assert.deepEqual(parseDocument(text),[{type:'paragraph',text}]);
});

test('圈号支持段首和逐行排版，跳号、混用编号和引用内圈号保持原样',()=>{
  for(const text of ['①第一项\n②第二项；③第三项','要点：\n①第一项\n②第二项\n③第三项']){
    const list=parseDocument(text,{structureSummary:true}).at(-1);
    assert.equal(list.marker,'circled');
    assert.deepEqual(list.items.map(item=>item.text),['①第一项','②第二项'+(text.includes('；')?'；':''),'③第三项']);
  }
  for(const text of [
    '单项：①仅一条。','要点：①第一项；③跳号。','要点：①第一项；二是第二项。',
    '说明见①；②处有示例。','引述：“要点：①甲；②乙。”',
    '括注（要点：①甲；②乙）。','引用 `要点：①甲；②乙`。',
    '要点：①；②第二项。','要点：①；②第二项；③第三项。',
  ]){
    assert.deepEqual(parseDocument(text,{structureSummary:true}),parseDocument(text));
  }
  const protectedMarks='要点：①示例（符号：②）；②引用“提示：③”；③读取 `示例：④`。';
  const [intro,list]=parseDocument(protectedMarks,{structureSummary:true});
  assert.equal(intro.text,'要点：');
  assert.equal(list.items.length,3);
  assert.equal(list.items.map(item=>item.text).join(''),protectedMarks.slice(intro.text.length));
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
