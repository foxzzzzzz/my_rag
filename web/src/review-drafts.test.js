import {test} from 'node:test';
import {strict as assert} from 'node:assert';
import {draftKey,emptyReviewDraft,updateReviewDraft,saveReviewDraft,reviewDraftSaved,canSubmitReview} from './review-drafts.js';

test('来源和版本共同隔离，缺少 ID 不生成键',()=>{
 assert.equal(draftKey('a',''), ''); assert.equal(draftKey('', 'v'), '');
 assert.notEqual(draftKey('a','v'),draftKey('b','v')); assert.notEqual(draftKey('a','v'),draftKey('a','w'));
 assert.notEqual(draftKey('a,b','c'),draftKey('a','b,c'));
});
test('保存为独立快照，修改后必须再次保存',()=>{
 const original=updateReviewDraft(emptyReviewDraft(),{score:'98',note:'原意见'});
 const saved=saveReviewDraft(original); assert.equal(original.saved,null); assert.notEqual(saved.saved,saved);
 assert.equal(canSubmitReview(saved,98),true);
 for(const patch of [{score:'99'},{note:'新意见'}]) {const changed=updateReviewDraft(saved,patch); assert.equal(reviewDraftSaved(changed),false); assert.equal(canSubmitReview(changed,98),false); assert.equal(changed.saved.note,'原意见');}
});
test('动态门槛、空值及低分决定',()=>{
 const draft=(score,decision='approve')=>saveReviewDraft(updateReviewDraft(emptyReviewDraft(),{score,decision}));
 assert.equal(canSubmitReview(draft(''),98),false); assert.equal(canSubmitReview(draft('0'),98),false);
 assert.equal(canSubmitReview(draft('97'),98),false); assert.equal(canSubmitReview(draft('98'),98),true);
 assert.equal(canSubmitReview(draft('97'),97),true); assert.equal(canSubmitReview(draft('0','rework'),98),true); assert.equal(canSubmitReview(draft('0','reject'),98),true);
 assert.equal(canSubmitReview(saveReviewDraft(updateReviewDraft(emptyReviewDraft(),{score:'98',reviewer:' '})),98),false);
});
test('未知提交结果下重复保存保持重试 ID，字段变化才重置',()=>{
 let d={...saveReviewDraft(updateReviewDraft(emptyReviewDraft(),{score:'98'})),reviewId:'retry'};
 assert.equal(updateReviewDraft(d,{score:'98'}).reviewId,'retry');
 for(const patch of [{score:'99'},{note:'x'},{reviewer:'甲'},{decision:'reject'}]) assert.equal(updateReviewDraft(d,patch).reviewId,null);
 assert.equal(saveReviewDraft(d).reviewId,'retry');
 const changed=updateReviewDraft(d,{note:'明确修改'});
 assert.equal(saveReviewDraft(changed).reviewId,null);
});
