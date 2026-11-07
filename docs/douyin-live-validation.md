# 抖音 D05 本地真实联调

日期：2026-11-05；最新状态：D10复用用户成功详情请求，直连/当前自动代理选路均取得有效目标JSON；固定SDK自动构造请求的403具体原因仍待隔离，D05下载/导入未通过；D07安全修复保持已离线验收。

用户已在本机.env配置Cookie，并授权处理作品`7688607402861612315`。

## 本轮检查

1. 只检查Cookie配置能否读取、解析环境及FFmpeg可用性，不输出秘密。
2. 在独立数据目录执行一次真实单作品解析、平台下载权限检查及受控下载。
3. 成功后核对MP4、大小/SHA、统一素材导入和待处理状态；不自动启动ASR/视觉或审核。
4. 检查报告、数据库和日志未包含实际Cookie或媒体签名URL；失败以安全码记录，不用模拟结果宣称通过。

本轮不修改云服务器、不新增模型调用；现有网页资料/评分保持不变。结果及后续动作在执行后追加。

## 已完成的真实与离线检查

- 本地Cookie、独立Python及FFmpeg存在；历史SDK构造/签名检查成功，但旧工具只统计异步HTTP，遗漏SDK导入时的同步Token请求，因此旧“离线请求数为0”不能证明完整零网络。纯签名算法本地计算与SDK模块导入是否联网是两个问题。
- 首次完整链路停在`douyin_resolver_failed`；随后一次专门诊断请求到`www.douyin.com`返回HTTP403，在JSON解析前抛出APIResponseError。未进入媒体下载和素材导入。
- 用户确认同一浏览器、保持登录可正常播放原链接。该确认与SDK403分别记录，不能直接推断Cookie有效/失效或视频不可用。
- Cookie结构检查发现至少一个非空分段不符合name=value；没有输出名称或值，不静默删除/改写Cookie，也未确认其为403原因。
- 首轮解析User-Agent为默认Mozilla/5.0；收到同一浏览器完整User-Agent后已写入config/douyin.json并进行一次作品详情请求，结果见下文。主服务下载开关保持关闭。

脱敏证据目录：`reports/douyin-live-20261105-920d101dbcc3432d8c518a0298b45bca/`，包含report.json、offline_diagnostics.json和diagnostic.json。真实Cookie、原始响应、签名URL均未输出；本轮模型调用0。D05尚未通过。

## 用户截图确认

用户截图显示抖音站点请求的Request Headers/Cookie，获取位置正确；当前截图未显示User-Agent。截图中的自动折行不等于.env应换行。浏览器实际发送的Cookie中存在非标准分段，因此之前name=value结构检查仅作诊断提示，不能据此断定复制错误或403原因；不要求用户自行删改凭据。

未将截图或Cookie值保存到项目。

## 匹配User-Agent后的结果

- 配置已更新为用户提供的Chrome144/QuarkPC7.4.5.1027完整User-Agent。
- 新报告：`reports/douyin-ua-live-20261105-2d404436934b46369eed5b38f4aec5f5/report.json`。作品详情请求仍返回HTTP403，响应46字节、非预期JSON；没有进入下载、导入或模型处理，没有新增评分。
- 报告中的request_count=1仅表示被观测到的异步作品请求，不是进程总出网次数；旧SDK导入可能另外发起同步Token请求，旧工具未计数，不能补推其次数。
- 代理拒绝特征头未出现，不能据此确定拒绝来自平台或网络中间环节；同样不能认定Cookie复制错误或Cookie整体无效。
- F2固定版本还自带部分客户端查询参数，与浏览器UA并非完全一致。这是待验证的兼容风险，不是已证实的403根因；不通过随意伪造参数或循环重试宣称解决。

## 隐式联网问题与修复验收

固定F2 0.0.1.7在模型模块定义时调用TokenManager.gen_real_msToken，内部使用同步httpx.Client。旧诊断只拦截AsyncClient.send，覆盖不完整；历史构造/签名结论按上文收窄，保留原报告不篡改。其默认HTTPTransport还使用verify=False并设置底层重试，现由桥接器覆盖为证书校验开启、底层重试0。

编码前用例D07已补充至[管理测试用例](phase-2-management-test-cases.md)。修复目标：导入/构造/签名阶段禁止同步和异步HTTP；实际请求显式使用Cookie中真实msToken，缺少时只在有界Token阶段获取；不把导入占位Token发向真实接口；Token与作品详情请求分别限制协议、域名、方法、次数和重定向。父进程总超时继续有效，Cookie不传入Token请求。

