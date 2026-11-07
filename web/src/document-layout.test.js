import {test} from 'node:test';
import assert from 'node:assert/strict';
import {parseDocument,safeLink} from './document-layout.js';
test('dangerous links are rejected',()=>{assert.equal(safeLink('javascript:alert(1)'),null);assert.equal(safeLink('data:text/html,x'),null);assert.equal(safeLink('https://example.com/a'),'https://example.com/a')});
test('HTML remains plain text and common blocks preserve structure',()=>{const b=parseDocument('# Title\n\n<script>alert(1)</script>\n\n- one\n- two\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\n```\n<x>\n```');assert.deepEqual(b.map(x=>x.type),['heading','paragraph','list','table','code']);assert.equal(b[1].text,'<script>alert(1)</script>');assert.equal(b[4].text,'<x>')});
