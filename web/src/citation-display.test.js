import test from 'node:test';
import assert from 'node:assert/strict';
import {displayAnswer,locationText} from './citation-display.js';
test('known citations preserve order and repeat; unknown and ordinary brackets remain text',()=>{let a='a'.repeat(64),b='b'.repeat(64),u='c'.repeat(64);let d=displayAnswer(`[${b}] [sandbox] [${a}] [${b}] [${u}]`,[{chunk_id:a},{chunk_id:b}]);assert.deepEqual(d.items.map(x=>x.id),[b,a]);assert.equal(d.parts.filter(x=>x.marker).map(x=>x.marker).join(''),'①②①');assert.ok(d.parts.some(x=>x.text?.includes(`[${u}]`)));});
test('human edits never claim video time',()=>assert.ok(!locationText({locator:{origin:'human_edit',seconds:12}},true).includes('12')));
test('overflow numbering and repeat are stable',()=>{let ids=Array.from({length:21},(_,i)=>i.toString(16).padStart(64,'0'));let d=displayAnswer(ids.map(x=>`[${x}]`).join('')+`[${ids[20]}]`,ids.map(chunk_id=>({chunk_id})));assert.equal(d.items[20].marker,'[21]');assert.equal(d.parts.filter(x=>x.marker==='[21]').length,2)});
test('location respects media type and valid nonnegative times',()=>{assert.doesNotMatch(locationText({locator:{start:3,end:9}},false),/秒/);assert.doesNotMatch(locationText({locator:{origin:'human_edit',start:3,end:9}},true),/3|9/);assert.doesNotMatch(locationText({locator:{start:-1,end:9}},true),/-1/);assert.match(locationText({locator:{start:3,end:9}},true),/3 秒 至 9 秒/)});
test('uppercase hexadecimal IDs are recognized',()=>{let id='A'.repeat(64);assert.equal(displayAnswer(`[${id}]`,[{chunk_id:id}]).items.length,1)});
