# PersonalKB

2026-11-06当前：本人已批准视觉并启动Phase 4。**生产认证、部署与维护代码及迁移包已交付，目标云端待验收。** 请按[服务器操作手册](docs/phase-4-server-guide.md)第一节先回传预检；[本机验证](docs/phase-4-validation.md)记录476项后端/42项前端及真实迁移恢复证据。原资料审核不需重评，服务器路径变更后索引须明确重建。以下保留历史进度。

2026-11-06最新：已按本人反馈修正正式版偏离样稿的问题，[正式入口](http://127.0.0.1:8765/)恢复14px界面、品牌导航、上置筛选/日期列、审核分隔线与850px问答。[三页同尺寸对照及验收](docs/ui-implementation-consistency.md)已完成；等待3U-D本人确认修正效果，Phase 4未启动。以下“工程通过”为此前功能交付记录，不能代替本人视觉确认。

2026-11-06当前：**Phase 3U-C本机工程验收完成，第二版设计已接入正式前端。** [打开正式入口](http://127.0.0.1:8765/) · [验收与截图](docs/phase-3u-frontend-validation.md) · [操作指南](docs/phase-3-rag-guide.md)。现进入3U-D本人正式界面体验，Phase 4未启动。前端38项、后端443项通过；原3份审核/214块索引保持，无新增模型调用。

使用顺序：资料库打开资料 → 阅读正文及来源证据 → 如有新资料，保存评分草稿后明确提交审核；问答页输入问题，按需展开范围/设置并明确同意本次模型费用。当前3份资料与9题回答已获本人批准，无需重评或重建索引。

设计历史供对照：[第二版样稿](http://127.0.0.1:8765/assets/ui-prototype-v2-20261106/index.html#library) · [首版样稿](http://127.0.0.1:8765/assets/ui-prototype-20261106/index.html#library) · [skill调研](docs/ui-skill-research.md) · [项目skill](skills/personalkb-ui-design/SKILL.md)。以下早期阶段记录不覆盖上述最新状态。

回答版式更新：已支持自然段、段距与行高，保留①脚注和原评分绑定。[查看当前回答](http://127.0.0.1:8765/assets/phase3-live-review-20261106.html#q2) · [分段验收](docs/answer-paragraph-validation.md)。

2026-11-06最新：正式3来源/214块索引及9题问答已获本人100分/全部批准；按反馈完成①脚注与来源证据分区，原答案/评分绑定不变。[查看新版页面](http://127.0.0.1:8765/assets/phase3-live-review-20261106.html#q0) · [反馈确认](docs/phase-3-answer-review-acceptance.md) · [显示验收](docs/citation-readability-validation.md)。本机Phase 3当前样本闭环完成，Phase 4目标部署仍待实施；下文含历史阶段描述。

个人使用的Obsidian Markdown + 轻量RAG项目。Phase 2D和Phase 3本机工程已完成；云端部署仍待Phase 4。首轮预研批准不沿用到当前业务新版本，真实资料仍由本人审核。

当前[本机页面](http://127.0.0.1:8765/)支持导入/持久任务、证据复核/评分、分类/Obsidian往返和正式问答。可按来源/主题/标签检索，回答带引用，服务端更新或撤审后引用失效；客户端显示边界见[UI验收](docs/phase-3u-frontend-validation.md)。操作见[正式RAG指南](docs/phase-3-rag-guide.md)。2026-11-06已将本人批准3份业务资料（99/100/100分）构建成214块正式索引，工程样例排除；9题真实输出在[历史评分页](http://127.0.0.1:8765/assets/phase3-live-review-20261106.html)，均已获本人100分批准，无需重复评分。[交付记录](docs/phase-3-live-answer-validation.md)保留费用/引用/修复和限制。

Phase 3本机1万块/1024维合成性能复测：混合p95=0.509秒；假向量/假回答验证工程，不替代本人真实质量评价或目标Linux正式链路验收。下面保留历史分阶段证据；最新状态以PLAN、Todo和上述正式验收为准。

Phase 2A/2B持久领域层与视频自动编排证据保留，见[2A操作](docs/phase-2-workflow-guide.md)、[2B操作](docs/phase-2-video-guide.md)及[2B验收](docs/phase-2-video-validation.md)。本轮网页未新增模型调用，原累计保守预留仍22.00元；未替本人评分真实素材。

ASR双存储基础模块及离线回归已完成。C01已确认模型检索与轻量架构；C02开发默认使用已实测的百炼临时上传，正式私有OSS配置完成后由用户手动切换。正式OSS尚未真实联调，详见[存储配置与切换](docs/asr-storage-configuration.md)、[技术选型](docs/technical-selection-record.md)和[接入边界](docs/production-integration-boundaries.md)。日常月费仅列优化Todo，预研累计100元约束继续。

最新结果：[目标Linux媒体资源核对](docs/target-media-resource-validation.md)，报告已归档，无需重复运行；[操作指南](docs/cloud-media-resource-validation.md)保留供后续回归。

目标Linux索引阶段已通过，混合p95为36.26ms；原[索引包说明](docs/server-environment-assessment.md)和[问答评分页](reports/retrieval-trial-v1-20261104/review.html)保留查阅，无需重复执行已通过项。

最新状态：[四项复评及合并确认](docs/retrieval-review-acceptance.md)，当前15项最低98、平均99.53且全部批准；[四项确认页](reports/retrieval-revision-2-20261104/review.html)保留供查阅。

直接打开[本轮统一评分页](reports/demo-baseline-v1-20261104/review.html)，或查看[原始画面对照](reports/demo-baseline-v1-20261104/evidence.html)。模型链路、费用和限制见[结果报告](docs/demo-run-results.md)。

## 当前流程（PRD v0.2）

**现有sources素材 → 候选方案生成真实结果 → 本人看结果、打分、批准/返工/拒绝 → 决定选型。**

不再要求先做逐事实人工标注或补齐50视频/500事实。3视频+2HTML即可开始；先音画方案，再检索方案，最后冻结选型并开发主体业务。默认主观目标98分，不等于统计准确率。每份后续内容也要本人审核，分数高不会自动入库。

已确认：4C/4GB/40GB Linux；每日约10视频（平均5分钟以内）+10HTML+10问答；预研累计模型费100元不变，日常月费按使用量观察并列优化待办；Markdown长期保存、手动导出到Obsidian及重传更新。资源及先预研后开发门槛继续有效。

| 阅读内容 | 文档 |
|---|---|
| 产品规格及变更 | [PRD](docs/PRD.md) |
| 正式索引、问答、引用及失效操作 | [RAG指南](docs/phase-3-rag-guide.md)、[工程验收](docs/phase-3-rag-validation.md) |
| 当前推荐主方案及证据 | [技术选型记录ADR-001](docs/technical-selection-record.md) |
| 生产补测与未实现范围 | [生产接入边界](docs/production-integration-boundaries.md) |
| 本人需确认/稍后配置的事项 | [确认清单](docs/production-confirmation-checklist.md) |
| 当前阶段与门槛 | [实施计划](docs/PLAN.md) |
| 用户需要做什么 | [样本清单](docs/sample-preparation-checklist.md) |
| 新评审文件协议与命令 | [个人评审工具](docs/personal-review-contract.md) |
| 本轮模型和两个Key的配置 | [Demo配置指南](docs/demo-model-setup.md) |
| Key与三个模型真实探测 | [API验证结果](docs/api-key-validation.md) |
| 核心方案候选 | [技术预研](docs/technical-research.md) |
| sources文件检查 | [首批素材核查](docs/sources-readiness-assessment.md) |
| 实施前用例 | [评审测试用例](docs/personal-review-test-cases.md) |
| 当前任务及变化 | [TodoList](docs/TodoList.md)、[CHANGELOG](docs/CHANGELOG.md) |

## 离线评审工具

Python 3.12+，仅标准库。读取已经生成的真实转录/视觉/摘要/笔记产物，建立可本地打开的评审HTML；本人打分后下载反馈JSON，再汇总每份材料的状态和待优化问题。命令以[工具协议](docs/personal-review-contract.md)为准。

评审工具本身仅标准库；新增SQLite索引研究测试另需隔离依赖：`python -m pip install --target tmp/benchmark-deps -r config/research-requirements.txt`。服务器第一步环境检查不需这些依赖。

只需分数0–100、审核人及决定；备注和问题标签可选。默认≥98且批准才审核就绪，返工/拒绝或未审核均不就绪。审核就绪不是已经写入RAG。来源、方案、run或输出内容变化后重新审核；人工修订另存版本，保留原输出。

源HTML不直接运行，模型输出按文本转义，费用未知显示未知。没有真实产物时不填充假转录、假摘要或分数。工具不能证明内容语义、评审人身份或自报的调用来源，最终由本人判断。

```powershell
cd D:\codex_project\My_RAG\PersonalKB
python -m pytest tests -q
```

## 费用与服务配置

本轮demo用百炼北京paraformer-v2（REST临时上传）、qwen3-vl-plus视觉和DeepSeek deepseek-flash文本。只需在.env填写DASHSCOPE_API_KEY与DEEPSEEK_API_KEY；先用`python -m tools.demo_setup init`创建空模板，再用`python -m tools.demo_setup doctor --json`本地检查。模型/地址在config/demo-models.json，详见配置指南。C01已确认这些已测主模型及text-embedding-v4/1024检索基线；其他候选不自动成为备用。

配置工具不联网、不验证Key有效性。2026-11-04已另外执行真实能力探测和五份完整转换，运行器按2元探测、20元首轮demo及累计100元限制预留预算，结果见上述报告。不要通过聊天发送密钥或Cookie。

原预算工具继续可用：

```powershell
python -m tools.research_cli budget-check --actual 0 --pending 0 --new 10
```

示例金额不代表真实支出。检查实付、未结算预留、新批次上界是否超出100元。离线工具不联网、不代管账本、不原子预留，无法阻断外部调用。

## 可选的客观基准

原validate/freeze/evaluate保留为annotated_benchmark。50/500/98%及formal_pass不再代表当前个人评审流程的审批或入库条件。见[旧工具协议](docs/tool-contract.md)和[样本规范](docs/sample-specification.md)。

旧专项配置在config/research.json与config/acceptance-policy.json；个人评分使用单独配置。历史[验证记录](docs/verification-results.md)说明工具测试范围及限制。

sources/、samples/、data/、reports/、tmp/、密钥和数据库均忽略。临时脚本及合成测试文件放tmp/，不当作真实模型质量证据。

## 当前实施重点（2026-11-05）

Phase 2C1已通过本机验收；按[更新计划](docs/PLAN.md)已实现并完成本机工程验证[长期Markdown/永久附件与HTML模型接入](docs/content-storage-contract.md)，先行用例见[验收清单](docs/phase-2-content-test-cases.md)。两份真实HTML新结果待本人评分，详见[验收记录](docs/phase-2-content-validation.md)与[使用说明](docs/phase-2-content-guide.md)。分类、Obsidian ZIP/重传、抖音链接和综合验收随后完成；正式RAG/公网部署尚未开放。SQLite备份仍是恢复完整任务/审核历史的必要组成。

## 最新管理能力（2026-11-05）

2C2c分类/别名/筛选/批量与2C2d Obsidian笔记/附件ZIP/安全预览应用已工程验收，当前[本机页面](http://127.0.0.1:8765/)已升级。抖音2C2e支持可选独立解析环境与受控下载，默认关闭、真实Cookie/链接D05未验收。完整pytest 355通过/2跳过，11项前端及构建通过。本轮无新模型调用，内容评分仍由本人完成。

[进展与验收](docs/phase-2-management-validation.md) · [操作与配置](docs/phase-2-management-guide.md) · [Todo](docs/TodoList.md)。Phase 2整体、正式RAG与云端部署尚未通过，人工分类可用，AI分类建议仍在待办。
