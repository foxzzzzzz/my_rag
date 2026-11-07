# ASR 存储模式与手动切换

日期：2026-11-04；对应 PRD v0.8、C01/C02 用户确认。

## 当前默认

`config/asr-storage.json` 的 `backend` 为 `temporary`，沿用已验证的百炼临时上传路径，只依赖现有 `DASHSCOPE_API_KEY`。不需要现在购买 OSS、创建 Bucket 或补充正式 OSS 凭证。配置中出现 OSS 字段或环境中存在 OSS 凭证，都不会自动切换模式；调用失败也不会切换。

“临时 OSS”在这里指百炼代管的临时上传能力，与用户自己开通的私有 OSS Bucket 是两套路径。临时引用有效期约 48 小时，受账号/模型绑定；上传政策接口限流 100 QPS、不可扩容，官方不建议用于生产或压测。用户已知情选择用于当前开发。这些限制已保留，正式 OSS 真实联调不再阻断 Phase 2 开发。参见[官方说明](https://help.aliyun.com/zh/model-studio/get-temporary-file-url)。

## 已实现的接入层

- `personalkb/asr_storage.py`：显式选择后端，统一返回 `PreparedAudio`；记录模型、输入哈希、大小和有效期。
- `personalkb/asr_storage_temporary.py`：申请上传政策、上传音频、生成 `oss://` 引用；上传不携带百炼 Bearer。临时对象由服务方管理，不假称主动删除成功。
- `personalkb/asr_storage_managed.py`：对已配置的私有 Bucket 上传、生成限时签名 GET、清理本适配器创建的对象。采用官方 `oss2==2.19.1`，依赖清单为 `config/oss-requirements.txt`；默认临时模式不导入该 SDK。

截至2026-11-05，Phase 2A持久任务与2B视频编排已接入：正式模式传入ownership回调，在PUT前将对象归属写入私密SQLite，支持跨实例核对scope后清理；见[2B说明](phase-2-video-guide.md)。底层适配器不带ownership独立使用时仍只有实例内存归属，不可据此任意恢复/补删对象。正式Bucket实际权限/清理与生命周期兜底仍未联调；Web和完整生产业务未完成。

## 后续手动切换步骤

1. 需要正式存储时，手动准备中国内地 OSS 私有 Bucket 和专用音频前缀。当前适配器支持标准 HTTPS Endpoint，默认示例为北京；不自动创建 Bucket、不设置公共读。凭证权限只覆盖该前缀的必要上传、读取和删除。
2. 填写 `managed_oss.endpoint`、`region`、`bucket`、`prefix`；按排队和 ASR 获取时长调整 `url_ttl_seconds`。默认 3600 秒只是待联调初始值，临时 STS 凭证更早到期时会缩短实际可访问时间。
3. 将 `PERSONALKB_OSS_ACCESS_KEY_ID` 和 `PERSONALKB_OSS_ACCESS_KEY_SECRET` 配到本地私密环境或 `.env`。使用 STS 时再配置 `PERSONALKB_OSS_SECURITY_TOKEN`；适配器只接收调用方传入的秘密映射，不自行打印或加载 `.env`。模板见 `.env.example`，不要将实际密钥写进 JSON 或文档。
4. 在应用运行环境安装 `python -m pip install -r config/oss-requirements.txt`。**安装依赖不会启用正式模式。**
5. 将同一配置的 `backend` 手动改为 `managed_oss`，由调用方重新创建适配器。先按[接入边界 A01–A06](production-integration-boundaries.md)做小样本真实验证，核对签名下载、ASR、过期与清理，才用于日常正式链路。测试不通过时显式报错，由本人决定是否改回配置。

## 调用约定与限制

应用读取 JSON 配置和秘密映射后调用 `create_storage(config, secrets)`；`prepare(wav_path, model)` 返回引用。ASR 请求使用该引用的 `file_url` 和 `asr_headers()`，继续携带原有模型服务认证。临时路径额外需要 `X-DashScope-OssResourceResolve: enable`；正式签名 HTTPS 路径不需要这个解析头。重试前检查 `is_expired()`，重新上传应有持久任务/费用控制，当前模块不擅自自动重试。

音频应为已处理的 WAV；本模块不负责转码。默认单音频上限 64 MiB，超限直接报错，不截断；调整前评估上传缓冲内存和目标机资源。`safe_metadata()` 用于日志，禁止序列化整个对象或输出 `file_url`、签名参数和密钥。远端任务终态及结果落盘后才能清理；失败清理不能写成成功。

现有临时上传路径已有真实 demo 证据；本轮新增适配器做离线回归。正式 SDK 已用假凭据完成初始化和离线签名验证，尚未做真实 Bucket 上传、下载、ASR 和清理联调。后续切换不会继承这些未完成项的“通过”状态。
