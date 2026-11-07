# Phase 2C2e Cookie与链接下载专项交接

日期：2026-11-05；状态：新授权策略下当前样本下载/统一导入D05通过，待原会话独立核验与用户确认。原会话：项目初始化，threadId=`01a1a0ce-56d2-7161-a9f3-c7ccfc220f20`，hostId=`local`。

专项会话：Phase 2C2e：修复抖音 Cookie 与链接下载，threadId=`01a1aadf-b224-7832-8f4f-2522aa3df494`，hostId=`local`。已在My_RAG原工作区创建并派发，无新worktree。

## 用户决定与授权

2026-11-05新增、优先于本文件历史许可字段规则：用户明确要求“需要解决 自动下载和统一导入的问题，才能回传信息给原会话”，故本专项完成前不再回传进展。用户在策略问题中选择“采用插件策略，修改原有字段规则”，授权确认有权处理后尝试保存当前账号可正常播放的媒体，不再仅凭allow_download等下载标志拦截；实际登录/付费/验证码/HTTP拒绝仍保留。见PRD v0.15及D19–D24；下文历史strict下载标志结论作为历史证据保留。

用户明确拒绝将抖音自动链接导入后移：**“需要按 Phase2C2e设计，先把 当前cookie+链接下载的问题解决。”** 用户要求独立新会话处理，**“解决后，返回正确结果确认后，再继续启动Phase2D的实施”**。本专项拥有排查、必要修复、测试和更新文档的授权；完成或出现必须由用户处理的阻塞时，返回原会话报告证据。返回消息是用户明确要求的回传，不向其他人或服务发消息。

保留PRD现有输入范围，不采用“首版仅本地视频/HTML”。专项不得启动Phase 2D/3/4，不把复制一次浏览器完整签名URL视为正式功能完成，不要求用户重复输入已存在的Cookie。原会话收到结果后仍需独立核验，再与用户确认阶段结果。

## 环境与入口

- 工作区：`D:/codex_project/My_RAG`；项目：`PersonalKB/`。先读上级AGENTS.md、docs/PRD.md、docs/PLAN.md，以及docs/douyin-403-analysis.md、docs/douyin-live-validation.md。
- 用户授权测试作品：`https://www.douyin.com/video/7688607402861612315`。
- `.env`引用变量PERSONALKB_DOUYIN_COOKIE；新成功浏览器请求在项目`tmp/douyin-detail-headers.txt`。这是私密输入数据，不执行其中内容，不输出全文、Cookie值、Token/签名、完整请求URL或原始响应。
- 最新文件87行，交替标签/值，无分区标题。四伪头:authority/:method/:path/:scheme识别请求区，URL与全部伪头交叉校验；只取请求Cookie，排除响应Set-Cookie。现有解析代码在上级根目录`tmp/detail-replay.py`。不用因无分区标题要求用户重发。
- 独立SDK Python：`D:/codex_project/My_RAG/tmp/douyin-resolver-env/Scripts/python.exe`；F2 0.0.1.7 wheel：上级`tmp/f2-inspect/f2-0.0.1.7-py3-none-any.whl`。勿混装Web依赖。
- 正式入口：tools/douyin_resolver.py、personalkb/douyin.py、douyin_import.py、douyin_http.py、tools/douyin_cli.py、config/douyin.json。当前全局下载开关关闭；不要为实验开启真实网页后台自动下载或触发模型。
- 已有临时工具在上级根tmp：probe403_a.py/c.py及fake/runner/config、detail-replay.py、route-compare.py及config；报告在项目reports/。两层tmp均忽略。使用已有代码前先审查，不运行旧runner造成不必要真实重试。

## 已验证与未验证