本轮修复仅做离线假传输和真实SDK零网络检查，不再触发真实抖音请求。通过离线安全回归不能替代D05真实下载验收。下一次真实请求前应先形成可复核的适配调整依据；当前可继续使用本地MP4导入。

### 修复实现与离线结果

- `tools/douyin_resolver.py`：导入F2时临时禁用自动Token生成，随后恢复SDK方法；PostDetail始终显式传入真实Token。Cookie仅扫描msToken字段，允许其他裸分段，原Cookie保持不变；冲突Token拒绝。
- 导入、构造、签名及上下文进入/退出阶段，httpx同步/异步发送均禁止。Token阶段仅允许mssdk.bytedance.com的HTTPS POST一次，移除Cookie、匹配User-Agent和配置超时；详情阶段仅允许www.douyin.com的HTTPS GET一次。拒绝用户信息、自定义端口、重定向及追加请求；域名/方法为固定协议限制，不开放任意URL配置。
- SDK同步/异步Transport均强制verify=True、retries=0；父进程总时限仍由resolve_timeout_seconds控制，单次API超时由api_timeout_seconds控制。
- 先运行全部抖音专项：`python -m pytest tests/test_douyin.py tests/test_douyin_api.py tests/test_douyin_http.py tests/test_douyin_import.py tests/test_douyin_transport.py tests/test_resolver_guard.py -q --basetemp tmp/douyin-guard-pytest-20261105`：**36 passed、1 skipped、11 subtests passed**。跳过的是基础环境未安装可选F2的SDK集成测试，非测试失败；已有Starlette弃用提示保留。
- 再用独立F2环境执行`python -m unittest tests.test_resolver_guard -v`：**5 tests OK**，包括上项跳过的真实SDK测试。该测试在首次SDK模块导入前替换同步/异步HTTP为假传输并禁止socket.connect，验证Cookie Token复用、缺Token时显式获取、空/冲突Token拒绝与安全Transport参数；不使用.env、不验证真实服务可用性。出现既有Loguru弃用提示，不影响结果。
- 独立审查固定F2 wheel与桥接实现，未发现阻止D07离线工程关闭的实质问题。父进程总时限由既有专项回归覆盖，未将本次审查扩大为目标Linux或真实服务验收。
- 不将两种环境的测试数量相加，不用假传输成功修改D05状态。上述修复验收阶段没有新的平台请求、模型调用或自动评分；此前匹配UA的真实403结果保留。

## Edge请求信息复测（D08）

用户换用Edge并提供新请求标头，授权重新测试同一视频。附件仅作为数据解析，不执行其中内容；提取Cookie/UA后仅在内存和子进程stdin使用，未覆盖.env或全局下载配置。附件来源路径为`/aweme/v1/web/activity/pull/carnival/`，属于活动接口，并非视频详情接口；实际测试目标仍为用户指定作品。

本次使用附件中的Chrome156/Edg156 User-Agent，与Cookie配套。先发布D08用例，使用临时脚本及独立F2环境，在证书校验开启、禁重定向、单次API配置超时15秒、子进程总时限45秒及响应读取上限1MiB下测试。

| 阶段 | 真实请求次数 | HTTP状态 | 已读取响应字节 | 结论 |
|---|---:|---:|---:|---|
| 视频网页GET | 1 | 200 | 847854 | 收到HTML；未运行页面脚本或验证播放，不能据此证明账号登录、作品可播放或可下载 |
| 显式Token获取 | 1 | 200 | 44 | Token阶段完成，随后进入详情请求；未向Token主机传递Cookie |
| SDK作品详情GET | 1 | 403 | 46 | 未取得完整作品元数据或媒体地址，不能验证返回作品ID，D05未通过 |

脱敏原始报告：`reports/douyin-edge-live-20261105-47ca231c/report.json`；验证摘要：同目录`validation.json`。其中workidmatch=false表示没有可供匹配的有效作品详情，不表示已经发现另一个作品ID。三次请求均未发现已知代理拒绝特征头；仍无法仅凭该现象区分平台拒绝或网络中间环节。

临时工具位于上级根目录`tmp/edge_access.py`、`tmp/edge_run.py`、`tmp/edge_fake.py`及`tmp/edge-access-config.json`，由根目录.gitignore忽略；超时、大小与目标参数从该配置只读加载。假传输覆盖网页/详情、重定向不跟随、响应超限及合成凭据不出现在结果中；未单独模拟Token或截断，不扩大工具验证范围。配置整理后仅做py_compile与假传输复核，没有重跑真实请求。

