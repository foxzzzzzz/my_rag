# Phase 4 服务器操作手册

2026-11-06。代码及本机验证已交付，**服务器尚未部署/验收**。继续由本人执行，回传报告。暂用`kb.yuanzhll.top`，现有官网域名及小程序不改。

2026-11-07认证报告进展：认证/4来源/CSRF/退出已通过，仅RAG状态503。最新修复包为`personalkb-deploy-20261107-ragpathfix1.zip`，修复Linux生产秘密/账本绝对路径被RAG配置校验拒绝的问题，包含之前构建源修复。现有服务先保持运行：新包校验解压到app-ragpathfix1，用`deploy/rag-path-hotfix.Dockerfile.template`、明确指定PERSONALKB_BASE_IMAGE=personalkb:local及--pull=false/--network=none构建独立personalkb:ragpathfix1，只复制修复代码不重装依赖；挂载公开配置只读并离线验证load_rag_config，成功回传后再备份原镜像tag及切换本项目服务。不得重新生成配置/账本/迁移数据。精确SHA与当前步骤以[部署交接](phase-4-deployment-handoff.md)为准；下方历史包说明保留，不要求重做已通过步骤。

2026-11-07最新：本人截图已确认buildfix2镜像构建成功（BUILD_OK、约275MB、磁盘剩约13GB），当前生产操作继续在app-buildfix2执行，下一步独立空目录恢复。后续构建备用包为`personalkb-deploy-20261107-buildfix3.zip`及SHA，增加`config/pip-build.conf`的清华PyPI HTTPS索引，仅在安装RUN中导出PIP_CONFIG_FILE覆盖三个pip安装；不设置镜像ENV或主机/运行时pip默认源。当前无需上传/重建/切换此备用包。下方buildfix2说明作为已执行步骤保留。

