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
    {type:'list',items},{type:'paragraph',text:limit}
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
      {type:'list',items:['一是静态；','二是动态；']},
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
