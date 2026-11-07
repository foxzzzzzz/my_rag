# 回答自然分段与文章版式验收

日期：2026-11-06；PRD v0.22；编码前用例[P01–P06](answer-paragraph-test-cases.md)。按用户要求改善回答连成一段的阅读问题；不改原措辞、结论、证据或已提交评分。

## 展示效果

在安全句末、明确话题转换和较长并列分句处分段，以真实段落元素增加段距/行高。Q01–Q09段数依次为**2、3、3、5、3、5、4、1、1**；长答形成自然段，两道短拒答仍是一段。没有补写标题、改写句子或重新调用模型。

每段是原answer的连续切片，拼接后逐字等于原文。句末后连续引用（含其前的空白/换行）归前段，全文①编号不在新段重置。引号、行内/围栏代码、英文缩写的apostrophe、路径/小数、连续？！及已有空行有保守保护；没有安全边界时保持完整，不在固定字数强行截词。

规则统一外置于`config/answer-layout.json`。Python `tools/answer_layout.py`用于评分页，JS `web/src/answer-layout.js`用于正式React问答；源码answer及反馈canonical SHA算法不变。此规则是显示层启发式分段，不声称理解所有文体或实现完整Markdown解析器。

## 测试与独立复核

- 原评分器加分段专项共14项通过；Node导出与旧VM行为检查通过。
- 全部前端29项通过，隔离Vite构建成功；正式React改用各段`p`渲染，仍使用安全文本/①按钮与原引用复验入口。
- 独立23组跨端输入（含实际9题、空白/空行引用、连续标点、nested quotes、直/弯引号英文缩写、多反引号/波浪围栏、CRLF/emoji/路径小数）逐段一致，join逐字等于原文。原文不变、全文编号及原9题绑定均复验，无新增P0/P1。
- 最终完整后端**443 passed、5 skipped、44 subtests passed**，一条既有Starlette弃用警告，日志`reports/answer-paragraph-20261106/pytest-final2.log`。旧442快照保留，不当作最终结果；跳过边界沿用原平台记录，未扩大为目标Linux验收。

## 浏览器与数据验证

实际8765评分页已更新：检查Q01两段、Q03三段及全9题段数；点击Q03的②仍展开对应OpenManus原文，技术详情保持折叠。刷新后9题评分/决定和两条备注与更新前逐项一致，绑定仍原值。

再次点击导出，等待实际浏览器下载并读取文件，9题输出SHA/评分/决定/备注仍相同。390px宽视口scrollWidth为375，无横向溢出，测试后恢复默认视口。正式React本轮通过纯函数、构建和跨端复核，未为版式变化重新花费调用真实模型。

数据/截图位于`reports/answer-paragraph-20261106/`：draft-before.json、paragraph-answer.png、narrow-answer.png、browser-validation.json、root-verification.json及测试日志。新在线原件为`review-final2/`内review.html和同名JS/CSS，发布时三文件一起复制，回答的canonical报告仍沿用原始报告，不覆盖本人反馈文件。

原页面地址：<http://127.0.0.1:8765/assets/phase3-live-review-20261106.html#q0>。仅合并静态资源及前端index，未清除评分页资源、重建索引或重启服务；真实3来源/214块与原审核保持，研究账本不增加。无需重新评分。
