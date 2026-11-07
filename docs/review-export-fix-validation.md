# 在线评分页JSON导出故障与验收

日期：2026-11-06；PRD v0.20；编码前用例见[E01–E06](review-export-fix-test-cases.md)。本次只修复导出和草稿保全，不改问答结果、原反馈绑定或业务审核，不调用模型。

## 原因与修复

初版评分页是离线自包含HTML，内联JS和CSS在8765主服务下被响应头CSP阻止。HTML中的meta策略不能放宽响应头，因此文字和表单可见，但导出监听器没有执行，样式也未正常加载。此前只验证展示和证据，没有实际下载验收，属于交付检查遗漏。

保留原默认离线模式，新增在线同源JS/CSS模式；不修改主服务CSP或原HTML sandbox。导出参数位于`config/review-export.json`，说明草稿开关及blob URL撤销延迟；客户端有可见的题目校验错误、空表单提示及只读JSON复制备用。下载链接先附着DOM再触发，延后撤销URL，页面只声明“已生成并发起下载”，不伪称知道浏览器保存成功。

草稿按run_id、question_id、输出SHA分别保存，跨运行/新输出不自动套用；localStorage不可用也不阻断导出。导出文件名限制安全JSON basename，资源同名不同内容在写盘前拒绝，同内容可复用，防止意外覆盖已有页面。

## 真实浏览器验收

1. 刷新前从用户当前tab的真实DOM读取9题评分/决定/备注/评审人，保存draft-recovery.json及latest-before-reload快照，并保留恢复JSON。
2. 将fixed-v3中的HTML/JS/CSS复制到现有8765静态资源目录，三个URL均HTTP200，服务CSP保持原值；没有另开端口或重启业务服务。
3. 通过UI逐项恢复表单，DOM比较与原草稿完全一致；不是在静态HTML中预填分数。9题原评分/决定及两项备注未变。
4. 在实际HTTP页面点击“导出JSON”，等待浏览器download事件，实际文件保存到`C:/Users/25311/Downloads/reviews-phase3-live-20261106.json`。
5. 读取实际下载文件：9题run/question/输出SHA、评分、决定、备注和评审人均与保全草稿一致；页尾显示下载发起说明和可复制JSON。
6. 再次刷新，9题评分/决定及两条备注自动恢复，确认新草稿保存逻辑实际生效。

证据目录：`reports/phase3-export-fix-20261106/`，含原草稿/刷新前快照、实际下载文件副本downloaded-feedback.json、download-proof.png及root-verification.json。导出仅生成本地反馈文件，不自动写回业务审核或据此提前进入Phase 4。

## 自动化与独立审查

- Python评分器9项测试通过，覆盖原安全转义/绑定/拒答/不覆盖及在线资源/CSP/路径与冲突保护。
- `node tests/test_review_export.mjs`全部断言通过：空白/缺决定/零分、9题与JSON一致、备注空白保留、延迟撤销、跨run/SHA草稿隔离、存储不可用。此脚本是一组断言，没有虚构测试项数。
- 独立Review另用Node VM检查下载点击异常仍可复制JSON、非法分数可见反馈等，通过；发现并关闭早期CSP替换影响样式索引、文件名和资源覆盖问题，无新增P0/P1。
- 最终全量438 passed、5 skipped、44 subtests passed，55.90秒；一条既有Starlette弃用警告。日志pytest-final.log同证据目录。平台跳过含义沿用Phase 3记录，未冒充目标Linux补验通过。

## 使用与重建

原地址不变：<http://127.0.0.1:8765/assets/phase3-live-review-20261106.html>。用户已填内容已恢复，并已实际导出一份到下载目录；需要修改时可继续编辑再导出。若下载被浏览器拦截，可复制页面下方的标准JSON文本。

重建前端可能清除生成页副本。恢复时须将`reports/phase3-export-fix-20261106/fixed-v3/`内同名HTML、JS、CSS **三个文件一起**复制回`web/dist/assets/`。不要再仅复制初版内联review.html到主服务。原始问答、评分快照和初版页面保留作历史证据，问题/答案及输出SHA没有变化。

用户草稿中提出的“正文引用改编号脚注”“来源索引和文字分离”已完整保留于导出JSON，本次不改写已评分答案或擅自当作最终确认；后续收到反馈确认后单独安排。无模型调用、付费、commit/push/tag。
