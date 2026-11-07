# Phase 4 本机实现与部署交付验证

2026-11-06。本人已批准视觉并授权Phase 4，**4A–4C本机实现及交付验证完成，4D目标服务器验收待执行；Phase 4整体尚未通过。** 域名暂定kb.yuanzhll.top，沿用现有Nginx，本人自行执行脚本回传报告。

## 实现与测试

### 2026-11-07 云端索引与三题问答本人确认通过

本人回传云端索引重建成功，OpenManus/smolagents两题回答及引用正常、无依据问题正确拒答。据本人观察关闭当前三份资料云端索引与问答分段，不外推全部问题或模型稳定性；尚未提供新块数/用量文件，不沿用旧214作为新构建实测。后续预算为原账本增量结算，不再要求198条SHA不变。

接续优先执行无retention/无上传的operate.sh backup，确保真实模型操作后的工作流与账本可冷备，再验证snapshot、独立恢复与manual外部副本；当前未实际执行。真实新导入、负载共存、硬中断、每日调度与外部恢复门槛仍未通过，Phase4整体保持待验。

### 2026-11-07 部署与资料迁移分段验收通过

本人回传APPROVAL_AND_BUDGET_OK：当前版本批准99/100/100，预算198行及与原迁移包逻辑行SHA一致；本人网页登录核对正文/审核正常。结合已归档认证passed、4来源3合格和目标机恢复/健康证据，部署与资料迁移分段通过，原批准和预算连续性保持。

云端索引仍ready=false/needs_rebuild=true。下一步只读检查配置模型/凭据存在性/费用上限，真实构建由本人页面本次费用同意显式触发；未执行真实模型调用，不能提前宣告问答/完整Phase4通过。

### 2026-11-07 09:54目标机认证复验passed

已读取并归档[本人认证报告](../reports/phase4-server-20261107/cloud-phase4-auth-ragfix-20261107-095403.json)，result=passed，原RAG503已恢复200，来源4、合格3；登录隔离/安全Cookie/CSRF/退出均通过。索引ready=false、needs_rebuild=true，保留旧3来源214块，符合路径变化后需显式重建的预期，不代表检索可用。磁盘剩13,185,523,712字节，报告闲置内存使用1,345,978,368字节；未进行负载采样，不能作为负载资源门槛通过。

主代理从原迁移包预算只读计算reservations=198及逻辑行SHA基准，准备目标机只读核对原账本连续性和99/100/100批准；这些补充检查、本人浏览器体验及后续真实模型/资源/中断/外部备份仍待证据，Phase 4整体未通过。

### 2026-11-07 认证通过项与RAG配置503修复

本人回传cloud-phase4-auth-20261107-093057.json：未登录401、登录200、三个Cookie安全属性、登录后session200、来源接口200/4条、缺CSRF退出403、合法退出200、退出后401全部通过；仅rag_status=503导致整体failed。未配置历史路径，资源采样/真实模型/中断/外部恢复未执行。

定位configure将env_file/budget.ledger重写为Linux绝对路径，但load_rag_config旧规则禁止绝对路径，Linux抛invalid_config并映射503；本机Windows的Path('/state/...').is_absolute为false使此前加载测试漏检。按RP01–RP04只允许这两个受信任本地配置路径使用绝对路径，以PurePosixPath/PureWindowsPath拒绝越界/UNC，index_dir/models_file继续相对约束。无请求层权限/模型/预算改变。

定向RAG及部署64 passed、1 skipped（平台symlink）、1既有弃用警告，见tmp/rag-production-path-pytest.log；新增热修复Dockerfile模板仅从指定本地基础镜像COPY rag_index.py，无RUN或依赖变化。交付personalkb-deploy-20261107-ragpathfix1.zip，服务器先基于已建personalkb:local生成独立tag并离线加载公开配置，当前服务保持；通过后才备份镜像tag、切换本项目Web/worker。修复镜像未在本机Docker执行，生产RAG恢复待回传。

### 2026-11-07 目标机恢复、启动与HTTPS健康实测

本人已回传独立空目录恢复4来源/6版本/5审核/4任务、预算账本完整性及RESTORE_OK，随后DATA_PLACED_OK、ready=true及两容器启动。09:27北京时间回传两容器Up 2 minutes、仅回环127.0.0.1:8768监听；正确Host/HTTPS代理头的回环healthz和真实HTTPS healthz均HTTP200及ok:true，后者经Nginx且未绕过证书校验，含CSP/nosniff/no-store。先前直接回环IP检查所致400已解释并纠正，未改安全策略。

至此目标机镜像构建、空目录恢复、数据放置、独立Web/worker启动与HTTPS健康已获实际回传；认证报告、登录后的资料/3份本人批准与预算连续性、显式费用同意后的真实链路/索引、资源共存/中断及外部恢复备份仍待验，Phase 4整体未通过。

