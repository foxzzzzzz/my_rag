# Phase 4 部署与资料迁移独立会话交接

2026-11-06。本人要求核验Nginx/SSL专项后，新开独立会话继续部署与资料迁移。原会话已核对专项会话01a1b027-1199-7173-96ab-5b88f7321537的最新用户输出、最终回复及原始安装回传，确认该专项通过；Phase 4整体仍未通过。

## 已通过，不重复实施

- 预检Linux/x86_64、Compose/FFmpeg、生产配置/口令哈希/秘密权限及端口准备通过；当时剩余约14.43GiB，构建前后仍需观察，不能全部占满。
- DNS kb.yuanzhll.top指向106.53.20.177。独立站点/etc/nginx/conf.d/personalkb.conf已安装，证书链/etc/nginx/ssl/personalkb/fullchain.crt、配对私钥privkey.key，SAN覆盖kb；有效期UTC 2026-11-06 08:00:00至2027-02-04 07:59:59。
- 原始回传中两次nginx -t均成功，reload未报错，服务active；HTTP301的Location为https://kb.yuanzhll.top/；HTTPS未加-k，证书默认校验通过后收到502。
- 本人确认原官网、小程序仍正常。无需重新申请证书、修改代理、开公网8768或重复询问共存是否确认。

## 最新后端状态（来自专项最后一轮用户输出）

### 2026-11-07 云端索引与三题问答本人验收通过，进入冷备恢复（当前优先）

本人确认云端索引重建成功、前两题回答及引用正常、第三题正确拒答。按本人观察确认当前三份资料的云端embedding/问答/引用与无依据拒答分段通过，原3份批准保持；未取得新的构建统计/用量报告，不臆造云端块数或实际费用。原198行预算基准不再作为不变断言。

下一小批优先运行operate.sh backup（不是daily），仅停止/恢复独立personalkb Web/worker，创建含当前工作流、预算、长期证据与新索引的一致性快照；不触发视频retention或第三方上传。本人先结束页面正在执行的操作，再从app-ragpathfix1显式sudo env执行，回传snapshot、恢复后HTTPS健康/容器及磁盘。create成功尚不等于完整verify/恢复通过，后续根据确切snapshot做完整性验证、独立空目录恢复及manual外部下载/回读。默认manual不自动开通OSS。

剩余4D：真实新视频/HTML导入与复核、单worker真实负载整机内存<=3GB及官网/小程序共存、硬中断与费用未知不自动重发、每日备份/调度/安全保留策略及外部恢复等仍待验收；不得仅三题通过宣布完整Phase4完成。

### 2026-11-07 凭据补充及登录配置保留通过，待本人显式构建与问答（当前优先）

本人确认LOGIN_CONFIG_PRESERVED、HTTPS健康正常、容器内两个Key均True。只证明原登录配置保持和Key存在，尚不证明远端权限/余额/真实模型调用通过。当前执行根app-ragpathfix1，原预算账本继续沿用。

下一步本人问答页确认合格3、页面本次费用同意后点击一次构建索引；成功应索引可用、已索引3，片段数按实际结果。取消费用勾选后可先本地关键词检索候选验证OpenManus证据；再每次明确同意费用，以混合检索生成OpenManus记忆/工具配对、smolagents错误反馈，以及无依据价格/退款/QPS/P99拒答样例，逐条打开引用核对永久证据。不得重复点击或出错后盲重试。真实构建/问答/模型费用仍待本人执行回传。

模型操作后预算reservations条数/逻辑SHA会正常变化，不再以迁移前198条和原SHA作为不变断言；应保留旧账并新增/结算本次记录。原3份批准不重评。后续资源共存/硬中断/真实新导入及备份外部恢复门槛仍待验。

### 2026-11-07 两项模型凭据缺失，准备保护登录配置地补充（当前优先）

本人回传embedding与answer的credential_present均false，要求配置服务器API Key且不得覆盖登录配置。指导仅备份并编辑现有secrets/personalkb.env，增加DASHSCOPE_API_KEY/DEEPSEEK_API_KEY，不重生成口令/整份覆盖.env、不输出Key或source文件；用既有dotenv比较原password_hash_env及所有非API键条目保持且Key非空。检查通过后从app-ragpathfix1只强制重建自己的Web/worker以处理编辑器可能更换文件inode的bind mount，不构建镜像/重启Docker。恢复HTTPS/Key bool后本人页面显式费用同意才构建索引。此处准备步骤，尚未声称凭据配置或真实模型可用。

### 2026-11-07 批准/预算及本人网页核对通过，准备显式索引重建（当前优先）

