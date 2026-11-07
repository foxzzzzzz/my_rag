# 抖音详情403差异分析与有界验证

## 最新结论：D19–D24真实下载与统一导入通过（2026-11-05，PRD v0.15）

用户明确采用authorized_playback策略后，保留strict显式可选。新策略从已成功校验状态/目标ID的详情中选择平台返回的play_addr，用户仍须确认有权处理；不再用下载标志单独拦截。媒体请求仅发送User-Agent及配置的固定Douyin Referer，不发送Cookie/Authorization；公共IP校验并固定连接、TLS、逐跳域名校验、大小/磁盘/超时保护不变。不是复制插件代码或浏览器签名URL，也没有执行扩展、换出口或重签媒体地址。

真实失败记录保留：`reports/douyin-d19-isolated.json`首次返回通用错误，不能据此推断CDN拒绝；第二次`reports/douyin-d19-isolated-2.json`安全堆栈及HTTP200证明已下载并进入workflow.import_file，失败为配置ffmpeg在PATH不可用。项目已有版本化便携FFmpeg文件，用成功隔离workflow配置的ffmpeg绝对路径解决，无须安装或持久修改系统PATH；缺工具错误现保留为media_tool_missing并显示中文提示。

成功证据：`reports/douyin-d19-isolated-3.json`。以原视频链接从正常DouyinImporter.enqueue/process_next进入，解析器/下载器使用真实实现，仅调用包装器记录计数，统一调用workflow.import_file；首次任务succeeded，媒体HTTP200。下载/入库/素材记录SHA256均为`0e29892823d2d187a38eecf550b98a0313776ff7094b7a389deacbc8588dd4df`，26,579,046字节。素材ID为`af2e3eca161241599aac87cf8d791c82`；第二次相同链接succeeded且相同source_id，解析/下载计数保持1/1，未再次发媒体请求。FFmpeg全视频解码退出0；本机没有ffprobe，报告明确null，不冒称已测。

验收范围：成功Cookie/UA、当前作品、Windows本机隔离数据目录；任务保持queued，无模型处理、评分或正式知识批准。计数是显式call-through及opener次数，非全进程出网审计；model_calls=0由普通导入路径及queued状态支持，非模型流量拦截计数。三轮分别保留，不只报告最后一次。原始媒体URL和凭据不落库/报告。默认全局enabled=false、.env未改，真实网页库未增加此验收素材。

本专项D05已按新授权策略通过当前样本动态解析/受控下载/统一导入/缓存闭环；不推广为所有抖音作品均可下载，不关闭旧F2 403唯一归因问题。Phase 2D仍待原会话独立核验并与用户确认。此前“完成前回传进展”已按最新用户要求停止，完成核验后才回传。

## D17：正常解析入口动态构造已取得明确许可结果

`config/douyin.json`新增minimal_detail默认模式及显式f2模式，aid/version_code/详情响应上限外置并校验。桥接器对固定无斜杠端点动态构造三参数，使用Cookie/UA与最小固定标头，直连trust_env=false、TLS校验、零重试、禁重定向；原始/解压各受max_detail_response_bytes限制，gzip/deflate有界解码，拒绝其他编码。正常父进程总时限和stdin秘密传递保持。

D17通过正常resolve_with_f2兼容函数（内部选择minimal_detail）真实执行一次，使用最新成功请求中的Cookie/UA，仅在内存临时配置enabled与解析Python，返回download_denied。metadata只在作品ID与状态校验通过后返回该错误，因此证明动态入口取得了目标详情及明确许可结果；没有依赖浏览器完整签名URL或额外Token。报告`reports/douyin-minimal-d17.json`保存执行时代码/配置哈希；守卫最多1 GET/0 POST，未对实际网络次数单独埋点，不把上限当计数。

该报告未保存实际临时配置指纹及凭据身份哈希，磁盘配置哈希仅代表模板；真实执行的UA/解析路径/启用开关有内存覆盖，不能据模板重放或宣称当前网页配置已启用。未覆盖.env，默认开关关闭，未请求媒体/导入/模型或评分。仍需允许下载样本验证完整D05；旧F2 403具体机制尚未唯一归因。

## simpdown线索及D16新进展（2026-11-05）