### 2026-11-07 buildfix2实际构建完成、后续pip构建源优化

本人截图回传buildfix2成功输出BUILD_OK，镜像ID `sha256:cde7b9f209fdd21a1f3070ab65a9783b699a0becba0acc03efe2be427f228f663`，SizeBytes=275589548，磁盘约13GB可用；实际构建已通过，未等同于启动或迁移验收。pip安装阶段耗时4245秒，用户授权后续仅改Docker构建pip源。

按BF07–BF09，新增外部`config/pip-build.conf`，使用[TUNA官方PyPI索引](https://mirrors.tuna.tsinghua.edu.cn/help/pypi/)；Dockerfile仅在依赖安装RUN内export PIP_CONFIG_FILE，三个pip命令及版本约束/no-deps保持，不添加ENV/主机或镜像全局pip配置。部署18项、前端42项通过，配置/作用域与包内容为静态回归，未实际构建buildfix3镜像。发布buildfix3为后续备用，当前app-buildfix2/已建镜像继续迁移。资料恢复/生产放置/启动及完整4D验收仍待回传。

### 2026-11-07 Docker内国内Debian源（buildfix2）

本人确认buildfix1 APT下载持续慢速后，授权仅修改本项目镜像内Debian源。按BF04–BF06新增外部`config/debian.sources`，使用清华TUNA主仓库及安全更新HTTPS镜像；固定bookworm/bookworm-updates/bookworm-security、main组件、官方Signed-By，保留TLS/包签名验证。Dockerfile仅在Python阶段apt之前复制此文件，部署包白名单增加.sources；未改Compose、宿主机软件源、Docker daemon、npm/pip源或其他业务。安全更新镜像存在同步延迟可能，参考[TUNA文档](https://mirrors.tuna.tsinghua.edu.cn/help/debian-security/)。

新增源配置解析、官方签名、Docker复制顺序与包内配置回归，部署17项/前端42项通过、隔离Vite构建成功；日志`tmp/buildfix2-pytest.log`、`tmp/buildfix2-frontend.log`、`tmp/buildfix2-build.log`。发布独立命名`personalkb-deploy-20261107-buildfix2.zip`；原迁移包保持，云端代码改从app-buildfix2执行。无本机Docker，未实际执行镜像构建/容器APT；目标机下载速度、最终镜像及后续迁移仍待本人回传，不宣称Phase 4通过。

### 2026-11-06 首次服务器构建失败与buildfix1

本人确认原部署/迁移ZIP SHA一致、state/workflow、state/budget.sqlite及restored均ABSENT，Compose检查通过。实际Docker构建在Vite阶段报`../../config/citation-display.json`缺失：原Dockerfile将web平铺到/build，且未把共享config复制到前端阶段。

按实施前BF01–BF03，修复前端工作目录为/build/web，将共享配置复制到/build/config，并将最终阶段产物复制源改为/build/web/dist。后端/生产配置/业务逻辑不变。新增持久回归测试按实际Dockerfile的WORKDIR/COPY映射文件，验证两个共享JSON引用和最终dist路径；旧布局检查失败，新布局通过。隔离模拟构建旧布局失败、新布局Vite成功（33 modules）；前端42项通过、部署16项通过。日志：`tmp/buildfix1-old-test.log`、`tmp/buildfix1-isolated-build.log`、`tmp/buildfix1-frontend-test.log`、`tmp/buildfix1-pytest.log`。初次系统Python缺fastapi的2项失败已使用既有tmp/web-deps重新执行通过。

交付独立命名`personalkb-deploy-20261106-buildfix1.zip`及SHA；保留原包，原迁移包保持。服务器解压到同级app-buildfix1，沿用已有config/state/secrets/backups，再check/build。本机无Docker，只验证隔离目录布局与前端构建，未声称Linux镜像通过。尚未执行云端恢复/启动/登录，Phase 4仍待验。

先行[F401–F417](phase-4-test-cases.md)与[部署契约](phase-4-deployment-contract.md)覆盖以下交付：

| 范围 | 实现及验证 |
|---|---|
| F401–F405 | 生产单口令登录、PBKDF2哈希引用、限速、随机会话/CSRF/轮换/退出、HTTPS/Host/Origin严格校验；业务API及历史资源保护，只公开当前编译入口资源；受保护响应no-store。原本机开发模式兼容 |
| F406–F407 | 生产Web关闭内嵌dispatcher，独立单worker复用持久派发；生命周期/执行锁阻止维护与运行并发；worker SIGTERM后停止领取。跨进程互斥本机测试通过，Linux硬中断待实测 |
| F408–F410 | SQLite backup与内容哈希对象去重、7代快照/安全GC、SHA验证、ZIP导出/空目录恢复；manual/私有OSS push/pull配置选择。OSS使用模拟SDK验证ACL、完整性、失败保留与秘密文件凭据，不宣称真实OSS通过 |
| F411–F412 | 7日成功原视频dry-run/apply，永久证据、任务/派发/远端状态及共享原件检查；planned删除中断可协调恢复。失败/待恢复片不自动删除，HTML/长期证据保持 |
| F413–F415 | 只读镜像/持久卷、单独Compose项目名、回环端口及Nginx模板、资源限制/日志、预检、每日备份和显式安装的systemd模板；ZIP逐文件SHA/CRC/执行权限与覆盖保护 |
| F414真实迁移 | 已停止自有8765服务生成当前业务冷备份并重启恢复服务；迁移包约23MB，在本机独立空目录恢复，业务行哈希一致、3份永久证据和批准资格通过。没有在服务器执行恢复 |
| F417 | 退出立即清空私有状态/忙状态；延迟JSON不能回填，RAG流401进入登录、卸载取消流；writer owner防旧finally解新锁，旧上传批次/审核收尾检查认证代次。实际共用编排helper的Node回归通过 |

最终全量后端：**476 passed、5 skipped、44 subtests passed、1项既有Starlette弃用警告**，见[日志](../tmp/phase4-final-verified.log)；最终前端**42 passed、0 failed**及Vite构建通过，见[前端日志](../tmp/phase4-final-frontend.log)、[构建日志](../tmp/phase4-final-build.log)。平台跳过不计作Linux通过。Shell通过本机Git Bash `-n`语法检查，未执行Docker/systemd命令。

全量后另补部署包中文文档与生产每日清理开关，部署定向**15项通过**，见[日志](../tmp/phase4-deploy-tests.log)，包含关/开/失败顺序；与全量存在重叠，不相加。生产默认每日成功备份验证后清理满足7日条件的原视频，开发默认关闭；失败清理会报告失败并恢复此前服务状态。最终[交付校验](../reports/phase4-20261106/delivery-check.json)验证ZIP CRC/SHA、逐文件清单、已知本机凭据未命中、文档链接和实际前端资源。

独立审查发现并关闭7项P1：退出后的旧响应回填、注销结果未知仍残留私有状态、私有assets缓存、RAG流401漏处理、缺每日调度、部署脚本权限和worker缺OSS依赖。随后主会话补F417用例及复核、子模型实现/测试，修正旧忙锁与上传批次；Compose项目名冲突另经主会话检查修复。模型调用中途曾因账户不支持返回不可用；用户要求重试后已成功接续，未放弃修复。

## 浏览器与发布

[隔离认证浏览器记录](../reports/phase4-20261106/browser-auth.json)：真实localhost服务/合成资料，错误密码拒绝、正确密码进入资料库，退出后登录页出现且旧问题、资料及RAG子树均不存在。测试使用开发模式回环地址，不代表生产TLS已经通过。截图API两次超时，未保存截图，不伪称视觉截图通过；本轮不更改本人已批准的三页视觉，仅新增同体系登录和退出入口。

本机8765继续原开发模式，云端认证只由生产配置启用；前端采用隔离构建后显式复制index引用资源并最后切换index，旧评分/样稿资源保留。真实审核/索引前后只读核验保持。无Git commit/push/tag，无真实模型调用，无本轮新增模型费用。

## 真实迁移证据

[迁移报告](../reports/phase4-20261106/migration-report.json)：4来源、6版本、5审核、4任务，迁移前后表行SHA完全一致；3份eligible，批准分数99/100/100，永久内容逐份verify通过。独立包含79个清单文件及共享预算账本，不包含.env；[迁移包](../reports/personalkb-migration-20261106.zip)和[SHA](../reports/personalkb-migration-20261106.zip.sha256)。

原正式索引仍3来源214块ready。本机恢复位置改变后索引需要显式重建；云端同理，不能将原索引状态或本机恢复演练写成服务器已经通过。原批准无需重评。

## 下一步与限制

按[服务器操作手册](phase-4-server-guide.md)先上传部署/迁移包，完成第一节并回传preflight-report.json；然后DNS/证书、镜像构建、空目录迁移及实际HTTPS登录。云端报告工具只做认证/只读检查和可选资源观察，不自动调用模型。

剩余：Docker镜像实际构建与进程启动、Nginx实际证书/代理、真实视频/HTML/问答链路、Linux硬中断/恢复、整机资源与网站/小程序共存、systemd一次实跑与手动下载或OSS外部备份/恢复。只有报告和人工观察齐备才关闭4D。

当前保留限制：备份/远端传输在维护窗口停本应用；manual未外部下载前只有本机副本；OSS无远端自动GC；失败素材自动清理关闭，生产成功原片7日自动清理可配置关闭。镜像基础版本使用官方tag，目标构建须记录实际digest/依赖版本，不能称为本机已验证镜像。正式ASR OSS仍按C02手动切换，临时上传官方限制保持。日常费用继续观察，非硬月费指标。