本人确认生产当前批准分数99/100/100、预算reservations198条及APPROVAL_AND_BUDGET_OK；该检查包含与迁移包基准逻辑行SHA一致断言，原账本连续性通过。本人登录网页确认正文和审核信息正常。部署与资料迁移这一段验收通过，原批准无需重评。

下一步先在当前Web容器只读检查模型凭据存在性（按models配置读取env变量名，仅打印bool，不输出Key）、RAG模型及配置费用上限。此检查不请求模型。后续索引构建需本人在问答页勾选本次费用同意后显式点击构建索引，仅处理3份合格资料；无聊天中自动付费授权，不调用API代替点击。当前配置模型embedding=text-embedding-v4、answer=deepseek-flash，单操作run_limit=2、累计research_limit=100（配置预算，不作实时官方价格或余额保证）。不更改账本/分数，API Key存在不等于可用。

完整Phase4仍待真实云端索引/问答/视频HTML、真实负载共存/硬中断、每日备份与外部恢复等验收；当前不提前关闭。

### 2026-11-07 09:54认证报告整体passed，RAG503已解决（当前优先）

已读取本人回传的[认证报告](../reports/phase4-server-20261107/cloud-phase4-auth-ragfix-20261107-095403.json)：result=passed，真实HTTPS、未登录401、登录/session/来源200、4来源、Cookie安全属性、CSRF与退出通过。rag_status=200、eligible_sources=3、indexed_sources=3、indexed_chunks=214、ready=false、needs_rebuild=true。确认生产路径503修复成功；旧索引因路径变化不可用，214不代表云端可检索，不自动重建或收费。

下一小批只读核对生产库当前版本3份最新批准分数99/100/100及预算reservations逻辑行SHA。主代理已从原迁移ZIP只读计算预算基准：reservations=198，按所有列取行、key=repr排序、data={'reservations':rows}再json.dumps(sort_keys=True,ensure_ascii=False,separators=(',',':')) UTF8的SHA256为`791c132ef563d0dab0d1e44f403df892ea18908d63d56e033105ce14e0216de7`；原预算SQLite文件SHA为`e819c2f3db8ebbc403df8a0e78505702530ea5d981a973b40a6e7976fa84c3cf`，逻辑行比较优先以免SQLite物理布局差异误判。尚待目标机输出及本人浏览器内容/审核观察。

剩余4D：显式费用同意后的云端索引重建/真实问答及视频HTML链路、真实负载共存/硬中断、每日备份与外部副本/恢复等仍未验收；报告历史路径未配置、采样未请求，不以passed扩大为Phase 4完成。

### 2026-11-07 09:48补丁切换成功，短暂502重试已恢复（当前优先）

本人回传旧镜像已保留为`personalkb:before-ragpathfix1-20261107-094810`；Web/worker重建Started，HTTPS首次502后自动重试返回ok:true，两容器running/RestartCount=0，并输出SWITCH_OK。切换脚本含两容器实际Image ID与补丁ID一致断言，已通过。首次502符合启动间隙且本次已恢复，无需修改代理或再次切换。

当前代码根为服务器app-ragpathfix1，personalkb:local已指向补丁。下一步执行前次第二批cloud_acceptance（使用既有state/tmp/cloud-acceptance-host.json，新命名cloud-phase4-auth-ragfix-*报告），私密输入口令，回传JSON。RAG状态200、3份资格及预算连续性仍待复验，不以healthz替代；索引重建/模型费用仍需显式同意。

### 2026-11-07 补丁镜像与RAG_CONFIG_OK通过，待切换复验（当前优先）

本人确认personalkb:ragpathfix1构建成功且输出RAG_CONFIG_OK，Linux公开生产配置已实测可加载，尚未切换当前Web/worker。

下一批从app-ragpathfix1读取当前运行Web/worker的实际Image ID并确认一致，将旧ID保存为带时间戳personalkb:before-ragpathfix1-*标签且回读验证；新ID重新标记personalkb:local。带既有路径变量、独立personalkb项目名执行compose up -d --no-build --pull never web worker，仅重建自己两个服务，不再次用operate.sh start的空端口预检。随后默认TLS的HTTPS healthz重试、回读两容器Image ID/运行状态，成功后重新运行cloud_acceptance生成新报告。保留旧标签及全部业务数据，不重新迁移、评分、模型请求或索引重建。切换/健康/RAG状态复验仍待回传。

### 2026-11-07 09:30认证报告定位RAG503，补丁待服务器离线验证（当前优先）