用户截图确认simpdown的抖音视频下载器3.1.6；本机对应扩展ID为`ohgljnhmogbogimdfgjjmicldlekffih`，只读检查安装文件，未运行/修改扩展、未读取浏览器凭据库。官方条目：https://microsoftedge.microsoft.com/addons/detail/douyin-video-downloader/ohgljnhmogbogimdfgjjmicldlekffih 。

静态代码`content-scripts/content.js`注入`fetcher.js`，通过postMessage让页面上下文主动fetch详情。`fetcher.js:265–271`使用无末尾斜杠的详情路径，构造aid/version_code/aweme_id三个参数，credentials=include。作者注释称页面hook补充签名及路径差异影响验证；这些说明只作线索，不能视为本项目动态证明。background选择video.bit_rate/play_addr等候选；媒体下载存在iframe/blob、downloads、改写CDN Referer/Content-Disposition及备用offscreen路径。所审代码没有allow_download/prevent_download_type/prevent_download判定；用户已确认同作品通过插件保存完整MP4且可播放，这是用户侧实测，尚非本项目下载入口验证。

D16按固定Cookie/标头、gzip、直连TLS/禁重定向/零重试、15秒/1MiB/间隔1秒执行两次GET：A仅删除成功URL路径末尾斜杠、保留rawquery；B改为同无斜杠路径，只动态构造aid=6383/version_code=190500/aweme_id。两者均200、业务0、目标ID匹配。B没有复制签名参数，是新的自动解析可行证据；不能推广为所有Cookie/作品均可用，也尚未隔离精简标头及三参数带斜杠的因果对照。两次均明确download_denied，未请求媒体。

报告`reports/douyin-d16-9fa389c2/result.json`包含文件哈希/运行版本/限制和显式尝试计数；临时工具根tmp/d16.py及配置，4项封socket离线测试通过。D11/D15与历史请求分别保留，不能写成总共只发2次请求。

下一步将该动态路径接入正常解析入口，参数外置，保持权限检查和流量边界；默认下载开关仍关闭。插件能下载与接口禁止字段并存，不能用前者覆盖后者。D05真实下载/统一导入尚未通过，Phase 2D保持待开始。

## 2026-11-05专项续验：D11/D12/D14/D15

D11固定成功请求的Cookie、query Token和标头，协商gzip，显式直连/TLS校验、零重试、禁重定向。外置配置上限8次GET、单次15秒、原始/解码正文1MiB、间隔1秒、循环截止240秒；实际5次显式GET尝试、无Token POST。该计数来自执行循环，非全进程网络审计。报告：`reports/douyin-d11-a29a12c6/result.json`，离线审计：同目录`audit.json`。

| 对照 | 结果 | 解释边界 |
|---|---|---|
| 原浏览器请求 | 200、业务0、目标ID匹配 | 完整上下文可用，不证明Cookie单独足够 |
| 仅删除第二签名 | 403 | 改变后失败，未证明独立必填性 |
| 仅删除a_bogus | 403 | 同上 |
| 保留其余rawquery，仅替换本地生成a_bogus | 403 | 签名输入包含timestamp和旧第二签名；绑定与时效混杂未排除 |
| 固定同Token/标头，SDK PostDetail动态构造 | 403 | 动态入口尚未修通，不能用原签名URL作正式实现 |

成功基线返回`video_control.allow_download=false`、`prevent_download_type=2`，顶层`prevent_download`缺失。完整生产metadata明确判定`download_denied`，因此媒体GET、下载产物及统一导入均为0，D05未通过。与D10单字段false统计不同，本次有明确禁止字段证据。未执行结束基线，不能彻底排除签名时效影响；不能据负对照直接认定ABogus算法错误或403来源。

D11工具4项合成测试在封锁socket.connect/connect_ex后重跑通过，扫描脚本/配置/报告未命中完整Cookie或长度至少8的选定凭据值。审计记录运行版本与依赖哈希；resolver哈希仅为审计时文件，不能追认为请求时版本。临时工具在根`tmp/d11.py`及配置；解码器引用replay配置，两个上限当前同为1MiB。