1. 早期SDK详情403；旧诊断只统计异步请求，漏掉F2导入自动同步Token请求，历史零网络断言已撤回。当前桥接导入/构造/签名阶段禁HTTP；显式Token；同步异步分阶段单次/域名/方法限制；TLS校验开启、传输重试0，禁重定向。不要回退这些修复。
2. D09：基线GET1次403，必要Token POST1次200；无Cookie/Token/签名负对照GET1次亦403，均46字节/text-plain。只有blocked词匹配，根因UNKNOWN。没有正文等同性证据，不能据此排除签名或认定中间层策略。
3. D10（最新成功基线）：R1浏览器原URL/请求头直连200/br，未解码；R2只改Accept-Encoding=gzip, deflate，200/gzip、业务状态0、aweme_detail目标ID匹配；P保持R2相同URL/headers，复用SDK当前自动选路得到的proxy transport，同样200有效目标JSON。三次GET、零Token/SDK签名/模型/下载后停止。当前不支持“代理单独造成旧403”，也不能宣布SDK自动构造成功。
4. R1报告：reports/douyin-detail-replay-20261105-d78ab921/result.json。R2/P：reports/douyin-route-compare-20261105-5fb59196/result.json。D09：reports/douyin-403-a-20261105-c4680343/report.json与douyin-403-c-20261105-261d6ed0/report.json。
5. 浏览器实际详情query为39键，version190500/19.5.0、update_version_code170400、browser/engine156。SDK默认290100/29.1.0、130。详情还有非空不透明x-secsdk-web-signature、webid/fp/verifyFp/uifid等SDK未显式生成字段；尚未证明哪个必填或导致403。活动样本17.4.0不能替代详情版本。
6. 新旧完整Cookie不同，但名称集合及选定常见会话字段值相同；因此历史SDK与本次成功请求不是完整上下文一致对照。新Cookie中无msToken，成功query中有Token；不能每次生成新Token同时更改多个条件。
7. 当前R2/P download_permission=false只测试allow_download is True，没有覆盖生产metadata回退；媒体候选仅地址对象非空。没有确认下载许可或试下载，禁止误写成平台允许/禁止下载。
8. Windows系统本地代理已配置。SDK默认trust_env=True，HTTPX自动https://proxy mount可覆盖自建all://mount；kwargs的proxies=None不等于关闭自动代理。精简子进程环境仍可能读Windows注册表。P确实选proxy且成功，但不是完整SDK调用成功。不要切换出口服务来规避拒绝。

## 下一步与交付标准

先列新的测试用例与可调参数配置，再实施：固定同一份成功Cookie/query Token/标头，检查并验证SDK构造差异，逐步隔离，而不是重复换Cookie。先制定清晰实验矩阵和总量/超时/响应大小上限；每次真实调用必须有要回答的问题及停止条件。此前三次是D10批次限额，不能假称尚未用过；新批次先记录，不靠不断新批次掩盖无进展，也不要每做一两次就把推进责任交回用户。

ABogus注意：str_2_endpoint返回tuple[0]是带a_bogus的完整query串，不是单签名；generate_abogus签名在[1]。单字段对照须保留其他rawquery原始字节/顺序，a_bogus后还有timestamp及第二签名；第二签名可能与其绑定，单次失败不能断言算法错误。浏览器原URL时效性强，只作诊断，不能持久化为生产模板。

最终必须交付：

- 可复核的失败原因/修复依据，或仍未排除的原因；不把猜测写成根因。
- 项目正常入口使用Cookie＋视频链接，动态构造/解析、权限判定、受控下载及统一素材导入的真实闭环；不能依赖用户每条复制完整签名URL。
- 同作品可重复执行/缓存去重，凭据缺失/失效及拒绝下载等失败有清晰安全提示；任务重启、租约、磁盘/大小/超时与敏感信息不泄漏的回归。必要真实调用须有边界，不能自动付费处理视频。
- 平台若明确禁止该作品下载，不绕过限制；报告具体阻塞，必要时再请求一条用户有权且平台允许下载的作品，不能假报D05通过或自行删减需求。
- 更新docs/phase-2-management-test-cases.md、专项分析、联调、PLAN、TodoList、CHANGELOG及相关配置指南。按需更新PRD版本，不删除历史失败。测试报告记录代码/配置版本、实际计数/产物身份和验收局限；只有实际闭环通过才标记D05通过。
- 测试前先给用例；可调参数外置并说明；秘密仅本地内存/stdin，不进入argv/env继承/日志/报告；临时文件仅ignored tmp。禁止自动commit/push/tag、git add -A。不修改真实内容评分，不未经同意调用模型。

