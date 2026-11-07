# Phase 4 部署与维护约定

2026-11-06。本人确认本次视觉OK并授权Phase 4；[先行用例F401–F416](phase-4-test-cases.md)。本文件描述实施约定，不代表已在服务器执行。

## 已确认与实施选择

- 使用现有域名的独立二级域名，暂定`kb.yuanzhll.top`，沿用服务器Nginx；官网及小程序保持原配置/数据库。需要用户添加该子域DNS记录并配置独立证书，不要求更换根域站点。
- 继续由用户自行运行交付脚本、回传JSON。此次授权包括实现和准备部署，不等于已经取得服务器访问或已经修改Nginx。
- 迁移现有业务资料。当前运行配置为`reports/phase2-content-20261105-07d9f46d/web.json`，数据在同目录`data/`，不是默认`data/workflow`。只读核验当前4来源、6版本、5审核、4已完成任务，其中3份本人99/100/100批准；保留工程测试HTML的未批准状态。
- 备份配置支持`manual`和`oss`。前者生成独立转移包，由本人下载；后者是阿里云私有OSS备份适配，需单独存储凭据/私有Bucket和前缀。默认manual，不开通服务、不自动上传。它与ASR音频临时上传/正式OSS开关相互独立。

## 进程、目录与网络

生产Compose使用同一镜像的Web及单独worker；Web明确关闭内嵌dispatcher，worker复用已有持久派发和execution_guard，不引入Redis/Celery。现有本机开发模式仍保留内嵌单worker，兼容已有操作。

目标为Linux host网络且Web只绑定`127.0.0.1:8768`，由同机Nginx代理，worker不监听端口；不新增监听80/443的容器或接管其他服务。Host网络共享主机网络命名空间，安全边界来自回环绑定、应用认证和主机现有访问控制，不能把它称作容器网络隔离。[Docker官方边界](https://docs.docker.com/engine/network/drivers/host/)

| 容器路径 | 内容/权限 |
|---|---|
| `/app` | 只读代码及干净前端构建，不含历史真实评分页 |
| `/app/config` | 外置公开配置，只读挂载；不得放API Key/密码 |
| `/run/secrets/personalkb.env` | 单独私密挂载，账号、密码哈希及模型/存储凭据引用；不打包 |
| `/state/workflow` | SQLite、长期Markdown、证据/帧、保留期内媒体及索引 |
| `/state/budget.sqlite` | 所有模型共用的累计预算/未决预留账本，迁移和备份必须包含 |
| `/app/tmp` | 自有临时上传/解析工作目录挂载，不与宿主系统tmp混用 |
| `/backups` | 与数据目录分离的快照对象库；同盘可用但不代表外部灾备 |

配置与容器资源有说明、端口可调；资源限制只约束本应用，不保证整机小于3GB，仍须目标机业务共存实测。

## 认证与会话

原本机`GET /api/session`不是生产登录。新增单用户密码登录/退出，密码只保存哈希，秘密从私密文件或环境读取。生产配置缺少认证或HTTPS精确域名时失败关闭，不把开发匿名会话带到公网。

生产会话使用随机服务端ID、明确期限、登录轮换、退出失效以及`Secure/HttpOnly/SameSite=Strict`；写操作保持CSRF及Origin校验，登录与API有限速。服务重启后重新登录，不恢复浏览器费用同意或自动重发任务。`Secure`限制Cookie仅通过安全连接发送，属性本身不能代替TLS。[Starlette Cookie说明](https://starlette.dev/responses/)

只公开登录前必须的应用入口及该入口实际引用的编译JS/CSS；历史评分页、原HTML、媒体、证据等均属于受保护资料。代理标头只信任同机回环来源，不能信任任意请求的转发标头。[FastAPI代理信任说明](https://fastapi.tiangolo.com/advanced/behind-a-proxy/)

Nginx独立虚拟主机配置包括上传大小、请求体/响应超时及事件流关闭代理缓冲；不把proxy_read_timeout误当总任务时限。[Nginx官方代理语义](https://nginx.org/en/docs/http/ngx_http_proxy_module.html)

## 冷备份、恢复与视频保留

生命周期锁分别保护Web/worker，维护同时取得两把锁和既有执行锁。每日维护窗口短暂停止本项目服务，先备份再做保留清理，失败恢复此前运行状态；不会停止网站/小程序。此为停写快照，不宣称多个文件及预算库在线原子备份。SQLite文件通过backup API生成一致性副本，不直接复制正在写入的数据库主文件。[Python SQLite备份接口](https://docs.python.org/3.12/library/sqlite3.html)

长期文件使用内容SHA去重对象、每日manifest、7代快照；完整校验后原子发布。恢复只到独立空目录，先验证全部路径/哈希，再恢复数据库、审核、文件与账本；拒绝符号链接、穿越与覆盖已有库。秘密不随资料包迁移。

手动导出包可在外部保留；同盘未下载副本不能当外部备份通过。OSS仅写专用私有前缀、HTTPS和显式私有对象，上传结果与本地快照分别记录；失败不删本地副本，不自动清理远端Bucket其他对象。对象ACL可以覆盖Bucket ACL，因此不能仅凭Bucket私有就忽略对象访问级别。[OSS对象ACL说明](https://www.alibabacloud.com/help/en/oss/developer-reference/manage-object-acls-1)

默认仅清理成功、超过7日、永久证据校验通过且无活动/未知远端任务的原视频，先dry-run再apply并留清理记录；失败/待恢复素材列为需人工处理，不自动销毁。长期HTML、Markdown、证据/帧不删，不按mtime递归删除video-work。原片过期后页面给出说明，RAG仍使用永久证据。

## 迁移和剩余验收

实际数据很少，迁移主要是停写导出、传包和空目录恢复，不需更换格式或重评。索引空间包含数据库/内容绝对路径，因此服务器路径变化后旧索引不能当成ready；保留原批准，显式同意后重建向量，发生的费用记原账本。

本机验证负责认证、维护、迁移和配置逻辑；目标Linux仍须镜像构建/启动、真实HTTPS登录、受控素材端到端、任务硬中断/恢复、资源与网站共存、手动或OSS外部备份及独立恢复。缺少目标报告时不宣布Phase 4整体通过。正式OSS ASR仍按本人既有C02手动切换，日常月费仅观察，不恢复为硬验收指标。