独立源码复核：SDK模型28键、成功浏览器query39键；PostDetail会静默丢弃webid等额外字段，客户端/浏览器版本及设备参数亦有差异。当前SDK签名前缀与HTTPX实际rawquery一致，未证实签名后编码失真。固定wheel ABogus返回tuple[0]是含a_bogus的完整query，tuple[1]才是单签名；生产model_2_endpoint已正确取[1]，历史“[0]是原params”表述应以本更正为准。

D12/D14修复：明确拒绝跨字段优先；存在但类型非法的权限字段不能被另一允许字段掩盖；未知许可安全拒绝。两个许可错误经解析子进程、父进程白名单、持久任务到网页固定中文提示传递，未知异常不透传。先发用例再实施，最后补类型冲突测试。中间全量快照363通过/3跳过/34子测试；最后类型补丁后专项33通过/1可选SDK跳过/29子测试，独立F2环境此前5项离线guard通过；最后补丁后的全量仍需重跑。前端12项和构建通过；不把不同快照的数量相加。

D15另验证正常视频页结构化解析：仅1次GET、HTTP200，原始189960字节、解压861585字节；RENDER_DATA JSON字典存在，未找到目标aweme_id作品对象，未形成正式解析路径。报告`reports/douyin-d15-d7187f78/result.json`；4项离线测试通过，工具及2MiB外置配置在根tmp。不执行页面JS、不处理验证，200不证明登录/挑战状态；未下载。

用户随后提供simpdown扩展线索，继续只读调查其浏览器上下文实现；不将扩展按钮可用当下载许可，不启动Phase 2D。无需重复Cookie。

日期：2026-11-05。范围：作品`7688607402861612315`，本机固定F2 0.0.1.7与用户Edge请求信息。最新D10已取得有效同作品详情JSON，直连与当前自动代理选路均200；旧SDK自动构造请求的403具体原因仍未锁定，D05下载/导入未通过。不把请求复现成功等同SDK兼容或平台许可。

## 已有证据

此前Edge实测网页200、显式Token200、SDK详情403，各请求一次，详见[真实联调记录](douyin-live-validation.md)。网页200只证明收到HTML，Token200只证明该阶段完成，都不能证明视频详情身份、播放或下载资格。

附件是`/aweme/v1/web/activity/pull/carnival/`请求，并非`/aweme/v1/web/aweme/detail/`。用户本轮已确认Edge正常播放时存在详情请求，状态为200。此为用户侧观测，当前尚未取得该成功详情请求的实际标头、查询参数或响应结构；不能用活动请求替代它。

## 固定SDK与附件的差异

以下行号指本机固定wheel内文件：上级`tmp/f2-inspect/f2-0.0.1.7-py3-none-any.whl`。不访问或引用其他滚动版本来推断本机行为。

| 项目 | 固定SDK/当前桥接器 | 用户Edge附件 | 能得出的结论 |
|---|---|---|---|
| 接口 | `api.py:55`定义详情路径；`crawler.py:175`构造签名后GET | 活动接口 | 路径不同，附件不能作成功详情响应证据 |
| User-Agent与查询版本 | 桥接器传入UA156，但model继承browser/engine版本130.0.0.0 | UA和查询参数为156 | 存在确定的不一致，尚未证明导致403 |
| 客户端版本 | version_code=290100、version_name=29.1.0 | 170400、17.4.0 | 确定存在差异，两个接口的参数语义未证明等价 |
| 详情参数 | `model.py:11`基类、`:203`PostDetail；桥接器显式给aweme_id/msToken | 活动查询另有webid、verifyFp、fp、uifid | 当前详情路径不注入这些字段；不能仅凭活动请求认定详情必填 |
| 签名 | `conf/conf.yaml:23`默认ab；`crawler.py:97`选择ABogus；`utils.py:653`添加a_bogus | 活动查询也存在a_bogus | 算法/字段名称存在不证明签名正确；备用XBogus路径在utils.py:607 |
| 标头 | 桥接器显式UA、Referer、Cookie，并叠加HTTPX默认标头 | 另有Accept-Language、sec-ch-ua及sec-fetch等 | 应比较构造后的标头名称，不因kwargs没写Accept就断定实际缺失 |
| 网络与传输 | 当前强制TLS校验、禁止重定向和底层重试，导入/构造/签名阶段禁止HTTP | 浏览器有其连接与会话上下文 | 现有附件没有TLS/HTTP协商与同接口响应证据，不能断言某指纹造成403 |

