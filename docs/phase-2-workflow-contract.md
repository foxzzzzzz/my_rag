# Phase 2A 后端流程契约

日期：2026-11-04；实施范围：标准库SQLite持久领域层、文件导入、单worker、CLI；Web API/React、抖音链接下载、自动视频模型链路、RAG索引和云部署后续实现。本轮不新增联网依赖或模型费用。

## 数据与状态

`sources`保存稳定ID、kind、原件SHA、受控blob相对路径、当前版本、删除状态；`tasks`保存来源、状态、尝试次数、租约/令牌、当前阶段及远端task_id；`versions`保存不可变完整结果JSON与SHA、机器/人工类型和父版本；`reviews`保存服务端追加顺序、版本/SHA/决定/分数及人工说明。各表保留创建时间，任务另保留更新时间；当前stage/error及尝试计数不是完整事件日志。初始导入的来源与任务在一个SQLite事务内登记，重复按kind+原件SHA去重。

任务状态：queued → running → succeeded/failed/needs_attention/cancelled。全局只运行一个任务；令牌检查与写入在同一事务内，租约到期的旧worker不能发布。外部请求开始标记必须先持久化；无结果的外部提交过期只转needs_attention，不自动重发。需要人工介入的任务不走普通重试。失败/取消仅显式重试，并受尝试次数配置限制。

版本JSON至少包含title、body、summary、notes、evidence、provenance、scheme_id、scheme_version和output_kind。证据保留真实原文/时间信息。机器输出只接受local_extraction/provider，人工修订使用human_edited；simulation/空输出不能发布。审核绑定version_id+内容SHA，只允许当前未删除版本；同review_id相同内容幂等，冲突拒绝。当前版本最新审核为approve且分数达到目标才是正式知识资格。没有实际向量索引，资格不称为RAG已经写入。

长期Markdown通过不可变版本导出；原始结果JSON与原件保留，数据库是当前有效版本/审核的索引与事务边界。本轮先实现安全导出，不把派生文件写入和SQLite跨介质事务等同数据库原子性。后续Web/索引只可读取统一资格查询，禁止绕过审核表。

## Python领域接口

`personalkb/workflow_store.py`提供`WorkflowError(code)`和`WorkflowStore(db_path, *, quality_target=98, lease_seconds=300, max_attempts=3, busy_timeout_seconds=5)`。数值来自外部配置，构造器默认仅供嵌入兼容。

- `import_source(kind, sha256, original_name, blob_relpath)` → `{source, task, duplicate}`，dict行包含ID；重复软删除来源报`source_deleted`。
- `get_source(id)`、`get_task(id)`、`list_sources()`、`list_tasks()`、`get_version(id)`、`list_versions(source_id)`读取记录。
- `claim(worker_id, now=None)` → task或None；返回任务含`lease_token`。`recover_expired(now=None)`安全处理过期；`heartbeat(task_id, token, now=None)`续租。
- `checkpoint(task_id, token, stage, *, remote_task_id=None, external_started=False, now=None)`；外部开始标记不可撤销，远端ID不可换绑。
- `finish(task_id, token, result, now=None)` → version；`fail(task_id, token, code, *, needs_attention=False, now=None)`；`cancel(task_id)`；`retry(task_id)`。
- `revise(source_id, expected_version_id, result)` → 新人工version，乐观冲突检查；`review(source_id, version_id, content_sha256, score, decision, reviewer, *, review_id=None, note='', tags=None)` → 记录。
- `eligible_sources()`、`delete_source(id)`。删除保留历史，取消未完成任务；不自动恢复删除来源。

每次操作独立连接/事务，不让调用方持有未提交事务；时间可注入测试。result采用确定JSON编码计算内容SHA。读函数未知ID返回安全错误，JSON已解析结果通过version.result返回。

## 导入、worker与命令

`config/workflow.json`管理数据目录、上传大小、磁盘保护、质量目标、租约/次数、HTML编码和worker方案；相对路径相对于项目根目录。文件以内容SHA寻址放入`data/.../originals/`，原名仅元数据。只处理显式传入的本地文件，不自动扫描导入全部sources。

worker的`run_once`原子claim并调用handler；HTML走不执行脚本的真实本地提取，结果只称正文预览摘要而非AI摘要。视频支持显式提供已验证预研bundle，校验原件身份、完整输出和provider来源后接入，不继承旧评分。无handler或无真实结果显式失败。处理过程不自行读取.env、联网或自动调用模型。

CLI最少包括init、import、work-once、tasks、sources、show、review、revise、cancel、retry、delete、eligible、export；输出JSON。执行评分是用户明确操作，不自动评分；导出Markdown用安全生成名且检测版本SHA，不执行源内容。CLI使用与领域层同一质量配置。
