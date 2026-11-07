import {test} from 'node:test';
import {strict as assert} from 'node:assert';
import {sourceSignature,isCurrentRequest} from './rag-state.js';
test('资料顺序不影响签名，版本资格分类或删除变化使签名改变',()=>{
 const a={id:'a',current_version_id:'v1',eligible:true,classification:{revision:1}},b={id:'b'};
 const sig=sourceSignature([a,b]); assert.equal(sig,sourceSignature([b,a]));
 for(const patch of [{current_version_id:'v2'},{eligible:false},{deleted:true},{content_status:'rework'},{classification:{revision:2}}]) assert.notEqual(sig,sourceSignature([{...a,...patch},b]));
});
test('断线、资料变化或新请求都拒绝旧响应',()=>{
 assert.equal(isCurrentRequest(1,1,true,'a','a'),true);
 assert.equal(isCurrentRequest(1,2,true,'a','a'),false);
 assert.equal(isCurrentRequest(1,1,false,'a','a'),false);
 assert.equal(isCurrentRequest(1,1,true,'a','b'),false);
});

test('同版本审核提交周期变化使旧结果失效',()=>{
 const sources=[{id:'a',current_version_id:'v1',eligible:true}];
 assert.notEqual(sourceSignature(sources,0),sourceSignature(sources,1));
 assert.notEqual(sourceSignature(sources,1),sourceSignature(sources,2));
});