`api.py/model.py/crawler.py/utils.py`均位于wheel的`f2/apps/douyin/`；`conf/conf.yaml:25`记录固定客户端默认值。实际桥接实现见`tools/douyin_resolver.py`。未复制附件、凭据、签名URL或原始响应到文档。

## 验证边界与停止条件

编码前D09已写入[测试用例](phase-2-management-test-cases.md)。先以合成数据验证诊断分类、秘密不输出及既有超时/次数/大小边界，再进行固定SDK基线观测。原始响应仅在内存匹配预定义策略措辞/诊断标记，落盘仅枚举、布尔值、HTTP状态、长度和受控类型。

本轮上限为目标详情GET三次、必要Token一次，不包含历史测试；这是上限而非必须用满。先执行基线；出现明确策略/robots拒绝或有效详情立即停止其他候选。只有基线无法解释时，才考虑复用完全相同URL、Cookie、UA，仅补附件可确认的浏览器标头；必要时用无Cookie/Token/签名的最小参数作负对照。负对照失败不能解释成用户登录失败。

不批量尝试版本/签名组合，不更换网络出口、代理或TLS指纹，不处理验证码或绕过访问限制，不放宽域名/权限/下载限制。全局配置与.env不变，没有模型调用、素材下载、评分或服务器改动。

## 尚未排除的原因

| 假设 | 当前状态 |
|---|---|
| Cookie失效/复制错误 | 未证实；网页200与用户可播放都不是该SDK详情身份的充分证明 |
| 请求参数/签名不兼容 | 已证实存在版本差异，但没有因果实验或成功浏览器详情对照 |
| 标头或会话上下文差异 | 存在差异；活动接口标头不能替代完整同接口对照 |
| 平台端访问策略 | 尚未证实，403本身不足以确定来源 |
| 网络中间层或本机执行环境策略 | 尚未证实；历史报告缺少原始拒绝语义分类，无特征头不表示不存在中间层 |

## 本轮真实验证结果

| 实验 | 条件 | 真实观测 | 可解释范围 |
|---|---|---|---|
| A：当前SDK基线 | Edge附件Cookie/UA，现有签名/模型参数，必要Token一次 | Token POST1次：200/44字节；详情GET1次：403/46字节，text/plain | 复现当前失败；正文仅匹配blocked预定义词，严格策略分类UNKNOWN，不能归因登录/签名/平台风控 |
| C：无凭据负对照 | 同详情路径，只带aid和aweme_id，不带Cookie/Token/签名 | 详情GET1次：403/46字节，text/plain；诊断UNKNOWN | 此负对照也被拒绝；它同时改变多项参数，不是签名的单变量实验 |
| B：仅补浏览器标头 | 计划在条件充分时复用同一签名URL作对照 | 未执行 | 成功浏览器详情标头尚缺；没有消耗剩余额度或盲目组合参数 |
| 用户Edge浏览器 | 正常播放该作品时观察详情请求 | 用户回复“有，200” | 浏览器可获得详情成功状态；尚非工具读取/完整响应内容验收 |

原始脱敏证据：

- A：`reports/douyin-403-a-20261105-c4680343/report.json`。
- C：`reports/douyin-403-c-20261105-261d6ed0/report.json`。
- 本轮观测累计**详情GET2次、Token POST1次、网页GET0次**，不同于此前D08批次；完成后停止，没有后续请求。

A、C只确认HTTP状态、字节数和MIME一致，没有正文等同性比较，不能写成“相同响应正文”。C响应含Via；已检查的代理拒绝特征头未出现，TLS issuer对mitmproxy/openai两个名称的标记为false。Via不能证明转发节点生成403，标记未匹配也不能排除中间层。

根目录临时工具为`tmp/probe403_a.py`、`probe403_a_fake.py`、`probe403_a_runner.py`、`probe403_c.py`、`probe403_c_fake.py`、`probe403_c_runner.py`及外置JSON配置，均被忽略。以独立F2环境分别执行两个fake脚本，均退出0：A覆盖策略分类、未知分类、正确作品JSON、超限、重定向；C覆盖分类、无Cookie及指定查询键/主机、重定向、超限和合成数据脱敏。主Agent独立重跑确认通过，没有重跑真实请求。

