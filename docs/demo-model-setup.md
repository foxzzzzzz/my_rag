# 本轮Demo模型与配置

日期：2026-11-03；方案ID：demo-baseline-v1；依据PRD v0.3。这是本轮试验组合，尚未经过本人评分，不等于生产选型冻结。

2026-11-04进度更新：两Key及三个模型真实探测已通过，临时预算运行器已完成现有3视频+2HTML全部转换。请直接使用[结果与评分入口](demo-run-results.md)。下文配置与处理顺序保留为说明，不必重复初始化或重跑调用；正式业务运行器尚未开发。

## 1. 本轮确定的模型

| 能力 | 服务/模型 | 用途和选择理由 |
|---|---|---|
| ASR | 百炼北京 `paraformer-v2` | 提取完整语音及服务原生句时间；中文/英文术语，支持热词，低成本起步 |
| 视觉/OCR | 百炼北京 `qwen3-vl-plus` | 读取关键帧中的文字、表格及流程/图表关系；不是只做字幕OCR |
| 文本 | DeepSeek `deepseek-flash` | 结合转录、画面材料或HTML正文，生成摘要和完整Markdown来源笔记 |

本轮不调用embedding，不做RAG问答；音画结果经本人认可后再进入该阶段。不会预先铺开所有ASR×视觉组合；低分项按问题定向增加对照，避免重复费用。

最新官方模型价格页当前北京千问VL表可核实qwen3-vl-plus；旧研究中的qwen3-vl-flash快照未在该表列出，因此不作为本次默认。不能仅凭未列出就断言旧模型所有账号均不可用。

## 2. 只需配置两个Key

| 变量 | 获取/开通 | 权限范围 |
|---|---|---|
| `DASHSCOPE_API_KEY` | [百炼Key官方说明](https://help.aliyun.com/zh/model-studio/get-api-key)，在控制台选择华北2（北京），开通模型服务并使用有额度的按量API Key | 至少允许paraformer-v2与qwen3-vl-plus；同一个Key用于ASR和视觉 |
| `DEEPSEEK_API_KEY` | [DeepSeek平台](https://platform.deepseek.com/)，创建API Key并确认账户额度 | deepseek-flash文本调用 |

不是阿里云RAM AccessKey，不使用Coding Plan专用Key。本地视频已具备，不需要抖音Cookie；本轮无须自建OSS、额外存储Key、embedding Key或本地GPU。公共北京域名仍获官方支持；Workspace专属域名可后续在配置中替换，Key和地域必须匹配。

项目 `.env.example` 为模板，`.env` 是忽略的本机配置文件。初始化命令只在文件不存在时复制模板，绝不覆盖：

```powershell
cd D:\codex_project\My_RAG\PersonalKB
python -m tools.demo_setup init
```

用本机编辑器填写 `.env`：

```dotenv
DASHSCOPE_API_KEY=填百炼北京的真实Key
DEEPSEEK_API_KEY=填DeepSeek的真实Key
FFMPEG_PATH=
```

只有前两项需要填写；FFmpeg已在本机临时工具中具备，FFMPEG_PATH可留空。环境变量优先于.env；如果已有同名环境变量，要避免旧值遮盖新配置。不要把真实Key粘贴到聊天或写进config/demo-models.json。

模型名、接口和额度已在 [demo-models.json](../config/demo-models.json) 填好，无需用户逐项研究。密钥文件不执行shell插值。配置后可本地检查：

```powershell
python -m tools.demo_setup doctor --json
```

doctor只读取本地配置、文件和FFmpeg，不联网、不收费，不打印Key内容或其前后缀。`ready_for_smoke_test`仅表示本地条件具备，`service_verified=false`表示还没有确认密钥有效性、模型权限或余额。

## 3. 本地视频如何送ASR

FFmpeg先提取音频，再按百炼官方临时上传政策获取48小时有效的URL。上传和识别必须同主账号、同模型；使用REST异步转写，并设置`X-DashScope-Async: enable`和`X-DashScope-OssResourceResolve: enable`，开启时间戳校准，记录task_id后轮询。

官方区分SDK与REST：转录SDK不支持该临时URL路径；本轮不能混用TokBrain私有上传函数加SDK转录来假设可用。先短音频验证上传、结果下载和句时间，失败立即记录并停止；不自动改用其他供应商或要求额外OSS。临时URL是demo便利方案，官方明确不用于生产，生产存储路径需在后续冻结前重新设计。

视觉图片可用base64直接送兼容接口；文本只送所需提取材料。音频、关键帧和文本将按环节发送至对应云模型，原素材留在本机。

## 4. 配置完成后的处理顺序

1. 本地doctor：两Key是否配置、当前文件/哈希、FFmpeg、模型参数及预算；不验证账号或质量。ready只表示具备最小探测前提，不证明五份完整处理已就绪；实际完整批次还须核对3视频+2HTML清单。
2. 实施/接通受预算控制的真实运行器：先记录价格快照，预留每次调用上界；未知费用或超限不发请求。
3. 2元以内最小探测：短音频ASR、单帧视觉、短文本摘要；检查响应、原始时间、token及实际费用。ASR上传失败不重复提交新任务，已有task_id先恢复查询。
4. 探测通过后，首轮5份完整素材新调用上界20元（累计预研仍≤100元）。保留转录、带时间视觉材料、HTML正文/表格/代码与原SVG、摘要、笔记、方案/输出版本、费用及耗时。
5. 生成每份可评分的评审HTML。本人给整体分数和approve/rework/reject；分数主观，不称统计准确率。低分定位到ASR、视觉、摘要、遗漏或分类再决定对照试验。

截至2026-11-04，配置检查、离线评分工具及临时预算运行器均已执行；五份真实结果已生成，待本人评分。doctor本身仍只检查本地，不能将它的ready状态当作模型质量验收；正式业务运行器尚未开发。

## 5. 价格和预算依据

2026-11-03核对公开北京原价，不抵扣优惠/免费额度：Paraformer 0.00008元/秒，本批约1076.21秒音频的单次ASR分项约0.0861元；不含其他环节和重试。Qwen3-VL-Plus输入≤32K时输入1元/百万token、输出10元/百万token，更长输入分档计费。DeepSeek Flash人民币峰时未命中输入2元/百万、输出8元/百万token，闲时半价。

本轮视觉图片token、帧数量、摘要及一次HTML重试已实测，费用与未知用量上界见结果报告；整月日常链路成本仍未验收。2元与20元是本轮探测/完整批次上界，不是预计要花满的金额，也不追加到100元之外。

官方依据：

- [Paraformer模型及价格](https://help.aliyun.com/zh/model-studio/paraformer-v2)
- [Paraformer REST临时URL、时间戳与SDK区别](https://help.aliyun.com/zh/model-studio/paraformer-recorded-speech-recognition-restful-api)
- [临时上传及48小时限制](https://help.aliyun.com/zh/model-studio/get-temporary-file-url)
- [百炼视觉接口](https://help.aliyun.com/zh/model-studio/vision/)、[百炼价格](https://help.aliyun.com/zh/model-studio/model-pricing)
- [DeepSeek兼容接口](https://api-docs.deepseek.com/)、[人民币价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)

账户能否调用仍以最小真实探测为准。旧别名可能滚动更新，需记录实际模型名、响应元数据及调研日期；版本变化重新比较并保留旧评分。
