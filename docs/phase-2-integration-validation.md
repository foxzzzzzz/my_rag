# Phase 2D综合验收记录

日期：2026-11-05；PRD v0.16；状态：**本机工程综合验收通过**，未启动Phase 3/4。先行用例：[I01–I18](phase-2-integration-test-cases.md)，补充契约见[2D契约](phase-2-integration-contract.md)。真实内容本人评分、AI建议在线效果及目标Linux专项仍分别保留，不将合成结果解释成这些项目通过。

## 基线与审查

基线完整后端回归371 passed、3 skipped、44 subtests，40.79秒；独立SDK 8项OK；前端12项与Vite构建通过。日志位于tmp/phase2d-baseline-pytest.log。此为修复前基线，不冒充最终结果。

独立审查发现两项P1：PRD已有AI建议/新主题确认尚未实现；取消/删除只撤租约却没有等待原同步调用实际退出，多worker可提前执行第二任务。两项均已先补PRD/契约/用例，正在实现与独立复核；现有单模块测试通过不足以关闭缺项。

## 已完成的综合证据

- 新tests/test_phase2_integration.py当前4项合成流程通过，覆盖完整HTML导入/去重→生成→测试批准→分类/别名改名→MD/ZIP→正文和分类联合往返→新版待审→再批准/撤回→删除→重复原件拒绝，以及列表/资格/detail/导出交互。
- 预览后分类改名CAS、应用中注入分类事务异常、同步写盘失败/恢复及大小/磁盘配置边界均有断言。评分仅隔离库synthetic，不代表本人评分或模型质量结果。
- 既有真实工作库只读清单：reports/phase2d-real-evidence-20261105-92451.json。包含V01、H01、H02及一条历史网页工程样本，共四来源，当前均pending、无正式资格；不将工程样本描述为四份真实业务素材。未修改真实评分/版本或运行worker。D05原报告/blob/source SHA再次核对一致。
- 执行互斥新增跨进程锁、同线程重入、取消/删除期间阻塞第二worker、子进程终止释放、实际HTML调用阻塞时视频resume/cleanup/Douyin入口不执行的测试。针对性97 passed、1 skipped、5 subtests；跳过为当前Windows无法实测POSIX fork，不扩大为Linux部署通过。

## 修复与最终验收

已关闭两项P1：补齐AI建议持久生成/显式应用及完整Web交互；跨进程execution_guard覆盖实际worker入口，取消撤提交资格但占用保持到执行退出。新增fork子进程继承FD恢复边界，Windows/POSIX使用对应内核锁；不以本机跳过项声称POSIX已实测。

AI建议先明确同意与预算预留，复用既有text服务，建议结构/类型/限额校验，正文版本/SHA、分类revision及目录摘要三重CAS，已知usage按配置价格结算，缺usage和未知POST保守保留预留。未决生成在安全取得执行锁后恢复needs_attention；应用同一建议的不同选择返回冲突，同选择幂等。用户明确确认的新分类才在原子事务创建，分类变更不改正文或评分。默认enabled=false，手工分类不受影响，启用步骤见[操作补充](phase-2-integration-guide.md)。

| 用例 | 本轮工程结论与证据 |
|---|---|
| I01–I03 | 综合HTML导入/去重/删除后拒绝静默复活；视频/下载入口沿用已有回归和D05真实闭环，D05只读哈希复核通过，无新增下载 |
| I04 | 取消/删除期间Event阻塞实际调用，其他claim/resume/下载/清理不执行；跨进程持锁/terminate后释放；POSIX fork待目标环境补验 |
| I05–I08 | 永久证据、MD/版本/资格、修订待审、同步失败/损坏/恢复及历史评分隔离通过综合与既有专项 |
| I09 | 分类/别名/元数据CAS、列表topic/tag/review AND筛选、当前MD/导出一致通过 |
| I10 | 后端/API/前端与假模型网页完整点验通过；真实供应商分类输出效果本轮未调用，不当作质量评分通过 |
| I11–I12 | 正文与分类联合往返、预览后目录变化、事务故障回滚、幂等和冲突通过 |
| I13 | 隔离8766网页：新分类默认未选，应用已有建议才改分类；拒绝不变更；重新生成/逐项确认后才创建新主题；正文版本仍同一且待审核 |
| I14–I16 | 大小/磁盘配置、执行/下载保护、策略/凭据/HTML/ZIP/会话CSRF等由新增综合及全量既有回归验证；不扩大为目标整机资源验收 |
| I17 | 四来源当前版本和最新审核与只读清单一致；三份实际业务材料及一份历史工程样本仍待审核，未代评分 |
| I18 | 最终全量391通过/4跳过/44子测试，独立SDK8项、前端14项及构建通过；独立Review无P0/P1阻塞 |

初次综合快照为390通过；收尾核对又发现AI内部分类实例未继承手工分类自定义配置，已修为同一配置并新增超限应用原子回滚测试，相关26项通过。最终命令：`python -m pytest tests -q --basetemp tmp/phase2d-final-config-20261105-92451`，**391通过/4跳过/44子测试**、43.00秒、退出0，最终日志pytest-config-final.log；上一390快照/日志仍保留。独立SDK `python -m unittest tests.test_resolver_guard -q` 为8项OK；web中`node --test src/helpers.test.js src/management-helpers.test.js`为14项通过，`node node_modules/vite/bin/vite.js build`成功。后两者代码未受配置修复影响，沿用其快照；各自结果不相加，既有Starlette/Loguru弃用提示保留。

报告目录：`reports/phase2d-integration-20261105/`，含最终日志、automated-validation.json、root-verification.json及ai-classification-browser.png。root-verification包含19项实现文件哈希、服务健康及真实数据比对。主Agent为解释跳过项，另定向执行`-rs`筛选验证：1通过、4跳过、37排除。4项分别为POSIX fork、POSIX进程组、Windows无法创建符号链接、基础环境未装可选F2；F2已在独立环境8项补验，其余平台限制留目标Linux专项。筛选数量不加进391。

独立Review在禁止外部DNS/连接下补跑后端33通过/1 POSIX跳过、前端14通过。Windows asyncio内部socketpair回环握手被初版严格封锁误伤，单独允许该内部握手后API15项通过；这是测试封锁修正，不是业务失败或放开外部网络。

## 服务、真实数据与剩余边界

现有8765服务已在核对无running/pending任务、无媒体维护占用后，从经验证的旧PID19416升级；首次PID12844，配置一致性收尾修复后最终PID26940，沿用原web/workflow配置。健康/session与新建议状态接口可用，enabled=false；四来源当前版本/最新审核再次比对不变。未读取/改写.env，没有付费模型调用。8766假模型演示服务PID25500已核对身份后停止，保留隔离数据与截图。

仍保留：V01及两份HTML新版本人复评、AI分类建议真实效果的用户主动生成/确认、实际Obsidian客户端属性改写、POSIX专项、完整目标业务资源共存和Phase 4部署/清理/备份恢复。待审材料不得参与正式问答。Phase 3正式索引/问答未实施或开放；不以本轮工程通过宣布首次生产可用。无commit/push/tag。