测试限制：A fake使用合成Token，未覆盖Token网络分支或独立第二次send拦截；C fake未独立验证TLS信息分类或累加transport调用次数。C runner写入的batch_counts/fake_validation是汇总常量，不能把报告本身当作动态执行证明；实际计数依据A/C各自响应事件、单次调用代码及执行记录交叉核对，不宣称完整进程网络审计。未发现完整Cookie或长度至少8的单项Cookie值出现在A报告；短值子串碰合不能证明泄漏，也不能声称全部敏感值扫描通过。C不读取Cookie。

## 当前定位与下一步

**已确认请求存在差异，尚未锁定403根因。** 用户报告浏览器同路径200，说明不能将当前情况描述为详情接口整体不可用；程序侧两类请求403不足以区分SDK参数/签名、会话状态与请求路径上的策略差异。

独立审查确认上述结论没有更强归因依据。不把版本130与156不一致直接当根因，不因为无凭据请求也403就排除签名/Cookie问题，不声称通过修改UA或关闭校验能解决。

用户确认浏览器详情200后，尝试通过computer-use只读取得当前Edge请求上下文。浏览器连接器未接入Edge，仅发现原生窗口；原生工具因无法可靠确认当前浏览器URL而由安全检查停止。已停止UI操作，没有刷新页面、重放请求或取得成功详情标头；不绕过该限制。

当时下一步为取得成功详情请求的本地文件；用户现已提供，D10结果如下。D09历史结论保留，不将后续请求计入其批次，不重放无关活动接口。

## D10：成功详情原请求复现及选路对照

### 输入解析与确定差异

输入为被忽略的`tmp/douyin-detail-headers.txt`，87行交替标签/值，没有明确分区标题。不能把全部文本直接转为标头字典：前部包含响应Set-Cookie，后部才是请求Cookie。采用四个连续HTTP/2伪头`:authority/:method/:path/:scheme`识别请求区，并将URL的主机、协议、方法、路径及完整原始query与伪头逐项交叉校验；不依赖乱码的首行标签。响应Set-Cookie未转发，伪头由HTTP客户端生成。

确认请求目标、作品ID正确，query有39个不重复键，签名不在query末尾。实际详情版本为190500/19.5.0，update_version_code仍为170400；浏览器/engine为156.0.0.0。不能将旧活动样本的17.4.0直接当详情版本。另有timestamp和非空不透明的x-secsdk-web-signature，固定wheel中没有显式生成该字段的实现；字段存在和代码缺失仍不能证明它是必填项或403的唯一原因。

与旧Edge活动附件相比，完整Cookie已变化；Cookie名称集合与选定的五项常见会话Cookie值相同（仅比较布尔，不记录值），所以历史SDK批次不是同一份完整请求上下文。新文件Cookie中没有msToken，实际query中有msToken。本次全部复用浏览器query，不额外请求Token。

### 请求与结果

先发布D10用例，随后依据首轮编码结果补充压缩协商与选路对照的测试条件，**总计最多三次GET**，没有获取Token或调用SDK生成签名。

| 实验 | 唯一处理/对照条件 | HTTP与有效性 | 请求次数 |
|---|---|---|---:|
| R1 | 原始浏览器URL及可转发请求头，显式直连 | 200/application/json，br压缩18213字节；当前环境不支持br，未判断正文JSON | 1 |
| R2 | 仅Accept-Encoding改为gzip, deflate，其余URL/Cookie/UA/标头不变，仍直连 | 200、gzip，19141原始/102911解码字节；JSON字典、业务状态0、目标ID匹配，有媒体候选 | 1 |
| P | 与R2完全相同URL和标头，使用当前SDK客户端构造方式选出的既有自动代理transport | 200、gzip，19137原始/102918解码字节；同样业务状态0、目标ID匹配，有媒体候选；实际子进程uses_proxy=true | 1 |

三次均保留原始query字节，URL normalization=false；TLS证书校验保持、禁止重定向与重试、API15秒/子进程45秒、原始/解码正文各1MiB上限。没有修改系统代理、引入新代理、放宽安全限制、下载或导入媒体，也没有模型调用/评分/.env变更。达到本批次三次上限后停止，不继续签名试错。

