# Phase 2D操作补充

日期：2026-11-05；PRD v0.16。验收结果与边界见[综合验收记录](phase-2-integration-validation.md)。现有资料/任务/手工分类/Obsidian操作继续沿用[管理指南](phase-2-management-guide.md)。

## AI分类建议

默认关闭，避免未经选择发起模型调用。需要使用时，仅将config/classification-suggestions.json中的enabled改为true，保留其余配置并重启PersonalKB服务；当前服务的建议配置在首次访问时加载，直接重复运行start_web.ps1只检查已有服务，不负责重启。重新载入页面后面板会显示生成入口。此操作不要求新Key，复用既有text模型配置和web配置的env_file；原手工分类一直可用。

打开来源详情的“AI分类建议”：勾选本次模型调用费用同意，点击生成。已有主题/标签建议与新候选分别显示，生成不会改变实际分类；新候选默认未勾选，只有明确选中并应用才创建。可只接受部分项，应用采用追加，保留手工已有分类；拒绝不变更分类。分类操作不改变正文/评分，新的正文仍须本人审核。

来源正文、现有分类或目录在生成后发生变化，会返回冲突；先刷新查看当前状态，再决定是否重新生成。生成失败或“需要处理”不表示可以安全重试未知POST，不会后台自动再调用；再次明确生成属于新操作。全局worker忙时不会并发开始第二次模型任务。

费用按共享研究账本预留并记录usage，默认单次保守预留0.20元（配置值，不是固定账单），未知调用保留预留，有有效usage时按配置价格结算。日常月费仍为观察项，研究累计上限100元保持。模型/提示词、上下文/目录/输出限额、传输主机/超时/响应大小及价格均在新配置中有说明，价格是既有配置估算，不代表实时账单。

接口（均沿用会话/CSRF）：

| 方法/路径 | 字段/用途 |
|---|---|
| GET `/api/classification-suggestions/status` | enabled，仅是否启用，不暴露Key |
| GET `/api/sources/{id}/classification/suggestions` | 最新持久建议或null，不触发模型 |
| POST 同上路径 | expected_version_id、expected_revision、allow_paid=true；明确生成 |
| POST `/api/classification-suggestions/{id}/apply` | existing_topics、existing_tags、confirmed_new_topics、confirmed_new_tags数组；只能选服务端本次建议项 |
| POST `/api/classification-suggestions/{id}/reject` | 拒绝该建议 |

未决请求保留状态与预算；同一建议重复相同选择幂等，不同选择冲突。失效来源/版本/目录不允许应用；不要复制模型结果自行上传来冒充服务端建议。

## 取消与资源占用

取消/删除会立即撤销提交资格，正在执行的同步HTTP或FFmpeg可能需要等待其返回。此时其他worker显示忙/暂不领取，不会因为任务已标取消就并发占用媒体资源。实际本地进程退出后内核释放执行锁；远端未知POST仍需要按原恢复规则处理，不能把本地结束当远端取消成功。不要手工删除执行锁文件来强行并发。

## 当前已知边界

本轮AI建议只用隔离fakeprovider验证控制流及网页，没有新真实模型调用或质量评分。现有业务库V01和两份HTML新版仍待本人评分，不能沿用历史预研批准。正式RAG索引/问答与云端部署仍是后续阶段。抖音已确认的authorized_playback规则保持，下载/导入不自动触发ASR或视觉。