本人报告cloud-phase4-auth-20261107-093057.json：认证/安全Cookie/4来源/CSRF/退出均通过，仅rag_status=503导致failed。源码确认部署器生成绝对env_file=/run/secrets/personalkb.env及budget.ledger=/state/budget.sqlite，旧RAG加载器在Linux拒绝绝对路径。主代理使用原buildfix2代码在显式POSIX路径语义下复现invalid_config；修复后生产配置加载通过，不是缺密钥或费用未同意导致。

当前补丁包：[personalkb-deploy-20261107-ragpathfix1.zip](../reports/personalkb-deploy-20261107-ragpathfix1.zip)，273,817字节，SHA256 `eb576294c217d591c93f0d2b2bf30402a68451f3929a72970d7fbd2000fb6e67`，对应.sha256已生成。145文件CRC/SHA及私密路径排除、旧Linux语义复现/新配置加载通过；相对buildfix2仅personalkb/rag_index.py运行时Python文件变化，见[报告](../reports/phase4-20261106/ragpathfix1-delivery-check.json)。定向64通过1平台跳过。

下一小批：上传ZIP/SHA至服务器原根目录，解压到尚不存在的app-ragpathfix1，校验内部清单；用其deploy/rag-path-hotfix.Dockerfile.template指定现有personalkb:local为BASE、--pull=false/--network=none构建personalkb:ragpathfix1，仅COPY修复文件不重装依赖。新tag挂../config到/app/config只读、--network none、--read-only运行load_rag_config并断言/state/budget.sqlite，期待RAG_CONFIG_OK。不挂秘密/业务数据，不停止当前服务。

离线成功回传后再备份旧镜像tag、把新镜像切到personalkb:local，并从app-ragpathfix1以明确路径/项目名compose up --no-build只重建web/worker（不可再次用start预检已占端口）。回环/HTTPS健康及认证复验、3份批准/预算检查仍待执行；不自动付费重建索引。

### 2026-11-07 09:27（北京时间）容器与HTTPS健康通过（当前优先）

本人回传Web/worker均Up 2 minutes；ss仅监听127.0.0.1:8768。携正式Host/本机HTTPS代理头的回环healthz返回Uvicorn HTTP200及ok:true；真实HTTPS healthz经nginx/1.24.0返回200及ok:true，未加-k，响应含CSP/nosniff/no-store。确认原400来自不合生产约定的检查命令，已解决，无需改代码或代理。

下一批从app-buildfix2运行现有tools.cloud_acceptance，派生宿主机disk_path配置到state/tmp、使用新命名报告，私密getpass输入口令。只验证未登录401、登录/Cookie/CSRF、4来源与RAG资格状态、退出，不调用模型或重建索引；报告可回传。认证、实际3份批准/永久证据、预算连续性及真实模型/资源/恢复/外部备份等仍待对应证据，不因healthz200关闭Phase 4。

### 2026-11-07 数据已放置、容器已启动，纠正健康检查（当前优先）

本人回传DATA_PLACED_OK、预检ready=true（剩余13,191,766,016字节）、Web/worker均Started且即时ps为Up。之后回环curl首次(7)连接被拒绝，重试返回400，set -e阻断后续HTTPS检查，尚未证明真实HTTPS失败。

主代理核对web_app.py：生产中间件要求Host完整匹配trusted_origins的netloc，再要求HTTPS；先前直接curl回环IP缺正式Host及X-Forwarded-Proto，诊断命令有误。无需改安全配置/代码或重新放置数据。下一批只读查看独立项目容器/监听，并以正式Host+本机HTTPS代理头检查回环healthz，再默认TLS校验访问HTTPS healthz。稳定运行与HTTPS健康待回传，不把瞬时Up或错误400当最终验收。

### 2026-11-07 目标机空目录恢复通过，待放置与启动（当前步骤）

本人回传restored恢复成功，4来源/6版本/5审核/4任务，BUDGET_INTEGRITY_OK及RESTORE_OK。这已是目标机恢复实测，不再仅本机演练。原迁移包只读抽查任务均succeeded（4），web_dispatch均done（3），无待执行派发；不重新评分或自动重建索引。

下一批命令在app-buildfix2同级核对生产workflow/budget不存在后，使用mv -Tn分别安全放置并检查源已移动；任一失败停止，保留现场，不覆盖/自动回滚。随后带明确路径变量sudo启动独立personalkb的web及单worker，查看项目ps、回环healthz及默认TLS校验的HTTPS根页面。此处是待执行步骤，尚未宣称服务/登录/资料资格验收通过。

### 2026-11-07 buildfix2镜像成功，继续迁移；buildfix3留作后续构建

