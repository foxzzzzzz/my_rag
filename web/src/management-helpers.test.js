import test from 'node:test';import assert from 'node:assert/strict';
import {filterSources,splitAliases,labelIds} from './management-helpers.js';
test('分类筛选维度AND、同维度OR、隐藏删除',()=>{const rows=[{id:'1',kind:'html',original_name:'Agent笔记',review_status:'pending',classification:{topics:[{id:'a'}],tags:[{id:'t'}]}},{id:'2',kind:'html',original_name:'Agent旧版',deleted:true},{id:'3',kind:'video',original_name:'Agent视频',classification:{topics:[{id:'b'}],tags:[]}}];assert.deepEqual(filterSources(rows,{q:'agent',kind:'html',topics:['b','a'],tags:['t']}).map(x=>x.id),['1']);assert.equal(filterSources(rows,{topics:['unknown']}).length,0);assert.equal(filterSources(rows,{review:'approve'}).length,0)});
test('别名分隔与稳定ID提取',()=>{assert.deepEqual(splitAliases(' RAG，检索\n retrieval, '),['RAG','检索','retrieval']);assert.deepEqual(labelIds([{id:'a',name:'旧名称'}]),['a'])});

test('未分类按主题判断，保留历史标签并排除回收站记录',()=>{
  const tag={id:'t'};
  const rows=[
    {id:'empty',kind:'html',original_name:'笔记'},
    {id:'legacy',kind:'html',original_name:'历史笔记',classification:{tags:[tag]}},
    {id:'deleted',kind:'html',original_name:'删除的笔记',deleted:true},
    {id:'topic',kind:'html',original_name:'已归类笔记',classification:{topics:[{id:'a'}],tags:[tag]}}
  ];
  assert.deepEqual(filterSources(rows,{unclassified:true}).map(source=>source.id),['empty','legacy']);
  assert.deepEqual(filterSources(rows,{unclassified:true,q:'历史',kind:'html',tags:['t']}).map(source=>source.id),['legacy']);
  assert.deepEqual(rows[1].classification.tags,[tag]);
});

test('douyin errors are safe and understandable', async () => {
  const {douyinErrorText} = await import('./management-helpers.js');
  assert.match(douyinErrorText('media_tool_missing'), /视频检测工具/);
  assert.match(douyinErrorText('download_denied'), /禁止下载/);
  assert.match(douyinErrorText('download_permission_unknown'), /无法确认/);
  assert.match(douyinErrorText('douyin_resolver_failed'), /解析失败/);
  assert.equal(douyinErrorText('secret'), '下载失败，请稍后重试');
});
