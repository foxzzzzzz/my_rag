# Phase 4 实现与部署验收

## 2026-11-10 目标服务器验收回传

部署与迁移会话回传以下分项结果，早期记录按当时状态保留。

| 范围 | 回传结果 |
|---|---|
| 部署与原资料 | 资料及审核迁移、Git 一键部署切换、HTTPS 登录与认证、原资料及索引通过。云端问答、引用和无依据拒答通过。 |
| 恢复 | F409 服务器隔离目录恢复及 F410 Windows 外部副本恢复通过。 |
| 新内容和预算 | 新视频与 HTML 模型处理、预算核对和本人内容复核通过。视频转写与时间戳可定位原片，HTML 摘要忠于原文，独立笔记及正文保留。 |
| 资源和中断 | 真实负载整机内存峰值 1,453,563,904 字节，官网与小程序正常。worker 硬中断后恢复，未知请求转为需要关注，尝试次数保持 1。 |
| 首装与回滚 | 目标服务器独立 Docker 环境离线复用已有镜像，空库首装及候选故障回滚通过。 |
| 手动维护 | 手动冷备及隔离环境快照轮换、原片保留规则通过。 |

Phase 4 继续待验收。已启用每周日北京时间 03:30 定时器，保留最近 4 份快照。首轮计划于 **2026-11-15 03:30** 触发。收集 systemd 触发及执行结果、新快照校验、按 7 天规则处置符合条件原片及永久证据保留的结果，并核对 Web/worker 恢复及 HTTPS 健康。以上核对通过后关闭 Phase 4。[待办](TodoList.md)

**4A–4C 的本机验证和交付已完成。4D 按目标服务器场景分项验收。** 现有服务器从手工部署切换到 Git 一键部署已通过，实测结果与各项验收范围见下文。

## 实现与测试

### 2026-11-07 F410 手动外部副本恢复通过

本人将 F409 快照 `3db5da8d6402dcd459c25837a461f4d7b1d4e8ba6382e1885a8c8e638885dbbc` 导出为 `personalkb-snapshot-3db5da8d6402.zip`，下载到 Windows 本机并恢复至独立目录。本人回传 `LOCAL_RESTORE_OK`，记录数为 4 个来源、6 个版本、5 条审核、4 个任务、229 条预算记录。

本机复核下载 ZIP 的 SHA256 为 `7b473c009ee19eaf5eaf4013d2a2381fbee83910b98f3ddf990d22b987e9563f`，与下载的校验文件一致。包内清单 ID 匹配 F409。另从同一 ZIP 在本机临时目录独立恢复，逐文件校验和两份 SQLite 完整性检查均通过，记录数与本人回传一致。F410 手动外部副本验收通过。

### 2026-11-07 冷备快照独立目录恢复通过

本人回传 `ISOLATED_RESTORE_OK`。快照 `3db5da8d6402dcd459c25837a461f4d7b1d4e8ba6382e1885a8c8e638885dbbc` 已恢复到服务器 `~/my_rag/personalkb/restore-drill.NbrCfo/restored`。恢复工具通过清单、文件 SHA256 及两份 SQLite 完整性检查，恢复结果为 4 个来源、6 个版本、5 条审核、4 个任务和 229 条预算记录。

演练只读挂载备份和公开配置，写入单独目录。脚本比对的 Web/worker 容器 ID、运行状态、启动时间和重启次数一致，HTTPS 健康检查返回 `{"ok":true}`。演练目录返回索引需按恢复路径重建的提示。F409 目标机独立目录恢复通过，服务器外部副本及其恢复仍列入 F410。

### 2026-11-07 现有服务器 Git 一键部署切换验收通过

本人确认在 `~/my_rag/personalkb/app-git` 检出 `910d185`，`Preflight passed`、`SNAPSHOT_VERIFIED`、`Deployment healthy` 和 `IMAGE_SWITCH_OK` 均通过。认证报告为 `passed`，4 个来源、3 份已索引资料、`ready=true`。本人在网页核对了原正文、审核记录和本地关键词检索证据。此项验收范围为保留现有配置和数据的 Git 升级。空机首装、故障回滚、外部备份恢复和完整 Phase 4 的其他目标机门槛分别验收。

### 2026-11-07 云端索引与三题问答本人确认通过

本人回传云端索引重建成功，OpenManus/smolagents两题回答及引用正常、无依据问题正确拒答。据本人观察关闭当前三份资料云端索引与问答分段，不外推全部问题或模型稳定性；尚未提供新块数/用量文件，不沿用旧214作为新构建实测。后续预算为原账本增量结算，不再要求198条SHA不变。

真实模型操作后的工作流与账本已完成冷备、快照校验及外部副本恢复。后续真实新导入、负载共存和硬中断的实测结果见本页 2026-11-10 验收回传。

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

迁移前本机索引含 3 个来源和 214 块。路径变化后的云端索引已由本人重建，随后在 Git 切换中验证可用。将资料恢复到不同路径时，仍需检查索引状态并在必要时重建。原批准继续有效。

## 下一步与限制

现有服务器的 Docker 构建、HTTPS 认证、资料迁移、当前资料问答及 Git 一键升级已有实测记录。后续常规升级见 [Git 部署步骤](../README.md#一键部署)。云端认证报告工具用于只读核对资料和索引状态，也可按需采样资源。

4D 仅剩首轮定时冷备与原视频清理实测。按本页 2026-11-10 验收回传中列出的检查项核对后关闭。

当前保留限制：备份/远端传输在维护窗口停本应用；manual未外部下载前只有本机副本；OSS无远端自动GC；失败素材自动清理关闭，生产成功原片7日自动清理可配置关闭。镜像基础版本使用官方tag，目标构建须记录实际digest/依赖版本，不能称为本机已验证镜像。正式ASR OSS仍按C02手动切换，临时上传官方限制保持。日常费用继续观察，非硬月费指标。