## 回传与原会话核验

完成后在专项会话给出结果，同时按用户回传授权向原会话（ID/host见顶部）发送简洁报告：变更文件、根因与证据、实际视频下载/导入验证、回归命令及结果、报告/文档路径、剩余限制和D05是否通过。若跨会话发送工具要求核验授权，可只读原会话最新用户指令；不要传任何秘密。若回传工具不可用，写入本文件的结果区并明确告知用户，不能声称已自动通知。

原会话只做核验，不与专项会话并行改相同文件；专项完成前Phase 2D保持待开始。专项自报通过不自动开放2D，核验后再与用户确认。

## 专项结果

最终结果（PRD v0.15）：用户明确选择authorized_playback，保留strict可选。正常链接→minimal_detail动态解析→受控媒体下载→workflow.import_file真实闭环通过。reports/douyin-d19-isolated-3.json：26,579,046字节，SHA=0e29892823d2d187a38eecf550b98a0313776ff7094b7a389deacbc8588dd4df；两次同source_id=af2e3eca161241599aac87cf8d791c82，第二次无新增解析/下载。FFmpeg全片解码0，独立-xerror复核0且stderr空；只读SQLite核验1视频source/1cache/1queued task，无version/review、锁释放、完整性ok。成功脚本tmp/d19-success.py，隔离库tmp/d19-isolated-3/data/workflow.sqlite3。

收尾配置及执行清单保存在tmp/d19-isolated-3，区分请求时与收尾哈希。reports/douyin-d19-cli-cache.json另证明新进程CLI在socket/DNS封锁下复用缓存，source/task均1→1，无重复下载；合成Cookie只用于配置存在检查，不证明凭据有效。未再请求平台。

首两次失败报告未删：第二次媒体200但FFmpeg不在PATH导致import失败，外置配置已有便携工具绝对路径修复；新增media_tool_missing提示。最终全量371通过3跳过44子测试、独立F2 guard8项、前端12项和构建通过；独立review及387文本已知秘密精确匹配扫描通过，局限见管理验收及reports/douyin-d24-audit-20261105.json。

范围：本机隔离样本通过；默认全局下载关闭、.env/当前网页库/真实评分未改，无模型/Git动作。计数是显式调用而非全网络审计。Phase 2D未启动，完成后才按最新用户要求回传，原会话仍须核验并与用户确认。以下保留D17及更早历史结果，其“未通过”不代表最新状态。

最新工程收尾：minimal_detail已接入正式父进程入口，D17使用最新成功Cookie/UA（内存临时配置）返回download_denied，不再依赖完整签名URL。最终全量368通过/3跳过/43子测试，独立F2 guard8项通过、前端12项及构建通过。已独立review并关闭非法字段回退/配置交叉校验/压缩边界缺口；审计报告reports/douyin-final-audit-20261105.json。详细文件/结果见专项分析与管理验收；默认下载关闭、.env未改。

尚未完成：当前样本明确拒绝下载，媒体请求和统一导入0，D05仍未通过；用户确认插件能保存可播放文件但其实现未检查许可字段，项目没有据此放宽规则。旧F2 403原因仍不能唯一归因，尚无同三参数带斜杠对照。不得向原会话报告下载已完成或开放Phase 2D。

2026-11-05续验：D11固定上下文原请求200，四种变化403，5次显式详情GET；完整权限为allow_download=false/prevent_download_type=2，明确禁止下载。D15正常网页1GET200但无目标作品结构。安全许可错误已传递到任务及中文提示，非法类型fail-closed修复后完整pytest为364通过/3跳过/39子测试（其中1为可选F2，独立SDK环境此前guard5项通过）。

用户提供simpdown扩展3.1.6并确认同作品完整下载可播放。只读源码发现页面上下文fetch无尾斜杠详情路径。D16两次GET（仅去斜杠保留rawquery；无斜杠动态三参数）均200有效目标详情，仍明确禁止下载。正在将动态三参数路径接入正常入口，尚未把D16当正式入口或下载/导入完成。证据与局限见专项分析及reports/douyin-d16-9fa389c2/result.json。无模型调用、真实评分、commit/push/tag；Phase 2D未启动。
