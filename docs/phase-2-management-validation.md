# Phase 2C2c–e 工程验收记录

日期：2026-11-05；PRD v0.15。先行用例见[管理测试](phase-2-management-test-cases.md)，操作见[指南](phase-2-management-guide.md)。

## 当前结论

| 子阶段 | 状态 |
|---|---|
| 2C2c 分类 | 工程通过：多主题/知识标签/别名、稳定ID、来源/目录CAS、组合筛选、逐项批量报告及Markdown元数据 |
| 2C2d 往返 | 工程通过：可编辑笔记/永久附件ZIP、安全预览、分别的正文与分类冲突、显式幂等应用、新正文待审 |
| 2C2e 抖音 | 新授权authorized_playback策略下，当前真实作品动态解析/受控下载/统一导入/重复缓存D05通过；隔离验收库，默认全局仍关闭；待原会话核验 |
| 2D / Phase 3 / 4 | 仍待原会话核验专项结果并与用户确认；未启动2D或宣布整体通过，完整目标机等验收尚待后续 |

## D19–D24最终真实闭环与回归

跨进程补验：完整非秘密配置保存在tmp/d19-isolated-3（workflow.json/douyin.json/validation.json），执行清单execution-manifest.json分列请求时快照与收尾配置/脚本哈希，未为更新哈希重发下载。新进程在socket/DNS封锁下运行CLI status/jobs/import/run-once，合成非空Cookie仅作配置检查，缓存返回原source_id且sources/tasks均1→1；报告reports/douyin-d19-cli-cache.json，不证明该合成值或原Cookie有效。首次CLI启动因PYTHONPATH未配置未进入应用，修正后通过，属于验收工具问题。

报告`reports/douyin-d19-isolated-3.json`：普通Importer两次成功任务同source_id，26,579,046字节，下载/入库/source/cache SHA一致；首次1次真实解析和媒体HTTP200，第二次缓存命中、计数不增。独立只读验库为1素材/1缓存/1queued task、无版本或审核、锁释放、integrity_check=ok；独立FFmpeg增加-xerror完整解码仍退出0且stderr为空。成功脚本是tmp/d19-success.py，数据库是tmp/d19-isolated-3/data/workflow.sqlite3；此前两轮失败保留，原因是FFmpeg未在PATH，使用已有便携工具外部路径解决。

最终完整`python -m pytest tests -q --basetemp tmp/douyin-d24-all-20261105`：**371 passed、3 skipped、44 subtests passed**，42.31秒、退出0；独立F2环境guard 8项通过；前端12项及Vite构建通过。3跳过包括既有平台项和可选F2（独立环境补验），旧Starlette/Loguru弃用提示保留。

离线审计`reports/douyin-d24-audit-20261105.json`扫描387文本，未命中已知完整Cookie/长度>=8 Cookie值及选定敏感query，非通用秘密检测；哈希是审计时快照。计数为显式call-through/opener调用，非全进程网络审计；零模型由导入路径与未运行task支持，非模型流量拦截。默认enabled关闭、.env及当前网页库不变，未自动评分/Git动作；D05只覆盖当前作品和本机配置，不推广所有作品。

没有新增需要本人审批的技术方向，C01/C02和费用观察口径不变。后续需要本人执行内容评分及Cookie/链接配置；Git commit/push/Tag仍须事前确认，本轮未执行。

## 验证证据

最终完整命令：`python -m pytest tests -q --basetemp <项目tmp下唯一目录>`。

- **355 passed、2 skipped、21 subtests passed**，39.08秒，退出码0。2项为既有Windows/POSIX平台跳过。
- **11项前端测试通过**；Vite构建通过。
- 最终全量包含pytest函数和unittest用例，不把分类/往返/下载专项数量再次相加。
- 存在1条既有Starlette TestClient依赖弃用提示，未因此改动Web依赖。

日志：`tmp/phase2-management-final-pytest.log`；正式副本及报告：`reports/phase2-management-20261105-602a8a3a/automated-tests.txt`、`validation.json`。

## 独立复核与故障用例

关闭批量选择后自动采用新revision的覆盖风险、非法批量项中断响应、标题筛选缺字段、CRLF无变化误建版本及分类冲突未明确展示的问题。

Obsidian验证覆盖路径穿越、重复/大小写碰撞、符号链接、压缩/实际解压限额、伪造身份/批准、同时篡改证据与manifest、应用时正文/metadata并发、过期/删除及幂等。正文/分类/回执在同一事务；同步失败留待重放。支持常见受限属性，不执行通用YAML。

抖音复核关闭无限DNS等待、截断当成功、失租后来源仍提交及F2文件日志副作用；详情见[专项记录](douyin-import-analysis.md)。固定公共IP连接保留原域名TLS验证；本机socketpair证明HTTP连接关闭后响应可读、响应关闭后FD释放。历史SDK构造检查未覆盖同步Token请求，原“没有真实HTTPS请求”判断撤回；完整零网络需D07补验。

