# API Key真实验证记录

验证日期：2026-11-04（Asia/Shanghai）。用户已将两个Key配置到本机.env并授权探测。没有输出Key、前后缀、Authorization或签名URL。

## 1. 结论

**两个API Key有效，本轮三个模型的最小真实调用均通过，可以启动现有3视频+2HTML的demo预研。** 这不是完整内容质量验收，未声称98分、已完成五份转换或已入RAG。

## 2. 实际请求结果

| 项目 | 测试 | 真实结果 |
|---|---|---|
| DeepSeek认证 | GET /models | HTTP200；列表含deepseek-flash、deepseek-v4-pro |
| 百炼认证 | GET兼容接口/models | HTTP200；列表含qwen3-vl-plus；ASR属另一接口，不要求在兼容列表出现 |
| 文本模型 | deepseek-flash，短提示，max_tokens=32，关闭思考 | HTTP200，非空生成；input7/output1/total8 token |
| 视觉模型 | qwen3-vl-plus，120×80纯蓝PNG的base64输入，max_tokens=64 | HTTP200，非空生成；input92/output2/total94 token；未将非空输出等同于视觉准确率达标 |
| ASR | sources最小视频的1–6秒片段，WAV16kHz单声道，paraformer-v2 REST | 上传policy、OSS临时上传、异步任务、查询和结果下载均成功；返回3句非空文字及服务原生begin_time/end_time |

ASR不仅取得task_id，还确认子任务SUCCEEDED及最终句时间存在。没有伪造时间戳。只处理5秒音频，不把它标为完整20秒/长视频转写。测试图为合成纯色图，不是sources画面内容质量试验。

## 3. 预算与安全

在实际POST前使用持久SQLite事务及唯一request_id预留预算：文本0.10元、视觉0.25元、ASR0.10元，共**0.45元保守占用**，在本轮2元与研究100元上限内。该数字不是已扣费金额；保留而不释放，以免未知费用或重复启动规避上限。

按已核对的峰时公开价格估算：文本0.000022元、视觉0.000112元、5秒ASR上界0.0004元，合计约0.000534元。估算不扣优惠、不代替供应商账单。

禁止自动重发付费POST；本轮固定身份和进程锁防并发覆盖；ASR持久化task_id，未完成时只恢复查询。API认证头只发官方API域名，OSS上传与转录下载无Bearer；校验HTTPS/域名/公网DNS并禁重定向。报告不保存转录原文、模型原始回复、Key或签名URL。

原始脱敏结果位于被忽略的 reports/api-smoke/verification-2026-11-04.json；预算位于 reports/research-budget.sqlite。临时探测脚本与假传输测试在tmp/，没有将其冒充生产运行器。

## 4. 实施与验证范围

先列S01–S09，再做预算及假传输测试，独立审查后执行真实探测。修复预算helper的SQLite连接未关闭问题；预算唯一键/超限测试通过。临时工具9项离线测试覆盖HTTPS/域名/私网拒绝、禁重定向、进程锁、上传表单、脱敏HTTP错误、文本结果解析/防重发、ASR恢复及时间缺失拒绝。测试不读取真实Key、不联网；真实探测独立执行。

真实探测后执行项目完整回归：54项unittest全部通过（约19.4秒）；Markdown引用和代码围栏检查通过。未执行Git提交、推送或Tag。

没有切换模型，没有完整转换五份sources，没有做检索、本人评分或云端部署。下一阶段沿用已验证模型和Key，接入完整处理、原始结果/来源版本及每阶段费用记录，最终生成本人评分页面；低分再有针对性比较其他方案。无需用户重复申请Key或先做gold标注。
