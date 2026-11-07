# Phase 3正式索引与问答契约

日期：2026-11-05；PRD v0.17；测试见[R01–R20](phase-3-rag-test-cases.md)。沿用已选SQLite FTS5 + sqlite-vec0.1.9/RRF、标题边界1000字符/120重叠、text-embedding-v4/1024、deepseek-flash关闭思考。所有可调参数和提示词外置config/rag.json，中文说明、价格日期和调用上限保留。不新增第三方服务Key。

## 实现接口与职责

- `personalkb/rag_index.py`：`RagIndex(store, config, provider=None)`；`load_rag_config(path=None)`统一校验配置；`build(allow_paid=False, request_id=None)`、`query(question, filters=None, allow_paid=False, request_id=None, mode=None)`、`status()`、`validate_citations(citations, filters=None)`、`citation(chunk_id)`。query返回检索候选list，每项至少chunk_id/source_id/version_id/content_sha256/space_id/text/locator；validate失败抛安全WorkflowError。可增加纯内辅助函数，不改既有研究代码或评分。
- `personalkb/rag_provider.py`：`RagProvider(store, config)`提供`embed(texts, *, allow_paid=False, request_id=None, run_id=None)`→`{vectors,model,usage,...}`、`answer(messages, *, allow_paid=False, request_id=None, run_id=None)`→`{content,model,usage,...}`。方法懒加载Key、保守预算和持久请求；测试注入同接口假provider。config由index层统一loader验证；provider构造本身不联网。
- `personalkb/rag_answer.py`：`AnswerService(store, index, config, provider=None)`；`ask(question, filters=None, allow_paid=False, request_id=None, mode=None)`返回answer/citations/insufficient_evidence等；`stream(...)`产生dict事件。引用由服务端本次检索结果构造，模型只返回answer/citation_ids/insufficient_evidence，不能自报定位或权限。
- Web适配器复用WebService/现有会话CSRF，可注入rag_provider_factory；GET `/api/rag/status`、POST `/api/rag/build`、POST `/api/rag/search`、POST `/api/rag/ask`、POST `/api/rag/stream`（SSE）、GET `/api/rag/citations/{chunk_id}`。build/search/ask/stream含allow_paid及request_id；search范围为sources/topics/tags ID数组；用户选纯词法时明确mode=lexical，默认hybrid不静默降级。

## 正式资格与索引版本

正式入口必须拒绝无长期存储的store，不能利用eligible_sources在content_root=None时的兼容分支。调用eligible_sources并冻结当前source/version/SHA、最新review身份、证据与文件校验；只读真实资料仍待审，不自动approve或沿用预研分数。

generation库与工作流库隔离，manifest包含空间指纹及来源快照；空间至少绑定工作流DB/内容根身份、provider/base URL/model/显式revision/维度、分块/tokenizer版本及参数。构建用staging、全部写入并复验后ready，原子切换active；失败保留旧active。构建外部API期间不持业务事务，发布须在同一业务快照内复核，不能复验后又留下可竞态发布窗口。

所有公开查询都先按业务资格/当前文件校验排除失效来源，再排名/截断；旧版本/撤审/删除/损坏立即逻辑失效，不能依赖清理任务才安全。同步或查询前维护须删除失效正文/FTS/vec，不能只删展示字段；重建和增量维护不能调用reconcile自动覆盖坏文件。分类从业务当前稳定ID读取，过滤必须在范围内召回。改变空间后只允许显式重建，不混用相同维度的其他模型向量。供应商别名可能滚动，配置revision只是本地冻结标识，不声称权重不可变。

## 证据与回答安全

人工修订正文/转录/视觉时，新版本需同步对应引用证据；旧原始证据保留在父版本，不能通过简单保留旧evidence使修正不进入检索。若正文作为完整证据被改写，使用标明人工修订的正文证据，不能沿用旧片段时间；单独修订transcript/visual只替换对应证据。摘要/笔记/标题仅导航变动不改原始事实证据。人工文本可按新版本evidence_index与字符范围引用，视频时间不可验证时明确“无可验证时间”，不伪装原始ASR或帧证据。这属于用户批准的人工版本，不是模型代评。

分块优先原始evidence/body/transcript，不以notes/summary充作来源原文。HTML现有static-extraction可精确定位到不可变版本evidence_index及字符offset/end，不编造DOM锚点。视频audio已有start/end，visual只有seconds/image_sha256时保留点证据；旧整段转录仅在能解析真实时间戳时给精确时间，否则排除精确引用或明确不可定位。

同一回答的全部候选上下文在检索后、模型前后、发正文前再次验证资格/内容/过滤快照，包含最终未被模型引用的项。模型完整返回后校验结构、正文引用ID与citation_ids一致、ID属于本次候选；无答案只返回配置的拒答说明及空引用，不把候选当有效引用。代码校验不能证明语义完全正确，真实回答仍需本人检查。

2026-11-06真实联调补充（PRD v0.19/L09–L10）：片段引用标识为完整64位十六进制，`[sandbox]`/`items[0]`等技术正文仍为普通文本。insufficient_evidence=true且基础字段结构/类型正确时，忽略模型正文和所附引用，直接收敛为固定拒答/空引用；原始响应保留在请求缓存并记录协议偏差，不把这种收敛称为模型协议通过。非拒答仍严格检查未知ID/引用集合。生成前后对全部上下文的资格检查保持，不能用拒答绕过撤审/损坏保护。

首版事件流只先发progress，完整回答缓冲且验证后发answer，再复验后发done；失效发invalidated并让UI清空正文/引用，不能展示已经无资格的最终答案。此为安全事件流，不是上游逐字token实时透传；不声称能撤回已经送达给客户端的字节。不得为整个远端生成锁住审核/删除的业务写事务；仅实际处理资源受execution_guard保护。

引用打开必须再次验证当前资格/空间/版本/证据；HTTP409/410不带失效原文。视频引用可打开既有原件播放并定位确实存在的时间，HTML显示版本证据摘录。所有模型文本转义，不运行HTML/JS或检索材料中的指令。

## 付费与恢复

build、query embedding、answer分开明确成本与预留；同一run_id下阶段request_id分离，共用研究账本总100元。无合格材料/无上下文时不调用模型；status/引用纯读取免费。request先持久prepared/预留/in_flight，再唯一一次POST，已知有效usage按配置价格结算、缺失或未知保留预留，失败不自动重发；同request_id不同输入/空间配置拒绝，已完成缓存也不能绕过当前资格。

实际处理遵守execution_guard，未知POST不能随便重试；任何服务失败不自动更换模型、降低维度、切空间或切词法。纯词法是用户显式选项，不能冒称混合检索。请求/响应体、提示、向量/批大小、构建最大块数、超时/价格/预留/流事件限制外置。API不输出Key、原始异常、私密绝对路径；模型配置引用保留请求与返回model及指纹。
