# 音画提取与中文检索技术预研

## 2026-11-04 Phase 1D状态

材料与当前15项问答已获本人批准；[目标Linux索引](target-index-validation.md)和[三视频离线媒体资源](target-media-resource-validation.md)已核对通过。月费仅观察Todo。已整理[ADR-001主方案](technical-selection-record.md)、[生产边界](production-integration-boundaries.md)及[C01/C02确认清单](production-confirmation-checklist.md)，当前待本人确认与正式ASR存储最小补测，尚未冻结或进入主体开发。下方保留各历史时点，不把旧状态当当前要求。

## 2026-11-04 实测进展

本轮3视频+2HTML已由本人评分100/99/100/100/100且全部批准，版本核对通过。已执行两种分块、百炼v4与qwen3.7-text-embedding-flash的真实检索初筛，生成15道问答待本人评分，见[检索实测报告](retrieval-trial-results.md)。生产主备、embedding及检索方案仍未冻结，目标机资源/月成本待验收。下方各日期记录保留当时状态，以本节及结果报告为当前进度。

## v0.3 本轮demo基线（2026-11-03再次核实）

本轮确定paraformer-v2（百炼北京REST+临时上传）、qwen3-vl-plus、deepseek-flash。需百炼与DeepSeek两个Key；尚未真实调用或生产冻结，详见[配置指南](demo-model-setup.md)。当前官方北京价格表能核实qwen3-vl-plus，旧Flash快照不直接作为默认；Paraformer临时URL只用官方REST，不混用SDK。先2元内探测，再20元首轮demo，累计研究上限仍100元。下方其他候选和旧价格仅作历史对照，以本次指南来源与实际账号响应为准。

## v0.2 当前实验口径（2026-11-03）

依据 [PRD v0.2](PRD.md) 和 [实施计划](PLAN.md)，直接使用现有sources的3视频+2HTML运行真实转换并展示。本人逐份给整体0–100分及approve/rework/reject，备注/问题标签可选；默认目标≥98分且明确approve。分数是个人主观评价，不是统计准确率或覆盖率；高分仍需批准，低分需返工，不用平均分掩盖低分/未审核项。不存在真实结果时只显示待处理，模型自评、模拟结果不能替代本人评审。

每份展示转录、带时间的画面文字/描述、摘要、来源笔记、耗时、费用（未知须说明）及来源SHA256、run_id、方案和输出版本。机器原始输出与人工修订分开保存、分别评分。任何结果变化须重新评，同版本最新明确决定生效，rework/reject撤销旧approve，历史保留。当前离线工具只汇总审核就绪，不实际写入RAG，见 [个人评审协议](personal-review-contract.md)。

推进顺序：核实服务配置/价格和预算 → 最小能力探测 → 五份完整真实转换展示 → 本人逐份≥98并明确认可、能力与预算条件通过 → 真实问题检索与出处核对 → 成本/目标机资源验收 → 本人明确选择主方案及必要备方案 → 主体业务。主备目前均未冻结，无真实ASR结果或已评分/已入库结论。每份新内容后续也须评分审核；反馈按版本汇总，低分反推ASR/视觉/抽帧/提示词优化。版本变化先在本批demo回归重评，不自动重跑、花钱、批量推广或切供应商。

旧50视频/500事实、30/20划分、98%双客观指标、60+20问题与Recall门槛已取消强制地位；如需另行启用，明确标注annotated_benchmark，旧formal_pass不是当前personal_review批准。样本多样性缺口可按反馈补充，不作为开始当前demo的前置条件。

预算不变：预研总模型费≤100元、完整月链路目标≤100元。保留原分项成本公式和候选价格事实，不把历史假设当作实际账单。当前建议配额为最小探测5元、五份demo候选比较35元、返工/版本回归20元、通过音画后检索15元、重试/双轨缓冲15元、未分配预留10元；每批按已结算+未决预留+最坏上界检查，未知价格不放行。具体调用量以实际五份素材计算，不要求填满配额；回归也需明确运行安排，不能自动消耗预算。

