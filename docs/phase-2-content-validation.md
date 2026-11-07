# 长期内容与 HTML 接入验收记录

日期：2026-11-05；PRD v0.12。编码前用例：[K01–K08 / H01–H08](phase-2-content-test-cases.md)。

## 结论与阶段边界

2C2a长期内容及2C2b HTML模型接入的本机工程验证完成。两份sources HTML已通过新业务派发链路生成真实模型结果，**新版本均待本人评分，无自动批准或RAG写入**。2C2c分类、2C2d ZIP/重传、2C2e抖音链接、2D综合验收及Phase 3/4仍未完成。

实现：稳定note_id、note.md、不可变版本MD/证据/清单、永久JPEG；SQLite同步代数与信任根、失败待同步和显式重放；CLI/网页统一导出；HTML静态结构、明确授权的模型模式、预算/缓存/未知POST控制及重新处理的新任务。

## 自动验证及独立审查

| 验证 | 结果与解释 |
|---|---|
| `python -m unittest discover -s tests` | 260项，258通过、2项既有Windows/POSIX平台跳过；日志`tmp/full-content-tests.log` |
| `python -m pytest tests/test_content_storage.py -q` | 8通过；此文件为pytest函数，未计入上述unittest数量，不重复相加误报 |
| `node --test web/src/helpers.test.js` | 9通过 |
| `node node_modules/vite/bin/vite.js build`（web目录） | 构建通过 |
| 最后HTML进度修正后的跨模块用例 | `python -m unittest tests.test_content_integration`，4通过；HTML只有阶段1/1，无虚构帧数 |
| 独立只读审核 | 关闭批准资格与文件校验不同快照的并发竞态、成功预览无法升级模型、长标题漏算上下文、嵌套表格丢字；限定范围复核未发现阻断项 |
| 跨模块检查 | 写盘失败后同一版本重放不重复POST/评分；CLI/Web在待审、批准、返工及旧版本下逐字节一致；Windows CRLF问题已修复 |

恢复验证使用故障注入和受控锁竞争；不是目标服务器真实断电验收。文件同步持有SQLite写锁且校验全部历史附件，小样本已过，大版本历史下的锁等待/资源表现仍待优化测试。

## 两份真实 HTML

私有产物目录：`reports/phase2-content-20261105-07d9f46d/`，含`live-html-report.json`、`postcheck.json`、完整业务数据与单篇Markdown。目录被Git忽略。

| 来源 | 新版本 | 用时 | 静态结构 | 结果 |
|---|---|---:|---|---|
| openmanus-源码拆解.html | `0948f2176c0647ecb33b1ab30c3ab45d` | 37.720秒 | 4表格、42代码块、2 SVG | 摘要868字、笔记17825字；同步通过、待本人 |
| smolagents-agent-拆解.html | `3bd89c3ac08a4ba6ae6269b22500d62b` | 38.032秒 | 4表格、22代码块、3 SVG | 摘要822字、笔记18254字；同步通过、待本人 |

使用已确认`deepseek-flash`，关闭思考、输出上限16384 token。两项总计50146 token，按配置价格快照估算0.205748元，**不是实际账单**；每项保守预留0.75元，累计研究预留22.00→23.50元，不释放未知预留。未增加ASR/视觉调用、未变更模型或开通正式OSS。

旧HTML的99/100分不迁移。静态SVG作为文本结构证据，未做SVG图像视觉识别；JavaScript被忽略，动态/远程资源和复杂公式仍有边界。不由模型自评语义质量。

## 真实永久附件与网页

在上述独立副本中补建旧V01的21张永久JPEG；临时移开整个`video-work`后，21张均可经WebService按永久路径/SHA读取，随后恢复缓存。所有来源内容校验通过，两个HTML原件SHA未变，真实新HTML评分均为空。对报告、Markdown与数据库扫描实际两个Key值，未发现泄露；不删除用户知识里的普通URL/代码示例。

现有浏览器页面验证：服务已连接、两份新HTML出现在资料库；分别打开显示模型、真实摘要、版本ID、待审核、费用同意未选和提交审核禁用。没有代替本人输入评分或点击重新生成。浏览器截图接口连续超时，未生成截图，不用旧截图冒充；保留结果页供本人查看。

## 下一步

本人复评两份新HTML（以及此前尚未评分的新V01）；工程继续以2C2c分类/批量管理、2C2d Obsidian往返、2C2e抖音链接和2D综合回归为顺序。当前内容待审不阻止独立工程工作，但不能作为正式RAG资料或宣布整体质量验收通过。
