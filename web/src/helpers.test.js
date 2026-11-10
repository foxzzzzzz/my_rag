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

import {htmlBodyPreview} from './helpers.js';

test('离线 HTML 优先在完整句末截取，保留闭合引号',()=>{
  const body = '第一句。她说：“第二句。” Third sentence. More text follows.';
  for (const [extract, expected] of [
    ['第一句。她说：“第二句。” Third', '第一句。她说：“第二句。”'],
    ['第一句。她说：“第二句。” Third sentence. More', '第一句。她说：“第二句。” Third sentence.'],
    ['第一句。', '第一句。'],
  ]) {
    const result = {body, summary:'正文预览：'+extract, provenance:'local_extraction'};
    assert.deepEqual(htmlBodyPreview('html', result), {text:expected, omitted:true});
  }
});

test('完整正文不标省略，无句末则沿用原提取长度且不误断小数',()=>{
  const result = {body:'浓度为3.14毫克每升', summary:'正文预览：浓度为3.14', provenance:'local_extraction'};
  assert.deepEqual(htmlBodyPreview('html', result), {text:'浓度为3.14', omitted:true});
  assert.deepEqual(htmlBodyPreview('html', {...result, summary:'正文预览：'+result.body}), {text:result.body, omitted:false});
});

test('仅离线 HTML 摘录或原样继承的摘录是正文预览',()=>{
  const result = {body:'第一句。第二句。', summary:'正文预览：第一句。第', provenance:'human_edited'};
  assert.deepEqual(htmlBodyPreview('html', result), {text:'第一句。', omitted:true});
  assert.equal(htmlBodyPreview('html', {...result, summary:'本人另写摘要'}), null);
  assert.equal(htmlBodyPreview('html', {...result, summary:'正文预览：自行撰写'}), null);
  assert.equal(htmlBodyPreview('html', {...result, provenance:'provider'}), null);
  assert.equal(htmlBodyPreview('video', result), null);
});

test('正文预览保留以 iPhone 开头的下一句之前的句末',()=>{
  const extract = 'First sentence. The old phone still works. iPhone users can switch';
  const result = {body:extract+' networks when traveling.', summary:'正文预览：'+extract, provenance:'local_extraction'};
  assert.deepEqual(htmlBodyPreview('html', result), {text:'First sentence. The old phone still works.', omitted:true});
});

test('浏览器无 Intl.Segmenter 时仍保留句末及闭合引号',async()=>{
  const segmenter = Intl.Segmenter;
  let preview;
  try {
    Intl.Segmenter = undefined;
    ({htmlBodyPreview:preview} = await import('./helpers.js?without-segmenter'));
  } finally {
    Intl.Segmenter = segmenter;
  }
  for (const [extract, expected] of [
    ['她说：“第一句。” 第二', '她说：“第一句。”'],
    ['The old phone still works. iPhone users', 'The old phone still works.'],
    ['Dr. Smith measured 3.14', 'Dr. Smith measured 3.14'],
    ['For example, e.g. A quick comparison', 'For example, e.g. A quick comparison'],
  ]) {
    const result = {body:extract+' millimeters.', summary:'正文预览：'+extract, provenance:'local_extraction'};
    assert.deepEqual(preview('html', result), {text:expected, omitted:true});
  }
});

test('缩写不会被误认为句末',()=>{
  for (const extract of ['Dr. Smith measured 3.14', 'For example, e.g. A quick comparison']) {
    assert.deepEqual(htmlBodyPreview('html', {body:extract+' units.', summary:'正文预览：'+extract, provenance:'local_extraction'}), {text:extract, omitted:true});
  }
});

import {taskControls} from './helpers.js';
test('派发队列使用持久模式并可取消，未派发任务仍可启动',()=>{
  for (const state of ['pending', 'working']) {
    const task = {status:'queued', dispatch:{state, processing_mode:'model'}};
    assert.deepEqual(taskControls(task, 'preview'), {mode:'model', action:'cancel', queuedForProcessing:true});
  }
  assert.deepEqual(taskControls({status:'queued'}, 'model'), {mode:'model', action:'start', queuedForProcessing:false});
  for (const [status, action] of [['running','cancel'], ['failed','retry'], ['cancelled','retry'], ['needs_attention','resume']]) {
    assert.equal(taskControls({status}, 'preview').action, action);
  }
});

test('隐藏已归档或结果未知的恢复动作，保留可查询任务的恢复',()=>{
  const task = {status:'needs_attention', dispatch:{processing_mode:'model'}};
  assert.equal(taskControls({...task, archived:true}, 'preview').action, undefined);
  assert.equal(taskControls({...task, resume_blocked_reason:'unknown_submission'}, 'preview').action, undefined);
  assert.equal(taskControls(task, 'preview').action, 'resume');
});
