# Phase 2C1 网页流程与接口契约

## 2026-11-05 补充：2C2a/b（PRD v0.12）

- GET `/session` 新增公开配置 `live_html_enabled`；仅开关，无Key/服务凭据。
- POST `/tasks/{id}/start|resume|retry` 支持 `processing_mode: "preview" | "model"`；默认preview（retry未指定时保留已记录模式）。model要求HTML开关和`allow_paid:true`，意图持久保存，不因重启改为另一模式。未知同步POST不自动重发。
- POST `/sources/{id}/process` 请求 `{expected_version_id,allow_paid:true}`，仅HTML；原版本存在、无活动/未知任务且版本一致时，在同一事务创建新的model任务和派发。无新评分，旧任务不复活。
- 来源摘要新增 `content_status`；只有当前批准且长期内容校验通过才返回`eligible:true`。详情`processing`采用白名单，包含模式、模型、用量和估价等；任务`dispatch.processing_mode`展示持久模式。多次处理时取最新任务。
- 帧接口优先读取永久附件并核对内容同步与SHA。显式补建旧数据、恢复边界及配置见[内容说明](phase-2-content-guide.md)。
- CLI与网页共用Markdown渲染，下载是审核状态快照；持久版本正文不随评分变化，当前note.md随状态变化。正式ZIP与重传协议仍待2C2d。

以下保留2C1历史契约，以上补充优先。

日期：2026-11-05；PRD v0.11。FastAPI提供同源JSON API与构建后React/Vite静态文件。单个后台线程消费持久web_dispatch，继续使用2A/2B同一SQLite、租约及审核条件；不引入Redis。原CLI不变。

## 本轮范围

网页本地HTML/MP4选择或拖拽导入、明确开始处理、任务进度与安全错误、笔记/转录/帧/原片证据查看、人工评分/批准/返工/拒绝、人工修订、撤回、删除与单篇Markdown下载。本轮2C1完成后仍须2C2主题标签/批量管理、附件打包及Obsidian重上传冲突；不提前进入Phase 3。抖音链接下载/账号入口另列待办，本轮不假装已实现。

## API

所有路径以`/api`开头。JSON错误`{error:安全码}`，验证400/422、无会话401、CSRF/Origin403、未知ID404、版本/状态冲突409、大小413、资源/能力不可用503。无堆栈、密钥、签名URL及lease令牌。API使用会话Cookie；写入请求必须有`X-CSRF-Token`及可信Origin（无Origin的本地客户端仍需CSRF）。

| 方法/路径 | 请求 | 返回 |
|---|---|---|
| GET `/session` | 无 | `{csrf_token,config:{quality_target,poll_interval_ms,max_upload_bytes,max_html_bytes,live_video_enabled}}`，设置HttpOnly/SameSite Cookie |
| GET `/sources` | 无 | `{items:[来源摘要]}`，摘要含id/kind/original_name/current_version_id/created_at/deleted/status/eligible |
| PUT `/imports?filename=...&rights_confirmed=true` | 原始文件字节，不用multipart；流式限量 | `{source_id,task_id,duplicate,name,kind}`；只登记不自动启动 |
| GET `/sources/{id}` | 无 | `{source,current,versions,review,task,eligible,frames,original_url}`；current为含result的版本，versions为历史元数据，review为当前版本最新审核或null |
| GET `/tasks` | 无 | `{items:[安全任务]}`；含id/source_id/status/stage/error_code/attempts/created_at/updated_at/progress |
| POST `/tasks/{id}/start` | `{allow_paid:boolean}` | 持久派发确认；视频明确true且服务启用才可派发 |
| POST `/tasks/{id}/resume` | `{allow_paid:true}` | 显式恢复派发，不重新提交未知POST |
| POST `/tasks/{id}/cancel` | `{}` | 安全任务；旧worker不能发布 |
| POST `/tasks/{id}/retry` | `{allow_paid:boolean}` | 先领域安全retry，再明确派发；不能绕过external_started |
| POST `/sources/{id}/reviews` | `{version_id,content_sha256,score,decision,reviewer,review_id,note,tags}` | `{review,eligible}`；使用store.review，不复制预研反馈批准 |
| POST `/sources/{id}/revisions` | `{expected_version_id,title?,notes?,summary?,body?,transcript?,visual?}` | 新version；完整原result合并允许文本，human_edited，新版无评分 |
| DELETE `/sources/{id}` | 无 | 领域软删除 |
| GET `/sources/{id}/original` | Range可选 | 视频同源播放；HTML附件下载+禁止脚本策略 |
| GET `/sources/{id}/frames/{index}` | 无 | 本任务manifest及产物SHA核对后的JPEG，无任意路径 |
| GET `/versions/{id}/export` | 无 | attachment Markdown；无写磁盘派生副本，含稳定ID/版本/SHA/审核状态 |

所有文本由React文本节点/textarea/pre展示，禁止dangerouslySetInnerHTML。score不接受bool/NaN/空值，低分approve由前后端同时拒绝。review_id每次明确提交生成，网络重试复用；冲突提示刷新，不能自动覆盖。编辑保存与评分分开；保存后必须看新版本再评分。

进度仅报告已知信息：视频阶段表完成数、帧完成数/manifest总帧，HTML显示提取阶段。未知总量为null；未完成不以百分比冒称完成。只用于查看，不用轮询触发模型。

## 领域服务接口

`personalkb/web_service.py`提供`WebService(workflow_config,pipeline_config,web_config,*,video_runner=None)`：`.store`、`sources()`、`detail(source_id)`、`tasks()`、`enqueue(task_id,mode='run',allow_paid=False)`、`process_next()`、`start()`、`stop()`、`review(source_id,payload)`、`revise(source_id,payload)`、`original(source_id)->(Path,kind,original_name)`、`frame(source_id,index)->Path`、`export(version_id)->(bytes,filename)`。所有返回公开字典经过字段白名单。process_next便于隔离测试；video_runner默认调用2B，只有实际视频运行才读取配置指定.env。

web_dispatch同任务只一条当前意图，保留mode/run或resume、state、请求时间、领取时间/owner。enqueue不消耗模型额度；process_next先核对任务/来源和领域全局锁，再调用2A指定HTML任务或2B指定视频任务。不扫描所有queued任务自动收费。崩溃的派发仅在等待超时且领域仍queued时安全重排，远端未知保持needs_attention并等待显式操作。服务关闭使自身活动任务停在可诊断状态，不擅自取消其他CLI任务。

2A新增可选指定task_id执行入口，避免HTML处理误领取用户尚未确认的视频；旧参数行为兼容。Web启动单进程单worker，第二实例由SQLite全局租约防止重复处理。

## 配置与本地安全

`config/web.json`外置host=127.0.0.1、port=8765、允许Host/Origin、会话TTL/数量、JSON限量、上传分块/总量保护、UI轮询与display_timezone、派发轮询/恢复延时、shutdown超时、启用视频、workflow/pipeline/env路径、frontend_dist。默认不绑定公网；本机会话+CSRF不是正式单用户认证，不宣称可直接公网生产。Phase 4仍需登录/HTTPS、反代及真实服务器验收。

原始HTTP字节逐块写到根tmp/web-uploads的本次UUID临时文件，先授权/声明大小/格式/磁盘预检，再流式计量；临时名保留验证用扩展名，展示原名另传metadata。上传结束调用既有import_file完整校验，finally仅删除本次临时文件。请求中断、超限、DB失败按2A原则处理，不自动清理其他任务。
