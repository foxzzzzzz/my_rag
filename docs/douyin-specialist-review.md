# Phase 2C2e专项回传的原会话核验

日期：2026-11-05；最新结论：按用户新授权及PRD v0.15，原会话已独立核验当前真实作品在本机隔离库的动态下载、统一导入闭环，D05在此范围通过。Phase 2D仍待用户确认后启动。下方首次核验保留为旧strict规则下的历史，不再代表最新状态。

## 第二次回传：完成结果独立核验（PRD v0.15）

已只读专项会话用户消息，确认用户明确选择“采用插件策略，修改原有字段规则”：确认有权处理后保存当前账号可正常播放的媒体，不再仅凭allow_download标志拦截；登录/付费/验证码及实际HTTP拒绝仍保留。因此本次核验使用authorized_playback新规则，不以历史strict拒绝否定已授权的产品变更。strict仍为可选配置。

原会话核对结果：

- `reports/douyin-d19-isolated-3.json`记录正常DouyinImporter.enqueue/process_next真实解析、媒体HTTP200、下载和统一导入成功；不是手工复制签名URL或插件代下载。
- 只读打开`tmp/d19-isolated-3/data/workflow.sqlite3`，integrity_check=ok，sources=1、douyin_cache=1、tasks=1、versions=0、reviews=0；第三个任务记录来自后续CLI缓存补验，不是重复素材。
- 实际blob存在且为26,579,046字节。原会话独立计算SHA256，与报告和sources记录均相等：`0e29892823d2d187a38eecf550b98a0313776ff7094b7a389deacbc8588dd4df`。source_id为`af2e3eca161241599aac87cf8d791c82`。
- 按外部workflow/validation配置中的便携FFmpeg路径、线程数和超时，原会话对实际blob再次执行视频/音频完整解码，开启-xerror：退出0，stderr为空。没有ffprobe，未将其计为通过。核验脚本首次因Windows默认文本编码读取中文配置失败，显式utf-8-sig后成功，此问题没有修改业务代码或触发下载重试。
- 报告中再次同URL命中相同source，resolver/downloader/media_http_attempts均保持1；跨进程断网CLI报告`reports/douyin-d19-cli-cache.json`同样复用来源，素材/任务数1→1。原会话核对这些报告和数据库，没有为了复核再次联网下载或运行会改变隔离库的CLI。
- 原会话独立运行`python -m pytest tests/test_douyin.py tests/test_douyin_import.py tests/test_douyin_http.py tests/test_douyin_transport.py tests/test_resolver_guard.py -q --basetemp tmp/root-douyin-final-review-20261105`：**45 passed、1 skipped、34 subtests passed**，1.55秒、退出0。
- 独立F2环境再次执行`python -m unittest tests.test_resolver_guard -q`：**8 tests OK**，0.630秒，补验基础环境的可选SDK项，保留既有Loguru弃用提示。未重复专项报告的371项全量、前端12项及构建，不冒充原会话重跑结果。

此次没有新增平台请求、模型调用、真实评分或Git操作；默认全局enabled仍false，真实网页库未更改。媒体校验依赖的便携FFmpeg在外置workflow.ffmpeg指定，未安装软件或修改系统PATH。媒体请求使用固定Referer，不向CDN传Cookie/Auth；保留域名、公共IP固定连接、TLS、重定向/大小/超时/磁盘和租约边界。

可确认“当前授权作品、本机隔离库”的Cookie＋链接自动解析/下载/导入与重复缓存闭环通过；不等于任意视频、Cookie永久有效、线上已启用或目标Linux已经通过。旧F2 403唯一成因仍未锁定，当前可工作实现是minimal_detail动态端点而非旧F2修复宣称。研究素材保持待处理，未执行ASR/视觉/摘要或自动批准。

Phase 2D尚未启动；原会话向用户报告上述限定范围的验收结果，取得用户确认后再按原计划开始综合验收，不自动开放Phase 3。

## 首次回传：旧规则下的阶段性进展核验（历史）

## 核验结论

已检查minimal_detail动态解析代码、父进程错误传递、任务错误白名单、配置及D16/D17报告。无尾斜杠详情端点和三参数方案已接入正式解析桥接，不依赖用户逐条复制完整签名URL。D17正常父进程入口返回download_denied，说明当前阻塞已转为本项目的下载许可判定，而非此次入口报告403。

旧F2的403仍未唯一归因。D16是新方案可工作的证据，未提供相同三参数的有/无尾斜杠单变量完整对照，不能把尾斜杠认定为所有旧403的唯一根因。F2模式保留且不自动失败切换。

当前作品详情报告allow_download=false、prevent_download_type=2；metadata执行拒绝优先并返回download_denied。生产规则据此在请求媒体之前终止。**没有发生媒体下载或统一素材导入，D05未过，Phase 2D保持待开始。** 用户确认插件可保存完整MP4属于已知用户侧结果，不等于本项目已完成下载，也不能把当前拦截描述为“媒体下载已尝试但失败”。

## 独立回归及文件核对

- `python -m pytest tests/test_douyin.py tests/test_douyin_import.py tests/test_douyin_http.py tests/test_douyin_transport.py tests/test_resolver_guard.py -q --basetemp tmp/root-douyin-review-20261105`：**42 passed、1 skipped、33 subtests passed**，1.30秒，退出0。基础环境跳过可选F2集成测试。
- 独立解析环境执行`python -m unittest tests.test_resolver_guard -q`：**8 tests OK**，0.731秒，补验上述可选环境；既有Loguru弃用提示保留。
- 未追加真实平台请求，未调用模型，未修改代码、Cookie配置或真实评分。此次没有重跑专项已报告的368项全量、前端12项及构建，不将其描述为原会话重跑结果。
- 对照最终审计哈希，当前tools/douyin_resolver.py、personalkb/douyin.py、douyin_import.py、config/douyin.json、tests/test_douyin.py、test_resolver_guard.py及web/src/management-helpers.js七项均匹配。
- web/src/management.jsx未列入最终审计哈希表，不能称八项全部匹配，也不是已发现文件变更。已只读检查其错误映射与下载任务展示；哈希/扫描报告的覆盖范围应保持此限定。

## 证据与限制

- `reports/douyin-d16-9fa389c2/result.json`记录两次显式GET均200、业务状态0、目标ID匹配及许可拒绝；计数为实验循环观测，不是完整进程出网审计。
- `reports/douyin-minimal-d17.json`只记录最多1GET/0POST守卫和正常父进程返回download_denied，实际请求次数未埋点。所附哈希属于当时执行快照，未冒充最终版本快照。
- `reports/douyin-final-audit-20261105.json`给出最终文件摘要和383文本的选定敏感值精确匹配未命中；不是通用密钥扫描，不能扩张为所有类型文件/未知秘密完全无泄漏。
- 原会话代码核对确认minimal_detail显式直连、TLS证书验证、零传输重试、禁重定向及压缩原始/解码响应双上限；配置默认enabled=false，保留明确启用步骤。

## 后续门槛

专项继续保留：使用符合当前项目下载许可规则且用户有权处理的真实作品，验证Cookie＋链接动态解析、受控媒体下载、统一导入、去重/恢复及失败提示闭环，并提交实际产物身份与回归证据。若当前样本确实无法通过既定规则，应明确所需的样本或产品规则决策，不以插件下载成功代替项目验收，也不由原会话自行放宽规则。

本次只接受“动态解析接入及许可错误链路的阶段性修复”结论，不接受“Cookie＋链接下载问题彻底解决”。专项回传真实闭环通过证据后，原会话再核验并与用户确认，之后才能启动Phase 2D。无需现在重新提交Cookie。