日常10视频（平均≤5分钟）+10HTML+10问答×30天及4C4G40G、整机≤3GB、1万块本地p95≤1秒仍有效，均待实测。本人主观高分不能豁免时间戳、有效引用、安全或预算检查。

## 历史 v0.1 研究记录（以下原记录保留，流程口径已被上节取代）

以下候选表、官方来源、日期、成本示例及当时未实测状态保留原事实；其中强制gold/样本数/客观门槛、旧预算实验分配和“下一轮”顺序是v0.1历史方案，不是当前实施要求。当前流程只按上节及PRD v0.2执行，不重新联网或冒充新增实测。

调研日期：2026-11-03（Asia/Shanghai）。本文仅记录官方文档、公开仓库和本地参考代码的只读核对；没有调用付费模型、读取真实密钥、执行媒体实验或服务器压测。所有候选均未冻结。文档可调用不等于账号可用，更不等于质量通过。

## 1. 决策边界与先验测试用例

约束来自 [PRD](PRD.md)：每日 10 条中文视频、平均每条 ≤5 分钟，10 份 HTML、10 次问答；30 天估算为 300 条/1,500 分钟视频、300 HTML、300 问答。Linux 无 GPU，4C/4GB/40GB；预研总模型费 ≤100 元，完整月模型链路目标 ≤100 元。文本默认 DeepSeek；ASR、视觉、embedding 各自配置服务地址、模型、密钥引用和能力参数。

先验验收用例（实现前确定，尚未执行）：

| 编号 | 输入/操作 | 应观察的结果 |
|---|---|---|
| AV01 | 清晰口播、行业术语、数字单位、近音词 | 原始转录与关键事实逐项对照人工真值；不能以摘要流畅替代准确率 |
| AV02 | 静音图文、板书、流程图、表格、快闪文字 | 抽帧覆盖视觉独有事实；OCR 文本及视觉关系绑定原始帧与时间 |
| AV03 | 音画冲突、画面修正前述数字、长教程尾部 | 保留双方证据与先后顺序，明确冲突；不能只保留口播或开头 |
| AV04 | ASR 无时间戳、空输出、超时、限流、重复提交 | 标记能力缺失/失败；时间不得伪造为 0 秒；重试记账且有效缓存复用 |
| AV05 | 含动态内容的 HTML | 静态提取正文、表格、公式和内嵌数据；不运行脚本；未提取内容明确标记 |
| R01 | 同一语料、同一切块、同一中文问答集切换 embedding | 独立索引，禁止跨模型/维度混搜；比较词法、向量、混合召回 |
| R02 | 跨片段、多来源、数字、别名、尾部和无答案问题 | Recall@10 与原始证据匹配；引用可定位；无证据不得虚构答案 |
| R03 | 删除/更新笔记、更换 embedding | 旧引用失效，重建索引后与主数据一致 |
| OPS01 | 目标服务器单视频处理和 1 万块检索 | 整机峰值内存 ≤3GB，本地检索 p95 ≤1 秒；记录磁盘及临时文件峰值 |

质量门槛严格串行：先完成至少 50 视频/500 原子事实、30 开发+20 锁定验收，机器初始关键事实准确率与覆盖率分别 ≥98%；再做至少 60 有答案+20 无答案的检索与回答实测，证据 Recall@10 ≥95%，引用有效且可定位。人工修改后结果另报，用户逐视频复核不能替代机器指标。预算不足时报告未完成项目，不缩小验收集宣称通过。

## 2. ASR：三条候选路径

