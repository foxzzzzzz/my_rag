# Phase 2C1 网页使用与启动

**2026-11-06当前入口说明：** 8765已切换Phase 3U-C正式新版，已支持完整分类/Obsidian与正式RAG。当前运行配置为`reports/phase2-content-20261105-07d9f46d/web.json`；重启请使用`tools/start_web.ps1 -Config reports/phase2-content-20261105-07d9f46d/web.json`，不要将下方历史验收配置误作当前库。服务已运行时无需重启。

操作：资料库打开独立详情，阅读正文/证据；新评分先“保存评分草稿”，再明确提交。保存只在当前页面会话，刷新会丢失；修改后重存，不自动批准。问答、导入、任务与分类从侧栏进入，手机采用紧凑导航。[新版验收与限制](phase-3u-frontend-validation.md)、[问答操作](phase-3-rag-guide.md)。以下为2C1启动历史记录。

日期：2026-11-05。已交付网页导入、明确派发、真实进度、原件/帧证据、评分/修订/撤回和Markdown下载。主题标签、附件ZIP及Obsidian重上传仍在2C2，不表示正式RAG或公网服务已经上线。

## 当前本机验收页

地址：[http://127.0.0.1:8765/](http://127.0.0.1:8765/)。本轮已启动并用真实浏览器验证；服务停止后按下节启动。

2026-11-05修复：此前临时工具进程退出后后台停止，浏览器可能仅剩缓存页面。Windows请从项目根目录使用独立后台启动脚本，关闭启动终端不等于关闭服务：

```powershell
.\tools\start_web.ps1 -Config reports/phase2c-web-20261105-dadc8620/web.json
```

启动脚本会检查健康状态、记录PID和根`tmp/web-server`日志；已有同配置服务则复用，不终止其他占用进程。默认不传Config启动的是`config/web.json`的新开发库，不是验收副本；配置不一致会明确拒绝。电脑重启后仍需手动运行脚本，本轮不设置开机自启。

页面现在区分连接中/已连接/未连接，断线后可点击“重试连接”或顶栏“刷新”。重连保留未提交输入，但提交前需重新核对版本；“刷新详情”会清除尚未提交的评分/编辑。不自动重发评分或付费操作。

当前运行配置位于`reports/phase2c-web-20261105-dadc8620/web.json`，数据是2B新V01的独立副本及明确命名的测试HTML。没有修改2B原报告数据库；视频当前仍待本人评分。自动验收的99分批准、80分返工只写到测试HTML，当前测试HTML的新修订版本也未批准。不要把这些测试分数算作模型质量。

默认正式开发配置是`config/web.json`，其数据目录由`config/workflow.json`决定，默认`data/workflow`。它与本轮独立验收库不是同一个目录；后续选择正式数据目录和迁移需保留版本/审核绑定。

## 安装和启动

本轮验证环境为Windows/Python3.14、Node24.22.1，前端React19.3.1/Vite8.3.5，后端FastAPI0.162.0/Uvicorn0.54.0。目标Linux应用整链路另验收。精确Python依赖及传递依赖见`config/web-requirements-lock.txt`，前端使用`web/package-lock.json`。

在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r config/web-requirements-lock.txt
cd web
npm ci --ignore-scripts
npm run build
cd ..
.\.venv\Scripts\python -m tools.web_server --config config/web.json
```

Linux使用对应`.venv/bin/python`，仍从项目根目录运行。Node只用于构建，FastAPI直接提供`web/dist`，无需另外启动前端服务。FFmpeg仍在`config/workflow.json`配置；没有FFmpeg则新视频导入校验会明确失败，不能只按扩展名假称媒体可处理。

本轮隔离依赖安装在被忽略的`tmp/web-deps`和`web/node_modules`，未改系统Python。标准部署应使用上面的虚拟环境命令，不依赖本机tmp缓存。当前验收库复现可将`--config`改为上述验收配置的实际路径。

## 三个网页流程

1. **导入**：进入“导入”，选择或拖拽HTML/HTM/MP4，勾选有权处理后上传。逐文件显示结果；同内容重复返回同一来源/任务。上传只登记，不自动产生模型费用。
2. **任务**：在“任务”点击“开始”。HTML使用本地静态提取；视频调用已验证ASR/视觉/文本链路。显示真实阶段、完成帧数/阶段数；未知总量不造百分比。失败、取消、重试和恢复遵循2A/2B安全规则。
3. **复核**：点击资料，查看摘要、笔记、正文、转录、视觉和材料缺失提示；视频原片可播放，点击关键帧时间定位。HTML原件只下载，不作为可执行页面内联打开。

输入0–100分、审核人及明确决定后提交。批准必须≥98分；返工/拒绝不要求高分，并会立即撤销该版本正式知识资格。没有评分或仅查看不会自动批准。所谓资格仍不是已写入向量索引，Phase 3才接正式检索。

“编辑”可修订标题、摘要、笔记、正文、转录和视觉；保存生成独立human_edited版本，旧产物和反馈保留，新版本必须重新评分。其他标签页修改后，正在填写的旧表单会提示刷新并禁止提交；服务端也检查version_id和内容SHA。评分未保存前，不会因后台轮询偷偷改绑新版。

Markdown下载包含稳定来源/版本/SHA和当前审核状态。当前只提供单篇Markdown；完整附件及Obsidian编辑重传不在本轮交付范围。

## 视频与费用开关

`config/web.json`默认`live_video_enabled=false`，便于安装和审核已有产物，不自动发付费请求。要处理新视频，由本人手动设为true并重启，再在网页勾选同意模型费用后点击开始/恢复。HTML本地处理不需要开启此开关。

模型Key仍放本地`.env`或进程环境，不填写在网页中；`env_file`只配置秘密文件路径，环境变量优先。仅执行视频任务才读取秘密，页面查询和评分不读取它们。预算仍沿用2B原累计账本，研究上限100元；不通过更换账本绕过历史预留。正式OSS仍由本人后续手动切换，不自动开通。

## 本机安全与恢复边界

- 默认只能绑定127.0.0.1/localhost，带Host/Origin限制、HttpOnly会话及写入CSRF校验；页面会话并非正式密码登录，不能据此直接公开到公网。正式单用户认证、HTTPS和云端代理在Phase 4完成。
- 上传按实际字节计量，HTML16MiB/总文件1GiB上限沿2A配置；临时文件仅本次UUID，超限/中断清理，不使用用户文件名拼服务器路径。JSON正文另外默认限1MiB。
- 数据库保留UTC，网页按`display_timezone`显示，默认Asia/Shanghai。轮询、会话、上传和派发参数在`config/web.json`说明，不写前端常量。
- 派发表只记录明确操作，不扫描所有queued任务自动处理。取消与派发撤销同事务，重试先核实费用许可；未知外呼不自动重POST。
- 服务关闭等待后台线程最多配置秒数；若外部调用仍未退出，不伪称已经停止。进程退出后靠领域租约恢复，未知请求保留待处理；真实云端硬杀、子进程治理与共存资源仍需Phase 4验证。

测试与证据见[W01–W16](phase-2-web-test-cases.md)和[专项验收](phase-2-web-validation.md)。

## 2026-11-05 当前新版演示

本轮长期内容/HTML业务演示使用独立副本，含待审V01、功能测试HTML及两份真实HTML新结果。启动：

```powershell
.\tools\start_web.ps1 -Config reports/phase2-content-20261105-07d9f46d/web.json
```

打开 http://127.0.0.1:8765/，选择两份HTML查看摘要、笔记及正文并评分。原演示配置与报告保留，不能同时占用8765。模型重新处理需明确同意，会生成新版重新审核；完整操作见[内容指南](phase-2-content-guide.md)。

## 2026-11-05 分类与Obsidian更新

同一8765入口已升级，原资料/评分保留。新增“分类”页、多条件资料视图、批量管理、可编辑笔记/ZIP、上传差异预览与冲突应用；导入页新增默认关闭的抖音入口。见[操作指南](phase-2-management-guide.md)及[验收与边界](phase-2-management-validation.md)。8766仅用于隔离测试，已停止；真实Cookie与链接未联调。
