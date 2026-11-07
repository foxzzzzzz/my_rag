# 编号引用与来源证据可读性验收

后续补充：PRD v0.22已完成[回答自然分段](answer-paragraph-validation.md)，在本次编号来源显示上进一步增加自然段/段距，原文与评分绑定保留；当前部署原件改用reports/answer-paragraph-20261106/review-final2三文件，下方保留本轮编号优化历史。

日期：2026-11-06；PRD v0.21。先行[C01–C08](citation-readability-test-cases.md)，本人反馈核验见[确认记录](phase-3-answer-review-acceptance.md)。本轮仅优化显示，不调用模型、不重建索引、不改变已评分答案。

## 已完成的显示

正文中的已知完整引用显示为上标①②③，按该回答首次出现编号，重复片段复用同号；超过20个按配置使用数字后备。原64位ID仍在原回答/评分快照中，显示层不写回answer。

文末列编号、可读资料名及真实时间/字符范围；来源卡分为标题/定位、证据原文、默认折叠的“定位详情”。完整chunk/source/version/SHA及原定位仅在详情展开后显示，不混在阅读正文中。普通`[sandbox]`/`items[0]`不变；未知ID不变成可信链接，无依据拒答不附来源。

正式React问答页同步采用上述编号与分区。点正文脚注或来源编号仍请求正式citation接口复验，不能直接显示失效缓存；撤审/流异常清除旧证据并取消迟到请求展示。人工修订不继承旧视频时间；HTML字符范围不显示为视频秒数。参数集中在`config/citation-display.json`，两个渲染端共用标记及标签。

## 反馈、原文与导出一致

- 输入9题反馈均100/approve且绑定核验通过，原文件及SHA归档；显示优化不改变这些评价。
- 新旧报告的questions深度相等；原问题/回答/引用证据及全部规范输出SHA保持一致。
- 实际用户表单刷新前保全、更新后自动恢复，9题评分/决定和两条备注逐项一致。
- 优化后的真实HTTP页再次点击导出，浏览器download事件成功；实际文件9题run/question/SHA/评分/决定/备注与原草稿一致，记录export-regression.json。无需用户重新评分。

## 自动化与独立Review

| 验证 | 实际结果 |
|---|---|
| Python评分器专项 | 12项通过，含旧导出/转义/不覆盖、编号及绑定 |
| 全量后端 | 441 passed、5 skipped、44 subtests passed，53.45秒；1条既有Starlette弃用警告 |
| 全部前端helper | 23/23通过，含重复/首次顺序、21号后备、普通/未知引用、人改无时间、HTML与视频区分 |
| Node导出脚本及独立VM | 通过；同源CSP、草稿/导出绑定和新来源锚点不回归 |
| 独立跨端fixture | 23个引用顺序/后备一致、转义及不改问题，未知标识不能成为可信链接 |
| Vite隔离构建 | 成功；发布时合并复制assets、最后更新index，未清除现有评分资源 |
| 独立Review | 无新增P0/P1；修复技术SHA字段、流异常及迟到GET、人改时间等检查意见 |

全量测试后只有低影响CSS窄屏调整（表单宽度、长词断行、去重复列表号），通过后述真实浏览器验证，不虚称另一次完整回归。5项平台/可选依赖跳过含义沿用此前记录，不是目标Linux补验通过。

## 浏览器与发布证据

实际8765评分页验证正文①脚注、点击定位对应原文卡、技术详情默认折叠，原9题草稿及绑定不变；390px视口scrollWidth=375，无横向溢出，默认正文不含长ID；已恢复默认视口。实际下载再次核验通过。

正式React组件在独立8783合成库/假provider中完成问答→①→GET引用→证据分区、无依据拒答无脚注、生成间撤审清除回答/引用。仅合成数据有测试评分，未触碰真实内容或发生模型调用。临时tab及核对身份后的PID18844服务已关闭，8765原业务服务继续正常。

证据位于`reports/citation-readability-20261106/`：numbered-answer.png、source-evidence.png、narrow-review.png、formal-component.png、formal-invalidated.png、browser-validation.json、export-regression.json、pytest-final.log及root-verification.json。本人反馈归档在`reports/phase3-feedback-20261106/`。

原地址不变：<http://127.0.0.1:8765/assets/phase3-live-review-20261106.html#q0>。新版静态原件位于`review-final-narrow/`：将其review.html部署为原URL文件，并一起复制同名JS/CSS。前端重建清空dist后须重新部署这三个文件；保持已提交报告及评分绑定不变。

本机正式索引仍3来源/214块ready，真实资料的版本/审核字段与原批准快照一致，测试样例排除，账本不增加。静态评分页是已审核结果快照，实时资格仍以正式问答接口为准；本轮不保证静态快照后来撤审时自动消失。

当前本人问答评审及本机显示优化闭环已完成；Phase 4目标Linux完整业务资源、公网认证/HTTPS、备份恢复仍按计划另验。旧式静态transcript类型若仅有start/end字段，其可读摘要兼容仍可后续补齐，原定位保留在详情，不将此项冒充全部历史格式已覆盖。无commit/push/tag。