| 候选/官方模型 ID | 调用与时间戳 | 公开费用（人民币） | 需要验证/当前判断 |
|---|---|---|---|
| 百炼 `paraformer-v2` | DashScope 原生异步任务：提交可访问媒体 URL → task_id → 轮询 → 下载转录结果。句/词时间信息；支持 `timestamp_alignment_enabled` 校准；不是通用 `/audio/transcriptions` 文件上传协议 | 北京录音文件识别 0.00008 元/秒，即 0.288 元/小时 | 低成本基线候选；术语、弱音、噪声、快语及时间边界须实测；媒体临时托管权限和附加费用须核算 |
| 百炼 `qwen3-asr-flash-filetrans`（有 `-2025-11-17` 快照） | 大文件异步识别；官方明确只有 DashScope 异步路径支持时间戳。默认句级，`enable_words=true` 开启词级；毫秒转换为统一秒单位 | 北京 0.00022 元/秒，即 0.792 元/小时；国际价格不同 | 作为不同 ASR 模型对照；不要把 `qwen3-asr-flash` 的同步短文件聊天格式当成相同契约 |
| 硅基 `FunAudioLLM/SenseVoiceSmall` | `POST https://api.siliconflow.cn/v1/audio/transcriptions`，multipart `file`+`model`；当前文档输出仅 `text`；文件 ≤50MB、时长 ≤1h | 官方使用文档称为免费服务，但本次未取得当前模型控制台计费快照，预算价格标记待核实 | 可做转录质量对照；**缺少文档保证的分段时间戳**，不能直接作为带时间证据主路径。需另测对齐方案并计费用/资源；不能按字符均分伪造时间 |