2026-11-05后续：已匹配用户完整User-Agent，真实作品详情仍HTTP403，未下载/导入；当前报告只记录异步作品请求，不代表SDK总出网次数。D05未通过，本轮停止平台重试，D07同步/异步分阶段限制按[联调记录](douyin-live-validation.md)单独验收。

D07补验：抖音专项36 passed、1 skipped、11 subtests passed；独立F2环境5 tests OK补齐可选SDK测试。覆盖隐式Token禁止、真实Token显式化、Cookie不外传Token主机、HTTPS/方法/次数/重定向、TLS证书校验开启和底层重试0。真实SDK测试使用假传输且socket.connect禁用，没有新的真实平台请求；详细命令与限制见上述联调记录。355项是此前完整工程快照，本轮未重跑前端或宣称新增全量结果。

D08真实复测：用户补充Edge Cookie/UA后，网页200、显式Token200、SDK详情403，各一次，无下载/导入或模型调用；网页200仅代表收到HTML，未确认播放或账号登录，D05继续未通过。证据见`reports/douyin-edge-live-20261105-47ca231c/report.json`及联调记录；未覆盖.env/全局配置。

D09归因验证：固定SDK版本差异已审计；本轮GET2/Token POST1/page0后停止，SDK基线与无凭据负对照均403，严格原因分类UNKNOWN，不能等同正文一致或排除身份/签名问题。两组合成工具检查由主Agent重跑通过，独立审查确认计数与结论边界；用户确认Edge详情200，但成功请求标头尚未取得，原生只读工具因URL确认失败被安全检查停止。详见[403专项分析](douyin-403-analysis.md)，D05/Phase 2D未通过。

D10：已取得本地成功详情文本，原URL直连200/br，gzip补证后直连及当前自动代理选路均200、业务状态0、目标ID匹配；query未重编码，无SDK签名或Token调用。三次GET后停止，两个临时工具的2项/1项合成测试由主Agent重跑通过。P实际选择proxy且成功，不支持代理单独归因；尚未验证SDK自动构造，未按完整生产metadata判下载许可、未下载，D05/2D状态不变。报告及隐私/编码/选路限定见专项分析D10。

## 网页真实交互

独立验收数据副本及8766临时服务中，仅新增工程测试HTML（`42710acdf8684b59af2bd15529e205fc`）：

1. 创建主题及别名、知识标签，按不同于文件名的标题筛选。
2. 批量分类成功；第二客户端更新后，原选择批量replace返回冲突，未覆盖新分类。
3. 文件选择器上传已编辑MD，预览明确尚未写入；确认后产生第二个待审版本，未代填评分。
4. ZIP实际下载成功；手机宽度无横向溢出，临时viewport已恢复。

截图：`browser-roundtrip.jpg`、`browser-classification-conflict.jpg`、`browser-mobile-import.jpg`。隔离8766已停止；测试资料/分类没有复制回当前资料库。

当前8765应用已升级，保留既有4份资料，新增分类和Obsidian入口；两份真实HTML当前版本及评分未变，真实新评分写入0。升级证据`actual-app-upgrade.json`，当前页面截图`browser-final-app.jpg`。五份sources原件SHA与预研记录一致，实际Key值泄露扫描未发现。

## 剩余边界与下一步

本轮新增模型调用0，研究账本保守预留仍23.50元；未改服务器、未开通OSS。

后续补D05真实抖音、本人对新HTML/V01评分及2D合并验收；AI分类建议尚未接入，人工分类已可用，建议预览/新主题确认列后续任务。Obsidian客户端/插件真实属性改写、目标Python3.12/Linux、完整队列/模型资源共存、七天清理和一致性备份恢复不能以本机测试替代。
## 2026-11-05 D11–D18专项最终工程快照

最终完整命令：`python -m pytest tests -q --basetemp tmp/douyin-d18-final-20261105`，**368 passed、3 skipped、43 subtests passed**，39.81秒、退出0。跳过包括既有平台测试及基础环境无可选F2；独立F2环境`python -m unittest tests.test_resolver_guard -v`最终8项通过。前端12项及Vite构建通过；不与上述数量相加。既有Starlette弃用提示保留。

独立review未发现minimal_detail安全阻塞，补齐配置交叉校验、压缩小于上限但解压超限和截断gzip回归。最终离线审计`reports/douyin-final-audit-20261105.json`扫描383文本文件，未命中完整Cookie/长度>=8的Cookie值及选定敏感query值；非通用密钥检测。缺Git仓库不能准确识别本轮变更，扩大扫描，文档收尾发生在审计后，代码与配置未再改变。

D16动态三参数详情成功；D17正常父进程入口取得明确download_denied，没有媒体下载/统一导入。当前用户样本接口allow_download=false/prevent_download_type=2；用户确认simpdown保存完整MP4可播放，属于用户侧证据，不改变本项目许可检查。D05保持未通过、2D未启动。执行报告中的哈希属于当时快照，最终代码/配置摘要另见离线审计，不为获得新哈希而重发平台请求。