证据：

- R1：`reports/douyin-detail-replay-20261105-d78ab921/result.json`。
- R2/P：`reports/douyin-route-compare-20261105-5fb59196/result.json`。
- 上级根目录临时脚本：`tmp/detail-replay.py`、`tmp/route-compare.py`及各自外置配置，未持久化URL/响应正文/凭据。
- 独立环境执行`detail-replay.py --test`为2项OK，`route-compare.py --test`为1项OK；主Agent分别重跑通过。包含合成输入的分区交叉校验、目标/CRLF限制、重定向/大小/编码、有效JSON、只改变Accept-Encoding、R2失败跳过P及R2/P请求一致性。用例数量不与历史全量回归相加。

R1报告的all_query_values_scan_hit=true来自包含公开作品ID等固定值的宽泛扫描，不能解释为凭据泄漏。主Agent独立检查脚本/配置/报告：未发现完整Cookie或长度至少8的Cookie/身份/签名值；短值子串检查不作完全脱敏证明。R2/P敏感项检查未命中。成功JSON中的blocked/signature/login词标记可能来自字段或内容，本身不表示请求被阻断或要求登录。

### 代理核对与结论边界

Windows系统代理已启用且配置为本地回环服务，无PAC；未改动或输出代理地址/端口。**这不是403根因证据**。离线核对还发现历史SDK构造并未保证直连：BaseCrawler仅传headers/mounts/timeout，HTTPX默认trust_env=True；httpx先通过urllib.getproxies生成更具体的https://代理mount，随后加入的all://安全mount不能清除它。Windows的getproxies可能使用环境或注册表。故不能因SDK kwargs中proxies为None或子进程环境精简，就声称SDK从未使用系统代理。

代码证据：固定SDK wheel中`f2/crawlers/base_crawler.py`的client/aclient；本机独立环境HTTPX `_client.py:692/1439`、`_utils.py:195/404`及Windows标准库urllib.request。离线重建的legacy sync/async均选择proxy、R选择direct；这证明当前重建行为，不追认所有历史进程选路。实际P子进程再次确认proxy被选中，且成功返回目标JSON，因此本次对照不支持“代理本身导致403”的解释。

**现在已验证：用户提供的浏览器详情请求在当前程序环境可以成功，HTTP/1.1直连及当前既有代理transport都可取到目标详情。尚未验证：固定SDK自动构造请求是否可用，以及哪个字段/签名/会话上下文差异导致旧403。** 浏览器请求上下文与历史SDK不同，不能把成功复现扩大为SDK算法正确、Cookie单独足够或根因已锁定。

独立审查在禁止socket.connect下重跑两个fake脚本通过，确认R2/P共享同一URL/headers输入、R2无效即跳过P、P只注入既有选路transport。未追加真实请求。可以关闭“当前runtime无法取得此浏览器请求的有效详情”及“当前选路差异单独足以复现旧403”两个假设；不能关闭SDK构造、具体字段因果、下载或D05。

R2/P的download_permission=false只代表测试工具未见`video_control.allow_download is True`，字段缺失、非布尔值、明确false都会落入此结果，没有覆盖生产metadata的prevent_download_type等回退规则，不能直接写成“平台禁止下载”。media_candidate_present=true仅表示地址字段对象非空，没有验证具体URL、媒体可访问性或许可。后续必须按生产完整权限规则复核，禁止为完成D05绕过许可或直接使用媒体地址。

下一小批次应先固定本次完整Cookie、query Token和标头，对照SDK生成的query/签名组合；若做a_bogus单字段实验，必须保留其他rawquery字节、顺序及第二签名，且考虑两种签名可能绑定。固定SDK的ABogusManager.str_2_endpoint返回tuple[0]为原params，不能误当签名；generate_abogus的签名在[1]。这些只是实验实施注意项，不是已查明的403根因。本批次不执行上述后续实验，不需要用户再次提供Cookie或文件。原浏览器URL含时效性请求上下文，复现仅用于诊断，不将该URL缓存为生产下载地址或以手工复制替代正式SDK适配。