依据：[Paraformer 原生 HTTP](https://docs.bailian.console.aliyun.com/zh/model-studio/paraformer-recorded-speech-recognition-restful-api)、[百炼价格](https://docs.bailian.console.aliyun.com/en/model-studio/model-pricing)、[Qwen3 文件模型与价格](https://help.aliyun.com/zh/model-studio/qwen3-asr-flash-filetrans)、[非实时识别及时间戳差异](https://help.aliyun.com/en/model-studio/non-realtime-speech-recognition-user-guide)、[模型输入限制](https://help.aliyun.com/en/model-studio/asr-model/)、[硅基转录协议](https://docs.siliconflow.cn/docs/api/audio-transcriptions-post)、[硅基免费服务说明](https://docs.siliconflow.cn/docs/usercases/use-siliconcloud-in-BiBiKeyboard)。以上均于 2026-11-03 核对；免费额度不作为长期成本成立的前提。

适配器应保留原始响应、供应商任务 ID、实际模型、usage、分段开始/结束时间及时间粒度；缺失结束时间须显式记录，不能声称精确引用。异步轮询超时后先查询已有任务，不能直接重交导致双重收费。外部媒体 URL 采用有限有效期和受控访问，原视频可先转为压缩音频；不得因公开 URL 要求而任意公开原素材。

## 3. 视觉/OCR：不能沿用旧的 DeepSeek 能力印象

| 候选/实际 ID | 接口差异与适用范围 | 当前价格/待验证 |
|---|---|---|
| DeepSeek `deepseek-flash` | 官方当前 Vision 文档明确支持图片，Chat Completions 采用 `image_url` 内容块，可用 base64/URL；可用于截图文字与图表理解。旧 `deepseek-v4-flash-vision-exp` 已退役并路由新 Flash，不能用旧名冒充固定模型版本 | 官方峰时美元价：未命中输入 $0.30/百万 token、输出 $1.20/百万 token；图片计入输入。当前文档单图上限 1024 token。人民币实付与汇率/计费渠道待核对 |
| 百炼 `qwen3-vl-flash-2026-01-22`（别名 `qwen3-vl-flash`） | 兼容聊天图片输入或 DashScope 原生多模态；非思考/思考可配置，Qwen 的 `enable_thinking` 属供应商参数；用于图表关系、演示步骤等视觉语义 | 北京且单请求输入 ≤32K：输入 0.15 元/百万、输出 1.5 元/百万 token；更长上下文单价升高 |
| 百炼 `qwen-vl-ocr-2025-11-20`（别名 `qwen-vl-ocr`） | OCR 专项：OpenAI 兼容与 DashScope 两种协议，支持 OCR 特有 `ocr_options`；用于密集字幕、板书、表格转写。OCR 模型不能单独证明流程关系/动作含义完整 | 北京输入 0.3 元/百万、输出 0.5 元/百万 token；官方标注不支持结构化输出能力，不得假定 JSON Schema 强约束有效 |

依据：[DeepSeek 当前 Vision](https://api-docs.deepseek.com/guides/vision/)、[DeepSeek 价格](https://api-docs.deepseek.com/quick_start/pricing/)、[DeepSeek 更新记录](https://api-docs.deepseek.com/updates/)、[Qwen 视觉调用说明](https://help.aliyun.com/zh/model-studio/vision/)、[Qwen 公开价格](https://help.aliyun.com/zh/model-studio/model-pricing)、[OCR API](https://help.aliyun.com/en/model-studio/qwen-vl-ocr-api-reference)、[OCR 模型信息](https://help.aliyun.com/zh/model-studio/qwenvl-ocr)。核对日期 2026-11-03。DeepSeek 更新记录含 2026-10-17 Flash 更新；调用时还应记录返回版本/响应元数据，滚动别名不能保证实验复现。

官方网页也存在旧页面/不同协议描述差异：DeepSeek 旧集成页仍有文本模型说明，应以当前具体模型 Vision 文档和最小图片探测结果为准；本轮仅建议先用 Chat Completions 图片路径，不依赖 Files/Responses 的扩展语义。百炼地域与 Workspace 地址可能不同，按账号实际官方接入页配置，不能把旧地址/他人 Workspace ID 写死。

抽帧是质量和成本的重要自变量。先做可追踪的时间采样+场景变化候选，再测去重、快闪文字补帧；每个输出绑定帧哈希、原始时间与裁剪位置。候选裁剪、缩放可能丢失小字；仅测 OCR 字符正确率不能证明关键事实覆盖。单路视觉、OCR+视觉双轨应在同一开发集对照，只有证据证明必要时增加常态双轨；冲突应展示给人工而非让融合模型无依据选边。

## 4. 中文 embedding：三个候选，不混用供应商能力

| 候选 | 文档可核实规格 | 接口与费用 |
|---|---|---|
| 百炼 `text-embedding-v4` | 中英文等多语言，默认 1024 维，可选 64–2048 的指定维度；兼容 API 每批 ≤10 条、单条 ≤8192 token | 兼容 `/embeddings`，`dimensions` 指定维度；北京 0.5 元/百万输入 token。兼容接口不输出 sparse，需稀疏向量时另用 DashScope |
| 硅基 `Qwen/Qwen3-Embedding-4B` | 官方模型卡为多语言指令 embedding；硅基文档列 32768 token、可选 64–2560 的指定维度 | `https://api.siliconflow.cn/v1/embeddings`，字符串/字符串列表；`dimensions` 仅其 Qwen3 系列支持。当前价格未取得可靠官方快照，记为未知，不按免费或旧价估算 |
| 硅基 `BAAI/bge-m3`（`Pro/BAAI/bge-m3` 为独立计费 ID） | BAAI 官方模型卡为 1024 维、8192 长度，多语言；模型原生存在 dense/sparse/ColBERT 能力 | 硅基 `/embeddings` 文档是 dense embedding 返回，不能推定开放原生全部能力；`dimensions` 不适用于 BGE。免费/Pro 价格与账号可用性待控制台核对 |

依据：[百炼兼容 embedding](https://help.aliyun.com/zh/model-studio/embedding-interfaces-compatible-with-openai/)、[v4 原价](https://help.aliyun.com/en/model-studio/text-embedding-v4)、[硅基 embedding 参数](https://docs.siliconflow.cn/docs/api/embeddings-post)、[Qwen 官方模型卡](https://huggingface.co/Qwen/Qwen3-Embedding-4B)、[BAAI 官方模型卡](https://huggingface.co/BAAI/bge-m3)。核对日期 2026-11-03。硅基 API 页面有文本及 VL embedding 多个参数区段，不能把多模态对象输入套到所有文本模型。

Qwen 查询指令按官方模型卡构建，查询和文档处理差异须作为实验参数记录；BGE-M3 不要求添加相同指令。实验固定切块、词法分词、top-k 与融合策略，分别报告纯词法、纯向量、混合召回。若增加 reranker，单列费用和消融结果。模型换代、归一化或维度改变均生成独立 index_version 后重建；禁止仅因维度相同就共用向量空间。本机不部署这些模型，4GB 资源留给媒体处理和检索。

## 5. 开源参考与服务器适配

stars 由 GitHub 官方仓库 API 在 2026-11-03 20:15（+08:00）读取 `stargazers_count`，不是页面四舍五入值。stars 仅说明关注度，不能证明中文召回、引用准确性、资源成本或代码质量。

| 官方项目 | stars / 许可证核对 | 可参考内容 | 本项目判断（推断，待压测） |
|---|---|---|---|
| [sqlite-vec](https://github.com/asg017/sqlite-vec) / [API](https://api.github.com/repos/asg017/sqlite-vec) | 8,236；仓库提供 Apache-2.0/MIT 文件，复用时按实际文件条款确认 | C 实现 SQLite 向量扩展、vec0、元数据/分区列；官方明确仍 pre-v1 | 优先实验候选：单用户和可重建索引匹配，搭配独立中文词法召回；需锁版本、验证过滤/更新/删除与扩展装载 |
| [RAGLite](https://github.com/superlinear-ai/raglite) / [API](https://api.github.com/repos/superlinear-ai/raglite) | 1,212；MPL-2.0 | Python RAG 工具包、关键词+向量检索、分句切块与重排；当前 README 使用 DuckDB/PostgreSQL，不能凭名字理解成 SQLite 包装 | 可参考切块/评测或作为对照；数据库、依赖和封装与自有数据契约的适配成本需测；复用文件保留许可证义务 |
| [LightRAG](https://github.com/HKUDS/LightRAG) / [API](https://api.github.com/repos/HKUDS/LightRAG) | 40,507；MIT | 图结构+向量双层检索、增量更新/删除、多存储实现 | PRD 首版排除图数据库；不因 stars 高引入图谱。图实体关系提取会引入额外模型调用与验证负担。可参考引用/缓存思路，暂不作主框架 |

SQLite+词法+向量只是优先实验方向，尚未选定。1 万块×1024 维×4 bytes≈39.1MiB 原始 float32，2048 维约78.1MiB；不包含元数据、FTS、页结构、Python 对象和工作集，不能据此宣称整机内存达标。中文 FTS 的分词/字粒度与短数字精确匹配必须实测。目标机以单视频执行，模型都走 API；ffmpeg 一次处理一段、关键帧落盘，避免同时解码全部帧入内存。40GB 磁盘按保留7天视频、长期关键帧/HTML、索引、日志、临时峰值及备份计算，<8GB 可用空间暂停接收。备份和原素材容量可能比向量更早成为瓶颈。

## 6. TokBrain 的复用边界

本地只读参考：[既有分析](../../TokBrain/project-analysis.md)、[媒体处理](../../TokBrain/app/services/content_pipeline.py)、[关键帧](../../TokBrain/app/services/keyframes.py)、[模型适配](../../TokBrain/app/services/providers.py)、[检索](../../TokBrain/app/services/knowledge.py)、[密钥](../../TokBrain/app/services/secrets.py)、[MIT 许可证](../../TokBrain/LICENSE)。核对到的代码事实：检索 SQL `.all()` 取出合格块，Python 遍历向量计算并排序；DPAPI 明确在非 Windows 系统报错。

可复用的是媒体校验、ffmpeg 参数组织、候选帧策略、阶段任务、费用预留/结算、证据类型区分与可恢复错误等实现思路及经过复核的纯函数；实际复制前检查依赖、输入契约、许可证与测试。不能整包搬运：

- Windows DPAPI 不适用于 Linux 云端；秘密配置需独立部署方案，密钥不进入 Markdown、导出和日志。
- SQLite 中 Work/Chunk 等既有主数据结构不能替代本项目 Markdown 主数据、稳定 ID、版本冲突及可重建索引契约。
- 全量加载 JSON 向量+Python 全排序不能直接作为目标规模方案；即使线程隔离也不会消除规模增长。必须用统一检索实测比较。
- 既有提示词、mock 测试、人工确认流程和历史功能完成记录不能证明本项目 98%/95% 门槛通过；硬编码阈值和供应商参数需外置并解释。

## 7. 成本模型、预研配额和停止条件

本节是预算方法与**假设示例**，不是实付预测或费用验收。公开价采用上文来源及地域；不抵扣新客额度、缓存命中、限时优惠。价格未知的候选在获得官方报价并写入价格快照前，不启动付费批次。

月成本分项：

`C = C_ASR + C_OCR/视觉 + C_音画融合/事实提取/分类 + C_HTML处理 + C_embedding入库及查询/重建 + C_300次问答 + C_重试/双轨/复核重跑`

每个文本/图片模型按 `输入token×输入价 + 输出token×输出价` 计算；视觉输入包括所有图片 token 和重复提示词；思考 token、分段重叠、失败是否收费按供应商实际账单确认。ASR 按上传总秒数，分片重叠和二次提交均计算。双轨不是统一乘二：分别累计第二 ASR、OCR/视觉、融合的实际单位用量；缓存复用只减去确实未调用的部分。超时但服务器已处理的调用要保守计提。

基础音频按 90,000 秒/月：Paraformer 全量为 7.20 元，Qwen3 文件 ASR 全量为 19.80 元；两路全部执行则 27.00 元，预留20%等价重试后32.40元，仅是 ASR 分项。有限问题样本双轨比例 `f` 时，额外费用为 `90,000×f×第二路单价`，不能假定只有低成本主路。

可核算的视觉示例：若每视频20帧，则6,000帧/月；**仅假设**每帧1,000输入token、200输出token，则600万输入+120万输出，Qwen VL Flash 短上下文价格约2.70元，OCR约2.40元，双路约5.10元；20%等价重试约6.12元。20帧及token数未实测，不能作为抽帧上限或质量依据。快闪文字可能需要多倍帧、裁剪与更高输入分辨率，费用按实际重算。

默认 DeepSeek 文本费用按实际输入/输出、峰时/非峰时及兑换币种核算；保守用未命中峰价，美元预算采用单独可配置人民币换算假设与汇率余量，不能把未经查询的汇率写成事实。为灵敏度计算，可用假设7.5元/美元（非实时汇率）：每100万未命中输入约2.25元，每100万输出约9元；正式人民币账单可取得时改用该价。HTML 长度和问答引用上下文尚未知，故尚不能宣称完整链路≤100元/月。

建议预研配额（总计100元，余额可在阶段内重新核算；每批需保留最大输出/重试上界）：

| 用途 | 上限 | 内容 |
|---|---:|---|
| 连通性/响应契约探测 | 5元 | 最小音频、图片、embedding；只确认能力与计费 |
| 音画开发集比较 | 35元 | 30开发视频逐步扩展，先小批消融，再扩大候选 |
| 音画锁定集验收 | 20元 | 最终配置20视频一次评测；留存机器原始结果 |
| 通过音画后检索实测 | 15元 | 3种embedding独立索引、60+20问答；含问答输出 |
| 失败重试/必要双轨/重跑缓冲 | 15元 | 不以自动无限重试消耗预算 |
| 未分配预留 | 10元 | 单价变化、输出增长和未预见调用 |

预留不保证全部实验可完成。每批计算 `已结算 + 未决调用保守上界 + 本批最坏成本`，超过总额100元或价格未知则不启动；达到阶段配额先评估候选淘汰与剩余工作。退款/免费额度只在账单确认后抵减。月目标同样需要包含分类、HTML、知识点生成、query embedding、问答、预期重试与索引重建摊销；若超出，回到方案讨论，不能静默降低质量或省略音画分支。

## 8. 尚未实测的状态与下一步

| 项目 | 文档核实 | 真实调用 | 质量验收 | 费用/资源验收 |
|---|---|---|---|---|
| ASR 三候选 | 部分已知；SenseVoice 时间能力不足 | 未执行 | 未通过/未测试 | 价格部分未知，未验收 |
| 视觉/OCR 三候选 | 已有官方输入与价格依据 | 未执行 | 未通过/未测试 | 图片及输出token未测 |
| embedding 三候选 | 已有官方规格 | 未执行 | 未通过/未测试 | 硅基单价待核实 |
| sqlite-vec/其他框架 | 仓库、stars与范围已核对 | 未部署 | 未通过/未测试 | 4C4G目标机未压测 |
| 完整月链路≤100元 | 仅分项估价与公式 | 未执行 | 不适用 | **尚未证明** |

当前无生产主/备方案。实验优先顺序：Paraformer作低价ASR基线，Qwen3文件ASR作对照；视觉比较 DeepSeek Flash、Qwen VL Flash，并以专项OCR检验密集文字增益；向量优先 text-embedding-v4 对比硅基 Qwen3/BGE。这个顺序可因最小探测失败或质量差异改变，不能写成已确定采购/接入选择。

下一轮严格按以下顺序执行：

1. 用户提供样本并人工确认事实标注，锁定开发/验收划分及价格快照、账号地域、密钥引用；不读取不必要的历史私密配置。
2. 最小能力探测确认图片真被模型读取、ASR时间戳粒度和单价、embedding长度/维度/usage。连通通过只解锁开发实验。
3. 在开发集分批比较ASR+视觉/OCR+融合及抽帧策略，保留消融、费用与错误类别；配置稳定后仅用锁定集验收音画，两个指标各≥98%。失败则停留本阶段。
4. 音画通过后，把原始证据文本与稳定片段ID用于检索实测，固定语料比较embedding和混合召回，再检验回答支持及无答案拒答；Recall@10≥95%且引用有效才解锁核心选型。
5. 目标服务器压测、完整月用量外推和故障恢复验收后，再冻结主/备与业务系统实现契约。备路也须测过，切换后的版本、成本和质量须可追踪。

仍需外部证据：实际视频/HTML长度和类型分布、人工真值、账号实际开通能力、硅基价格与限额、人民币支付币种、临时对象存储成本、ASR时间误差、抽帧视觉覆盖、问答token量、真实重试率、4C4G内存和40GB磁盘增长。没有这些数据，本文只能支持下一轮实验设计。

## 2026-11-05：已选方案迁入HTML业务链路

未新增候选或更换主模型。2C2b以已验证deepseek-flash、原来源忠实提示和16384输出上限处理原两份HTML；静态结构/SVG仅作文本，不执行脚本。新版本未继承旧评分，个人质量尚待本人；工程与费用/限制见[内容验收](phase-2-content-validation.md)。

## 2026-11-05：可选抖音适配器工程验证

沿用本地TokBrain的F2 0.0.1.7单作品接口，隔离依赖而不导入完整应用。未新增模型候选，未重写历史Star调研值。独立Python3.14离线构造/日志防护通过，未发请求；3.12和真实Cookie/下载仍待D05，见[专项分析](douyin-import-analysis.md)。