本人截图确认buildfix2输出BUILD_OK、镜像已标记personalkb:local（约275MB），磁盘剩约13GB。实际Docker构建通过；未恢复资料或启动服务。当前继续从服务器app-buildfix2执行，下一批仅将原迁移包导入独立restored并只读核对4来源/6版本/5审核/4任务与预算账本完整性；回传后再安全放置到不存在的state目标并启动。

用户另授权后续Docker构建pip国内源：新增config/pip-build.conf，清华TUNA HTTPS单一索引；仅安装RUN内export PIP_CONFIG_FILE覆盖三个pip，不持久ENV或修改主机/运行时默认源，版本/no-deps保持。部署18项、前端42项通过；作用域为静态验证，无本机Docker。当前无需为此重新构建/上传/切换服务器代码。

后续备用包：[personalkb-deploy-20261107-buildfix3.zip](../reports/personalkb-deploy-20261107-buildfix3.zip)，271,161字节，SHA256 `60e90b18e3010b27a8deb2928586747e91b4d7beb28c15ae56e521ab18df71ad`，对应.sha256已生成；144文件清单/CRC及解压配置/前端布局核验通过，见[报告](../reports/phase4-20261106/buildfix3-delivery-check.json)。原迁移包及SHA保持。下方此前构建待验状态按历史保留，勿重复构建已成功镜像。

### 2026-11-07 国内Debian源更新包（当前优先）

本人回传buildfix1已通过包校验并进入构建，APT安装FFmpeg从deb.debian.org下载耗时2250秒以上，npm ci为23.6秒；随后确认仍慢并授权仅改本项目Docker内源。按BF04–BF06增加`config/debian.sources`，Dockerfile在Python阶段apt前复制，仅写镜像；清华TUNA主仓库/安全更新HTTPS、bookworm系列及官方Signed-By保持。不改宿主机源/daemon/其他项目，不改npm/pip源。

- 当前部署包：[personalkb-deploy-20261107-buildfix2.zip](../reports/personalkb-deploy-20261107-buildfix2.zip)，269,782字节，SHA256 `24157a76e903a4a7c45a9fe9e79b75067518c5ddecdb8e3e90c8120386434e26`，对应`.sha256`已生成。
- 部署17项、前端42项及隔离Vite构建通过；发布包143文件SHA/CRC及解压后前端布局、源配置/签名与打包核验通过，见[交付核验](../reports/phase4-20261106/buildfix2-delivery-check.json)。本机无Docker，实际APT/构建速度仍未验。
- 下一步：本人在原构建终端Ctrl+C，返回提示符后上传新ZIP/SHA至原根目录，解压到尚不存在的app-buildfix2，check/build。代码根改用app-buildfix2，继续沿用同级config/state/secrets/backups；不重新生成口令/配置、不覆盖旧app、不清理全局缓存、不停止其他容器。定时服务工作目录后续亦用新代码根。
- 迁移ZIP及SHA保持；尚未恢复资料/启动Web或worker，Phase 4未通过。安全更新镜像同步延迟限制已记录于服务器手册和验证文档。

### 2026-11-06 部署接续及首次构建修复（本节优先于后面的旧包说明）

本人已回传：原两包SHA一致，workflow、budget.sqlite、restored均ABSENT，COMPOSE_CHECK_OK。首次实际Docker构建在前端Vite阶段失败，`../../config/citation-display.json`无法解析；原Dockerfile没有保留web与config相对关系。现修复为/build/web与/build/config，最终COPY从/build/web/dist取产物。

- 最新部署包：[personalkb-deploy-20261106-buildfix1.zip](../reports/personalkb-deploy-20261106-buildfix1.zip)，268,045字节，SHA256 `1fc6370b691200a1ef404c6138d590a63860edf4ab8e222cb4f87a4a444b1fbd`，对应`.sha256`已生成；保留原包作为历史，不再用原包重试构建。
- BF01–BF02本机通过：旧布局失败、新布局隔离Vite成功，部署16/前端42通过；新包142文件SHA/CRC及解压后的前端布局检查通过，见[交付核验](../reports/phase4-20261106/buildfix1-delivery-check.json)。无Docker，本机不代表Linux镜像通过。
- 下一批：本人上传新部署ZIP和SHA至原服务器根目录，校验后仅解压到尚不存在的app-buildfix1；沿用同级config/state/secrets/backups，check/build，记录镜像ID和磁盘余量。以后命令从app-buildfix1执行，定时服务工作目录也需使用该路径。
- 原迁移包/SHA保持，不重新生成配置或口令，不重解压到已有app，不修改Nginx。服务器镜像重建、资料恢复及启动均待回传；未收费调用、未Git操作。

