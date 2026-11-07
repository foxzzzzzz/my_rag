import {test} from 'node:test';import {strict as assert} from 'node:assert';import {parseSSE,applyEvent,errorText} from './rag-helpers.js';
test('分片和多个事件',()=>{let a=parseSSE('data: {"type":"progress"}\n\ndata: {"type":');assert.equal(a.events[0].type,'progress');let b=parseSSE(a.rest+'"done"}\n\n');assert.equal(b.events[0].type,'done')});
test('失效清空正文与引用',()=>{let a=applyEvent({answer:'旧正文',citations:[1]},{type:'invalidated'});assert.equal(a.answer,'');assert.deepEqual(a.citations,[]);assert.ok(a.error)});
test('未知错误不泄露原始信息',()=>assert.ok(!errorText('secret-value').includes('secret-value')));

test('封装错误和费用提示安全转换',()=>{assert.match(errorText('操作失败：invalid_config'),/配置无效/);assert.match(errorText('paid_consent_required'),/同意/);assert.ok(!errorText('操作失败：unknownsecret').includes('unknownsecret'))});
