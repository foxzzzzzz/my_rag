import {test} from 'node:test'; import {strict as assert} from 'node:assert'; import {validReview,errorText} from './helpers.js';
test('审核需要有效分数及审核人，批准达到门槛',()=>{assert.equal(validReview('', 'approve',98,'本人'),false);assert.equal(validReview('97','approve',98,'本人'),false);assert.equal(validReview('20','rework',98,'本人'),true);assert.equal(validReview('NaN','reject',98,'本人'),false)});
test('冲突需要刷新',()=>assert.match(errorText(409),/刷新/));
import {uploadError,progressText,statusText} from './helpers.js';
test('上传扩展名与大小限制',()=>{let c={max_upload_bytes:100,max_html_bytes:20};assert.match(uploadError({name:'x.exe',size:1},c),/支持/);assert.match(uploadError({name:'x.html',size:21},c),/限制/);assert.match(uploadError({name:'x.mp4',size:101},c),/限制/);assert.equal(uploadError({name:'x.HTML',size:20},c),'')});
test('未知进度不显示百分比',()=>{assert.equal(progressText({completed_frames:2,total_frames:null}),'帧 2');assert.equal(progressText({completed_stages:1,total_stages:3}),'阶段 1 / 3');assert.equal(statusText('completed'),'已完成')});
test('实际任务状态和阶段显示中文',()=>{assert.equal(statusText('succeeded'),'已完成');assert.equal(statusText('preparing_video'),'准备视频');assert.equal(statusText('extracting_html'),'提取网页');assert.equal(statusText('asr_submit'),'提交转录');assert.equal(statusText('asr_result'),'获取转录结果');assert.equal(statusText('vision-3'),'视觉分析 · 帧 3');assert.equal(statusText('text'),'生成文本');assert.equal(statusText('verifying_source'),'校验来源');assert.equal(statusText('loading_provider_result'),'读取处理结果')});
import {formatDate} from './helpers.js';
test('排队无进度显示待开始',()=>assert.equal(progressText({},'queued'),'待开始'));
test('审核时间按配置时区显示',()=>assert.match(formatDate('2026-11-04T17:20:00Z','Asia/Shanghai'),/2026\/11\/05.*01:20/));

import {connectionText} from './helpers.js';
test('连接状态区分连接中、成功和失败',()=>{assert.equal(connectionText('connecting'),'正在连接服务…');assert.equal(connectionText('connected'),'服务已连接');assert.equal(connectionText('disconnected'),'服务未连接')});
test('无数值进度的终态任务不显示处理中',()=>{assert.equal(progressText({},'succeeded'),'处理完成');assert.equal(progressText(null,'failed'),'处理失败')});
import {suggestionSelection, suggestionError} from './management-helpers.js';
test('新分类默认不选择，已有建议可选择',()=>{const x=suggestionSelection({existing_topics:['a'],existing_tags:['b'],new_topics:['新'],new_tags:['标签']});assert.deepEqual(x,{existing_topics:['a'],existing_tags:['b'],confirmed_new_topics:[],confirmed_new_tags:[]})});
test('建议冲突和忙碌使用可理解提示',()=>{assert.match(suggestionError('classification_conflict'),/刷新/);assert.match(suggestionError('worker_busy'),/忙/)});
