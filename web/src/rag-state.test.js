import {test} from 'node:test';
import {strict as assert} from 'node:assert';
import {sourceSignature,isCurrentRequest,hasOlderSourceReviews,availableSources,unavailableSourceIds} from './rag-state.js';
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

test('另一客户端对同版本重新批准时拒绝旧回答与引用响应',()=>{
 const source={id:'a',current_version_id:'v1',eligible:true,review_revision:1};
 const previous=sourceSignature([source]);
 assert.equal(sourceSignature([{...source}]),previous);
 const updated=sourceSignature([{...source,review_revision:2}]);
 assert.notEqual(updated,previous);
 assert.equal(isCurrentRequest(1,1,true,previous,updated),false);
});

test('交叉轮询识别同版本审核回退，允许正常刷新和新版本待审核',()=>{
 const source={id:'a',current_version_id:'v1',review_revision:2};
 const previous=[source,{id:'b',current_version_id:'v2',review_revision:null}];
 assert.equal(hasOlderSourceReviews(previous,[previous[1],{...source,review_revision:1}]),true);
 assert.equal(hasOlderSourceReviews(previous,[{...source,review_revision:null}]),true);
 assert.equal(hasOlderSourceReviews(previous,[source]),false);
 assert.equal(hasOlderSourceReviews(previous,[{...source,review_revision:3}]),false);
 assert.equal(hasOlderSourceReviews(previous,[{...source,current_version_id:'v3',review_revision:null}]),false);
});

test('撤审、删除及缺失的已选来源仍可识别为不可用',()=>{
 const sources=[{id:'eligible',eligible:true},{id:'reworked',eligible:false},{id:'deleted',eligible:true,deleted:true}];
 const available=availableSources(sources);
 assert.deepEqual(available.map(source=>source.id),['eligible']);
 assert.deepEqual(unavailableSourceIds(['eligible','reworked','deleted','missing'],available),['reworked','deleted','missing']);
});
