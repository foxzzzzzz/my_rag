# Phase 2B 视频处理与恢复契约

日期：2026-11-04；本轮在2A之上新增显式视频命令，不修改旧worker的离线默认。只处理已导入来源；不开发Web或正式检索。

## 模块与接口

`VideoJournal(store)`位于`personalkb/video_journal.py`，与WorkflowStore使用同一SQLite，创建独立`video_runs/video_stages/video_assets`表，不重写旧表。所有worker修改调用store._lease同事务校验，终态清理走独立claim保证没有其他running任务。

- `bind(task_id, token, fingerprint)`：绑定不可变方案指纹；更改报错。
- `stage(task_id, name)`返回row或None（row.result解析JSON）；`begin(task_id,token,name,input_sha256)`写prepared；`mark_started(...)`写in_flight并标任务external_started；`save_remote(task_id,token,name,remote_task_id)`存远端ID并调用等价checkpoint；`complete(task_id,token,name,result)`保存确定JSON与SHA，状态completed；重复完成仅相同内容幂等。
- `list_stages(task_id)`安全状态不含原结果/URL；`resume_claim(task_id,worker_id)`只对needs_attention且未删除、无其他running授权显式恢复，不能突破POST不确定状态的业务检查；计数/令牌继续留痕。
- `register_asset(task_id,token,metadata)`：独立asset_id/backend/object_key/source_sha256/size_bytes/model/expires_at和scope(bucket/endpoint/region/prefix)；不得存file_url/签名URL。`assets(task_id)`仅内部获取；`asset_terminal(task_id,token,asset_id)`远端任务已终态可清理；`mark_cleaned(asset_id,status)`仅在清理claim内使用。
- `cleanup_claim(task_id)`上下文：检查本任务不running且没有别的running，临时数据库maintenance锁与claim协调；`cleanup`只清理remote_terminal的持久对象；完成任务默认执行一次，失败显式再执行。公开status只返回asset_id/backend/状态，不含object_key。

为维护全局单任务，新增maintenance锁必须同时让WorkflowStore.claim拒绝维护期间领取；采用共享SQLite表、互斥事务更新，不用进程内锁替代。操作lease到期后旧worker不得注册、完成或清理。

`create_storage(..., ownership=None)`新增可选回调用于正式OSS在PUT前持久登记。ownership提供`register(metadata)`、`owns(asset)`、`deleted(asset)`，由编排器绑定任务/令牌和scope。无回调保持原2A适配器离线契约；有回调则跨实例cleanup仅在账本身份/scope核实后允许，不提供任意路径restore接口。

`personalkb/video_services.py`提供`ProviderClient(model_config, pipeline_config, secrets, transport=None)`：`submit_asr(asset)`→task_id；`query_asr(task_id)`→output dict；`download_asr(url,audio_seconds)`→{text,segments,...}；`vision(image_path)`→{content,model,usage,estimated_cost_cny}；`summarize(body,title)`→{content,structured:{summary,notes},model,usage,estimated_cost_cny}。无内置重试/预算；API请求由编排器先写阶段及预留。transport.request(url,key=None,payload=None,headers=None)返回(status,dict)，HTTPS/主机白名单/禁跳转/大小限制/安全错误；下载OSS不带Bearer。

`personalkb/video_media.py`提供`prepare_media(source_path,work_dir,workflow_config,pipeline_config,*,heartbeat)`→{audio_path,audio_seconds,duration_seconds,frames:[{index,seconds,path,sha256}]}。引用既有demo策略配置，SHA命中的3个demo沿用profile，其余用显式default_profile。全长音频/时间覆盖、线程限制、资源保护、可中断heartbeat与独占路径；原件不变。日志不输出原始ffmpeg stderr。

`personalkb/video_pipeline.py`提供`load_pipeline_config(path=None)`、`run_video(workflow_config,pipeline_config,secrets,*,task_id=None,resume=False,services=None,media=None,storage=None)`和`cleanup_video(workflow_config,pipeline_config,secrets,task_id,*,storage=None)`及`video_status(...)`。依赖可注入，fake不标provider实测；实际返回WorkflowStore.finish的待审version，异常安全进入failed/needs_attention。

## 费用和持久化顺序

处理参数存于`config/video-pipeline.json`，引用现有models、策略及存储配置。stage输入SHA绑定内容/参数与图像SHA。预算沿用`tools.api_smoke.reserve`和既有累计账本，不创建绕过历史预留的新研究额度；研究上限硬约束100元，单次video运行上界外置。保留request_id关联、usage/已知估算及未知状态，不擅自释放预留。

顺序为prepared→原子预算预留→持久in_flight→POST→持久结果。prepared恢复可核对同request_id的既有预留继续；in_flight且无可查询ID必须停止。ASR若已保存ID仅查询，结果下载成功后complete再登记对象remote_terminal。chat completed后才视为可复用。资源保护、本地准备失败不发POST。原始HTML/文本中的指令作为材料，不执行。

私有签名URL只在调用内存中，不写公开状态、报告、阶段result或日志。正式对象归属元数据在私密DB中；清理必须与创建时scope完全匹配，不因当前配置改变而跨桶删除。临时文件上传不能主动删除，由供应商48h清理；无查询接口不伪造主动删除结果。