`ss`确认8768无监听，回环直连curl (7)连接失败。随后用户执行sudo docker ps -a（过滤com.docker.compose.project=personalkb）仅表头，没有容器；sudo docker image ls personalkb:local也无镜像。这支持当前后端尚未在预期项目/镜像名下构建启动，解释502；不再只停留“容器状态未知”的旧记录。

服务器用户目录：ubuntu@VM-0-15-ubuntu:~/my_rag/personalkb。已上传并解压的应用预期在app/，同级有config/、state/、backups/、secrets/及迁移ZIP。下一会话先用小批量命令核对实际路径和已有文件，不假定shell之前export的变量还存在。

## 项目与现成材料

本机D:/codex_project/My_RAG/PersonalKB，遵循上级AGENTS.md。服务器由本人自行执行并回传，无SSH访问配置。本人授权按Phase 4继续部署和迁移，常规已授权步骤不重复索要批准。

- [服务器操作手册](phase-4-server-guide.md)：从第三节继续，第一/二节已通过，不重新生成口令/覆盖配置。
- [部署约定](phase-4-deployment-contract.md)、[测试用例F401–F417](phase-4-test-cases.md)、[本机验证](phase-4-validation.md)。后端全量476通过5跳过44子测试、前端42及构建；后续部署15项定向通过，不能算作Linux Docker镜像实测。
- [部署包](../reports/personalkb-deploy-20261106.zip)，SHA256 `0572edaaed648246b1e37c6d736e9f2512ea67772a52dfc79aca6b1378be3844`。
- [迁移包](../reports/personalkb-migration-20261106.zip)，22,976,275字节，SHA256 `2bd53077976c89d7444d063eeb91e94ec043181d3b8d19b46842a9f34de1ced8`。不含.env，包含工作流及预算账本。
- [真实迁移本机恢复报告](../reports/phase4-20261106/migration-report.json)：4来源/6版本/5审核/4任务、3份eligible及本人99/100/100批准；79清单文件与永久证据验证通过。工程测试HTML仍未批准。无需重评。

## 执行顺序与验收

1. 核对app目录、公开配置、秘密文件存在/权限、迁移包SHA、state是否已有workflow或budget.sqlite。只输出必要路径/存在性，不读取或回传秘密内容。重新export STATE_DIR/CONFIG_DIR/SECRET_FILE/BACKUP_DIR及PERSONALKB_COMPOSE_PROJECT=personalkb，指向已有目录。
2. 在app目录执行`sh deploy/operate.sh check`及build。服务器此前sudo docker才能运行，优先显式sudo -E保留所需路径变量，或在命令中逐个传所需路径；不要擅自给用户添加docker组或修改Docker权限。遇依赖/网络/磁盘失败，先分析真实输出，不清理其他项目镜像/卷。
3. 验证迁移ZIP恢复到独立空目录，再将workflow/预算账本安排到尚不存在的生产目标路径。必须在子shell set -e等失败即停止流程下检查并移动，禁止覆盖现有库；若发现已有数据先核对/保留，不能用默认空库绕过迁移。
4. 启动独立项目web+单worker；确认容器状态/回环监听和HTTPS。Compose使用host网络，应用绑定127.0.0.1:8768，不需要ports映射或公网8768；仅信任本机Nginx代理。
5. 登录后只读核对来源/版本/审核/资格及预算账本。迁移后索引绝对路径变化需显式重建；不把本机214块索引ready扩大为云端可用，也不自动重新评分或未经费用同意调用模型。
6. 按手册继续云端认证报告、明确同意的真实导入/问答、任务恢复与资源共存、备份/恢复。可以先分阶段交付“部署迁移已通过/剩余4D项待验”，不得仅页面200就宣布Phase 4全部通过。

默认manual备份，私有OSS仅配置选择/显式启用；不要开通付费存储、上传到第三方或索要密钥。ASR沿本人C02已确认临时上传，正式音频OSS另有手动开关。生产每日备份验证后按auto_retention_enabled执行7日安全原片清理；初次迁移验收不要主动执行删除/保留清理。日志回传前避免凭据/签名URL泄漏。

## 协作边界

不停止/替换官网、小程序或原数据库，不改已通过的Nginx/证书，不使用docker compose down -v或全局prune。不自动commit/push/tag。若需修复代码，先列对应测试用例，再实现、验证，记录更新包及SHA，不能让用户在已解压旧版本上盲改。

每阶段及时更新本交接/专项验证、PLAN、TodoList、CHANGELOG；最终给可返回原会话核验的结论，区分已执行事实、本人观察和待验项目。用户需要每次一小批可复制命令及明确成功预期，不要一次倾倒完整大脚本。
