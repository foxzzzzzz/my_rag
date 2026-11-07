# 长期内容与 HTML 模型处理操作说明

日期：2026-11-05；PRD v0.12。

## 长期内容目录

`config/workflow.json` 的 `data_dir` 默认 `data/workflow`，正式资料不放在临时研究目录。`content.enabled=true`、`content.directory=knowledge` 后，每份来源持久保存：

```text
data/workflow/
  workflow.sqlite3                    # 任务、版本、审核及同步信任根
  originals/<source_sha256>           # 原HTML/原视频，保留周期另按策略
  knowledge/<source_id>/
    note.md                          # 稳定笔记入口，含当前版本/审核状态
    current.json                     # 当前版本、同步代数与文件哈希
    versions/<version_id>/
      content.md                     # 不可变版本正文（不自报已批准）
      evidence.json                  # 完整证据文字、类型、时间
      manifest.json                  # 版本/证据与附件校验
    frames/<image_sha256>.jpg         # 永久关键帧
  video-work/<task_id>/               # 临时预处理缓存；不是唯一帧证据
```

Markdown 保留原知识文本、摘要、转录、视觉与证据相对链接。数据库私有 provider 字段、租约和运行路径不进入内容清单；用户自己写入来源文字中的路径、URL或代码示例不会被正则删除。请勿把实际 Key/Cookie/签名 URL 当知识内容输入。单篇下载不包含附件，附件 ZIP 在2C2d交付。

审核或修订先提交数据库，再同步文件。写盘失败时来源显示未同步，不能获得正式知识资格；不会重跑已完成模型，也不会生成假评分。修复磁盘/权限后显式执行：

```powershell
python -m tools.content_cli reconcile --config config/workflow.json
python -m tools.content_cli verify --config config/workflow.json
# 可附加 --source-id <来源ID> 限定范围
```

旧数据使用原 workflow 配置启用 `content` 后执行 reconcile；先做一致性备份，并在独立副本验证。程序不会自动删除旧 work、原件或审核记录。损坏文件可以从数据库/仍存在的缓存补建；如果永久帧与原缓存均丢失，必须从备份恢复，不能假称已修复。

`note_id=source_id`，版本ID独立。下载时审核状态按最新数据库计算；下载到本地的副本是当时快照。不要直接编辑服务器受校验的文件；Obsidian 编辑重传/冲突处理在2C2d交付。恢复整个应用必须同时备份数据库、Markdown、原HTML和永久附件，不能仅凭Markdown还原审核历史。

## 网页 HTML 操作

默认不开启付费。需在所用 `web.json` 中设置 `live_html_enabled=true`；`html_pipeline_config` 默认 `config/html-pipeline.json`。DeepSeek Key仍在本地 `.env` 的 `DEEPSEEK_API_KEY`，无需新增服务或Key。

1. 导入 HTML 并确认有权处理；导入只登记文件。
2. 任务页选择“离线正文预览”或“模型摘要与笔记”。模型模式另勾选费用同意，再点击开始。
3. 已有预览或模型版本可在资料详情勾选本次费用同意，点击“生成新的模型整理版本”。这会新建任务，保留旧版本，不能重用旧评分。
4. 任务完成后对照原件、正文证据、摘要与笔记，评分并明确批准。≥98分仅为个人主观门槛，不是统计准确率保证。

静态提取保留表格、代码及SVG结构文本；不执行JavaScript、不请求外部图片或链接、不把SVG作为活动网页插入。公式目前只保留文本，动态图表、复杂公式或图片需补静态材料。嵌套表格展平并提示核对。离线预览不是AI生成摘要，页面有明确标识。

## CLI 与异常

先用既有 workflow CLI 导入，获取 task_id，然后明确联网执行：

```powershell
python -m tools.html_cli --config config/workflow.json run <task_id> --live
python -m tools.html_cli --config config/workflow.json status <task_id>
python -m tools.html_cli --config config/workflow.json resume <task_id> --live
```

`resume`只复用已完成缓存或继续明确未发送的阶段。同步POST结果未知时保持 `needs_attention`，显式恢复也不会重复提交；需要人工核对供应商用量/原任务后另行处理。不要删除任务或账本来绕过限制。CLI无`--live`不会调用模型；所有真实POST沿用累计100元研究账本预留，日常月费仅观察。

当前文件同步在SQLite写锁中进行，正确性优先。大量版本/附件时重复校验可能增加等待，规模测试与缩短锁持有时间已列Todo。真实Linux整链路、清理与备份恢复仍在后续阶段验收。