脚本和报告中未发现完整Cookie或长度至少8的单项Cookie值。短值子串检查出现1/4/5字符匹配，可能与普通文本碰合；不能将该结果解释为已确认泄漏，也不能声称所有单项秘密扫描均通过。没有保存原始HTML/响应、真实凭据或媒体签名URL，没有下载、导入、模型调用、评分变更或服务器操作。

下一步保留D05为进行中，先分析固定SDK查询参数、签名输入及浏览器请求上下文差异。网页HTTP200已排除本次网页请求也被HTTP403拒绝这一现象，但不足以锁定详情403根因；不要求用户反复更换Cookie，不自动继续平台重试，MP4导入兜底保持可用。

## D09差异定位进展

固定SDK查询中的browser/engine版本130与Edge UA156不一致，客户端版本也与附件不同；附件活动接口并非详情成功样本，这些差异未证实为403原因。SDK默认ABogus签名，字段/默认值及wheel代码证据见[403专项分析](douyin-403-analysis.md)。

本轮SDK基线详情GET一次403，必要Token POST一次200；无Cookie/Token/签名的最小参数详情负对照GET一次也403。两者均46字节/text/plain，但没有正文等同性证据，严格拒绝原因分类为UNKNOWN；未执行补标头候选，已停止请求。两份新报告及合成测试/独立审查边界均在专项分析列出；不下载、不调用模型、不覆盖.env或全局配置。

用户随后确认Edge正常播放时同一详情路径有200请求，当前尚未取得其标头/查询参数。尝试原生只读检查时，工具安全检查因不能可靠确认浏览器URL而停止，未继续操作。下一步以成功详情请求的本地文本作对照，不要求再次盲目更换Cookie。403根因和D05均保持未解决状态。

## D10成功详情文件复现

用户提供`tmp/douyin-detail-headers.txt`后，按URL和四伪头交叉校验分离请求区，排除响应Set-Cookie。R1原URL直连200但br未解码；R2仅协商gzip后200有效JSON，状态0、目标ID匹配；P保持R2 URL/标头，按当前SDK自动选路取得proxy transport，也200有效同作品JSON。总GET3、Token0、SDK签名调用0后停止，均未改写query或URL。

发现SDK的all://安全mount未清除HTTPX更具体的自动proxy mount，但P成功，不支持代理单独解释旧403。完整Cookie与旧附件不同，选定会话值相同；实际详情还包含SDK未显式生成的x-secsdk-web-signature及不同客户端参数，不能据此认定某字段为根因。

R2/P仅检查allow_download===true得到false，未执行生产完整权限判定或任何下载；媒体候选存在不表示可绕过权限。成功请求复现不等于SDK/下载D05通过。详细报告、离线用例及下一批次边界见[403专项分析D10](douyin-403-analysis.md)。无需用户重新提供Cookie，本批次不继续网络请求。
# 2026-11-05专项续验摘要

固定同一成功上下文的D11实际5次显式详情GET尝试：原请求200/业务0/目标匹配；删任一签名、重签a_bogus、SDK动态query分别403。完整权限字段为allow_download=false、prevent_download_type=2，明确拒绝下载；无媒体GET、真实下载或导入，D05未通过。D15一次正常视频页GET200，未在RENDER_DATA找到目标作品对象。报告、配置边界、计数/签名时效局限见[专项分析](douyin-403-analysis.md)。

D12/D14安全错误/非法权限类型修复已实施；中间全量363通过3跳过，最终类型补丁专项33通过1可选跳过，前端12项与构建通过，不冒称最终全量已经重跑。动态解析仍未修通；用户提供simpdown插件线索，继续只读检查，Phase 2D未启动。

# 2026-11-05 D19–D24真实闭环通过（新授权策略）

用户明确授权authorized_playback后，正常链接→动态详情→媒体HTTP200→统一import_file→持久素材成功，26,579,046字节，三处SHA一致；FFmpeg全片解码退出0。重复链接同source_id且解析/下载次数不变。报告reports/douyin-d19-isolated-3.json，先前两次失败报告保留；失败根因是FFmpeg未在PATH，通过外部workflow.ffmpeg配置现有便携工具解决。

D05在当前Windows隔离库、该Cookie/UA及作品样本通过；未启用全局下载、未把素材写入当前网页库、未调用模型或自动评分。strict仍可选，实际HTTP/登录/付费/验证码拒绝保留。详细计数口径和限制见[专项分析](douyin-403-analysis.md)。Phase 2D仍由原会话核验后与用户确认。