2026-11-07更新：最新部署包为`personalkb-deploy-20261107-buildfix2.zip`及对应`.sha256`，保留前端共享JSON目录修复，并将Docker内Debian主仓库/安全更新改为清华TUNA HTTPS镜像；原迁移包保持。配置位于代码目录`config/debian.sources`，仅在镜像构建阶段复制到`/etc/apt/sources.list.d/debian.sources`，不是修改宿主机源或同级生产config目录。保持bookworm、官方Signed-By与TLS校验，安全更新镜像可能存在同步延迟，参考[TUNA说明](https://mirrors.tuna.tsinghua.edu.cn/help/debian-security/)。

已完成第一节的服务器无需重新生成配置/口令：先在慢速构建原终端Ctrl+C取消本次构建，确认返回提示符；上传新包，校验后解压至尚不存在的同级`app-buildfix2/`，校验内部`SHA256SUMS`，从此目录执行第三节check/build并沿用同级config/state/secrets/backups。原app及app-buildfix1保留，不将新代码目录当作新数据根；后续操作/定时服务工作目录也需指向app-buildfix2。不执行全局清理或重启Docker。精确包SHA见[部署交接](phase-4-deployment-handoff.md)。

## 1. 上传与准备（先做到本节并回传预检即可）

将以下四个文件上传至新目录`~/my_rag/personalkb`，不要放进旧索引压测目录：

- [部署包](../reports/personalkb-deploy-20261107-buildfix2.zip)及[校验文件](../reports/personalkb-deploy-20261107-buildfix2.zip.sha256)，只含代码/公开配置/前端源码。
- [迁移包](../reports/personalkb-migration-20261106.zip)及[校验文件](../reports/personalkb-migration-20261106.zip.sha256)，约23MB，含本人知识资料和审核/预算账本，不含.env。此包只需传给自己的服务器，不用回传。

在该上传目录执行：

```bash
sha256sum -c personalkb-deploy-20261107-buildfix2.zip.sha256
sha256sum -c personalkb-migration-20261106.zip.sha256
python3 -m zipfile -e personalkb-deploy-20261107-buildfix2.zip app
cd app
sha256sum -c SHA256SUMS
python3 deploy/configure.py --hostname kb.yuanzhll.top --output ../config
mkdir -p ../state/tmp ../backups ../secrets
chmod 700 ../state ../backups ../secrets
export STATE_DIR="$(realpath ../state)"
export CONFIG_DIR="$(realpath ../config)"
export SECRET_FILE="$(realpath ../secrets)/personalkb.env"
export BACKUP_DIR="$(realpath ../backups)"
export PERSONALKB_COMPOSE_PROJECT=personalkb
python3 -m tools.auth_setup --config "$CONFIG_DIR/auth.json" --output "$SECRET_FILE"
sh deploy/operate.sh report --config "$CONFIG_DIR/web.json" --state "$STATE_DIR" --secret "$SECRET_FILE" > ../preflight-report.json
```

口令工具会在终端私密询问两次密码，不用将密码发到聊天。配置工具与密码工具都拒绝覆盖已有文件；重试时跳过已经成功的生成步骤。`preflight-report.json`若失败仍会保存缺项，先回传此文件。它只检查可独立准备项，DNS/TLS字段false不代表证书已经测过。没有Compose时先回传，不自动升级Docker或修改现有业务。

## 2. DNS、证书与独立Nginx配置

本人已确认沿用云控制台下载、手动上传方式；具体命令与可下载的专属站点配置见[子域SSL安装步骤](phase-4-nginx-ssl-guide.md)，无需改为Certbot。

在域名DNS管理中增加`kb`的A记录到本服务器公网IPv4；没有可用IPv6就不要添加AAAA。官网`yuanzhll.top`的记录不动。

为`kb.yuanzhll.top`申请包含此子域的有效证书；根域证书不一定包含子域。将`deploy/nginx.conf.template`另存为本项目专属站点配置，替换`__HOSTNAME__`、`__APP_PORT__`（默认8768）、`__ACME_ROOT__`、`__CERTIFICATE__`、`__PRIVATE_KEY__`。不替换现有官网的server块、不设置default_server。证书签发前只启用模板的HTTP/ACME部分，证书存在后再启用HTTPS部分。

Nginx保留HTTPS代理、HTTP/1.1、关闭请求/响应缓冲和代理重试；否则大上传可能先占满代理临时盘，事件流可能被缓冲。最后由本人执行`sudo nginx -t`，成功后再`sudo systemctl reload nginx`。证书工具和具体站点目录取决于当前Nginx安装方式，本项目不自动改动。

## 3. 构建、迁移与启动

仍在app目录且保留第一节的环境变量：

```bash
sh deploy/operate.sh check
sh deploy/operate.sh build
python3 -m tools.maintenance --config "$CONFIG_DIR/maintenance.json" import --archive ../personalkb-migration-20261106.zip --target-empty-dir ../restored
test ! -e "$STATE_DIR/workflow"
test ! -e "$STATE_DIR/budget.sqlite"
mv -n ../restored/workflow "$STATE_DIR/workflow"
mv -n ../restored/budget.sqlite "$STATE_DIR/budget.sqlite"
sh deploy/operate.sh start
```

这是首次迁移流程；如state已有业务目录，应停止并核对，不要覆盖。恢复报告会提示路径变化需要重建索引，属于预期。4来源/6版本/5审核/4任务应保持，3份批准不必重评；工程测试HTML仍待审。

生产回环健康检查须携带正式Host与HTTPS代理头：`curl -sS -i --max-time 10 -H 'Host: kb.yuanzhll.top' -H 'X-Forwarded-Proto: https' http://127.0.0.1:8768/healthz`。生产中间件在进入healthz路由之前同样执行精确Host与HTTPS校验，直接以127.0.0.1:8768作为Host会返回400；这不意味着容器启动失败，也不能通过放宽配置来修复检查。只有来自本机回环的代理头会被信任。另用`curl -sS -i --max-time 15 https://kb.yuanzhll.top/healthz`验证真实Nginx/TLS链路，不加-k。首次启动连接被拒绝可短暂重试，持续失败再看容器状态，不重复移动数据或用start绕过已启动服务。

访问`https://kb.yuanzhll.top/`，用自己设置的口令登录。只有Web监听主机回环8768；不需要对公网开放8768，也不需要新开数据库端口。`start`用于首次或停服后启动，已运行的自有服务重启用`sh deploy/operate.sh restart`。所有命令显式使用独立Compose项目名，避免与其他站点的deploy目录同名项目冲突。

## 4. 启用真实处理与重新建索引

2026-11-07凭据补充：本人只读检查embedding/answer凭据均不存在。仅在既有`../secrets/personalkb.env`中补充DASHSCOPE_API_KEY（项目使用百炼北京接入点）与DEEPSEEK_API_KEY；先以私有权限备份原文件，再用服务器编辑器填写，不将Key放命令行/聊天，不复制整份本机.env，不运行auth_setup/configure或source秘密文件。编辑后用既有dotenv解析器检查无重复变量、非API键的原有条目及password_hash_env对应哈希全部保持；只打印检查通过/Key存在性。失败即停并保留私有备份，不重建容器。

编辑器可能原子替换绑定文件inode，校验通过后从app-ragpathfix1携带既有路径变量，仅对personalkb web/worker执行compose up -d --no-build --pull never --force-recreate以重新挂载秘密文件，而非构建镜像或重启Docker。服务恢复后只检查凭据bool与HTTPS健康，再由本人页面显式同意费用后构建索引。API Key存在不等于验证远端权限/余额；配置步骤不调用模型。

初次生成配置默认关闭视频/HTML模型和抖音自动下载，避免首次启动就付费。将所需`DASHSCOPE_API_KEY`、`DEEPSEEK_API_KEY`及抖音Cookie等仅配置在`$SECRET_FILE`；不要直接复制含无关变量的整份本机.env到公开目录。Cookie对应UA在`$CONFIG_DIR/douyin.json`核对；云端IP不同，抖音真实可用性须重新实测，拒绝后不无限重试。

需要处理时手动启用web.json的`live_video_enabled`/`live_html_enabled`、douyin.json的`enabled`，重启自有服务；导入后仍需显式启动并同意费用。ASR默认沿用本人C02确认的临时上传，正式音频OSS只在本人另外切换时启用，不与备份OSS混用。

问答页展开索引诊断，确认合格资料3份，勾选本次费用同意后重建索引。索引绑定绝对路径，因此迁移后不能把旧214块ready当成仍可直接使用；新索引块数由实际配置/版本决定。预算账本已迁移，重建和测试用量继续计入原累计额度。本机未替本人调用模型或重建。

随后各验证1份有权处理的视频与HTML导入→启动→复核，以及问答引用/无依据拒答。云端模型、真实下载、中断恢复和网站/小程序正常情况记录后回传；不要把离线测试当成这些步骤已经完成。

## 5. 定时备份、手动下载和 OSS

默认manual。先手动运行：

```bash
sh deploy/operate.sh daily
cat "$STATE_DIR/backup-status.json"
```

脚本短暂停止本项目的 Web 和 worker，新快照通过对象哈希及 SQLite 完整性校验后才轮换旧快照。冷备失败也会尝试恢复原先运行的服务。报告中的 `services_restored=true` 表示原先运行的容器通过连续两次状态检查，若原先运行 Web，还须通过回环和 HTTPS 健康检查。恢复超时或检查失败时，命令返回非零，报告保留已创建的快照 ID。检查超时和间隔沿用 `deployment.json`。手动模式仍需单独保存外部副本。读取报告的 `snapshot` 值后按需导出。

```bash
sh deploy/operate.sh export SNAPSHOT_ID --output /backups/personalkb-manual.zip
```

用自己的SFTP/文件传输工具从服务器`$BACKUP_DIR/personalkb-manual.zip`下载到本地；导出拒绝覆盖，下一次换文件名。默认保留7份快照且复用未变对象，不每天生成7份全量ZIP。

如选择OSS：maintenance.json设`storage_mode=oss`，配置真实region/HTTPS endpoint/private/bucket/专属prefix及凭据环境变量名，在统一秘密文件中填对应凭据。现支持阿里云OSS；需对专属前缀具备读写、核对Bucket/对象ACL权限，不借用官网全权限密钥。本项目不创建Bucket、不改访问策略。先运行`push SNAPSHOT_ID`，再在独立仓库/环境运行`pull SNAPSHOT_ID`和`restore`演练；上传成功不等于恢复完成。远端对象暂不自动GC，费用/生命周期需后续观察。网络上传和回读当前仍占维护窗口，资料增长后可能延长停服时间。

确认手动 `daily` 验收通过后，将 `deploy/systemd/` 两份模板复制为 `.service` 和 `.timer`，在服务文件中填入项目绝对目录和环境文件路径。环境文件只需 `STATE_DIR`、`CONFIG_DIR`、`SECRET_FILE`、`BACKUP_DIR` 和 `PERSONALKB_COMPOSE_PROJECT` 等部署变量，登录密钥仍通过 `SECRET_FILE` 引用。

定时器默认每周日北京时间 03:30。需要调整时，替换 `.timer` 中的 `OnCalendar` 值。可先用 `systemd-analyze calendar` 核对表达式的下次触发时间。

| 调度 | `OnCalendar` 值 |
| --- | --- |
| 每周日 03:30（默认） | `Sun *-*-* 03:30:00 Asia/Shanghai` |
| 每天 03:30 | `*-*-* 03:30:00 Asia/Shanghai` |

经确认后将单元安装到 `/etc/systemd/system/`，运行 `systemctl daemon-reload` 和 `systemctl enable --now personalkb-backup.timer`。通过 `systemctl list-timers personalkb-backup.timer` 和实际运行日志验收。调整已启用的定时器后，重新加载单元并重启该定时器。模板的 `Persistent=true` 会在错过运行时间后补跑，启用前需留出维护窗口。

快照份数由 `maintenance.json` 的 `keep_snapshots` 控制，默认最近 4 份，创建快照时执行轮换。原视频保留单独由 `video_retention_days` 和 `auto_retention_enabled` 控制。生产配置生成器默认开启自动清理，冷备创建并校验成功后才执行，仅处理满 7 天且证据校验通过的成功视频。可在首次演练前关闭该开关，另选维护窗口运行 `sh deploy/operate.sh retention` 预览。预览会短暂停止本项目服务。手动 `retention --apply` 需要单独确认。

## 6. 回传报告与剩余门槛

部署后在app目录准备宿主机报告配置：

```bash
python3 -c 'import json,os; from pathlib import Path; p=Path(os.environ["CONFIG_DIR"])/"cloud-acceptance.json"; c=json.loads(p.read_text()); c["disk_path"]=os.environ["STATE_DIR"]; p.write_text(json.dumps(c))'
python3 -m tools.cloud_acceptance --config "$CONFIG_DIR/cloud-acceptance.json" --url https://kb.yuanzhll.top --output ../cloud-phase4-report.json
```

工具私密询问口令，验证实际HTTPS、未登录隔离、登录、只读资料/索引状态、CSRF与退出，**不发付费请求**。报告不含口令、Cookie、CSRF、正文，失败时同样回传报告。它不代替真实视频链路或外部备份恢复。

资源共存复测可在自有容器内使用已安装psutil的工具，另一个浏览器窗口启动单条视频任务时采样：

```bash
cd deploy
docker compose --project-name personalkb exec web python -m tools.cloud_acceptance --url https://kb.yuanzhll.top --output /state/cloud-resource-report.json --sample-seconds 120
```

此命令会询问口令，采样不自动启动视频。回传`cloud-phase4-report.json`、`$STATE_DIR/cloud-resource-report.json`、`backup-status.json`及网站/小程序人工观察；外部下载/OSS与空目录恢复结果分开记录。Docker镜像、HTTPS、真实链路、硬中断、整机≤3GB与网站共存、异地恢复未完成之前，Phase 4整体保持待验收。
