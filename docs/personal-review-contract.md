# 离线个人评审协议

本工具不调用模型、不生成转换结果。先由已有方案实际产出数据并保存 UTF-8 JSON；如下数据结构仅为字段示意，不是实测结果。`provenance: provider` 是调用方声明，工具只能检查结构与哈希，不能证明内容真实性。

```json
{"items":[{"id":"唯一项目ID","source_path":"video/a.mp4","source_sha256":"实际文件的64位SHA256","scheme_id":"方案名","scheme_version":"方案版本","run_id":"运行ID","output_version":"输出版本","output_kind":"machine_initial","status":"completed","provenance":"provider","transcript":"实际转录","visual":"实际带时间的画面描述","body":"实际正文","summary":"实际摘要","notes":"实际来源笔记","duration_seconds":12.3,"cost_cny":null}]}
```

路径相对 `--source-root`，源文件须存在且哈希匹配，不允许越界或外链；`output_kind` 为 `machine_initial` 或 `human_edited`，修订须用独立输出版本。`duration_seconds` 是处理耗时，费用单位人民币元，未知用 `null`。转录、视觉、正文、摘要、笔记均为字符串；转录、视觉、正文至少有一项非空，摘要和笔记均须非空。视频的转录和视觉都须有内容，若确实没有则填写明确说明（例如无音轨或无可识别视觉文字）。无真实结果、未完成及占位/合成来源不可评审。空结果不能代替真实结果。工具显示原文件下载链接，HTML 原件不会内嵌执行。所有内容当文本显示，未加载外部资源。

```powershell
python -m tools.personal_review build --bundle 产物.json --source-root 来源目录 --output 评审页.html
python -m tools.personal_review summarize --bundle 产物.json --source-root 来源目录 --feedback 反馈.json
```

build 不覆盖已有 HTML。用浏览器本地打开后逐项填写整体分数（0–100）、决定和审核人，问题标签及备注可选，再点击导出。不要将模型自评分数填作本人评分。多次导出的反馈文件可重复传入 `--feedback 旧反馈.json --feedback 新反馈.json`，汇总时合并历史并选取最新审核。反馈格式：

```json
{"reviews":[{"review_id":"唯一审核ID","item_id":"唯一项目ID","binding":{"item_sha256":"该item规范化SHA256","source_sha256":"源文件SHA256","scheme_id":"方案名","scheme_version":"方案版本","run_id":"运行ID","output_version":"输出版本","output_kind":"machine_initial"},"overall_score":98,"decision":"approve","reviewer":"本人","reviewed_at":"2026-11-03T12:00:00+08:00","tags":[],"note":""}]}
```

`decision` 可为 `approve`、`rework` 或 `reject`；时间须含时区。每个项目以最新审核为准；重复 ID 或同项目同一时刻的审核拒绝。变更该条目的内容、来源、方案或版本均需重新评分；新增或修改其他条目不影响此条旧评分；每次 build 和 summarize 都重新计算来源哈希。默认 98 分且明确批准才审核就绪，可在 `config/personal-review.json` 调整目标。汇总列出每项、未评项、返工项、拒绝项、低分项、问题标签计数、审核人及备注、最低分和已评分项均分。`all_review_ready` 仅代表**当前 bundle** 的全部条目就绪；须确认清单覆盖本轮全部 demo，再由本人选择方案，不代表写入 RAG 或客观准确率。费用仅展示；预算仍由 `python -m tools.research_cli budget-check` 单独预检。旧标注专项报告 `evaluation_mode=annotated_benchmark`、`current_workflow_gate=false`，其 formal_pass 不是当前流程门槛。

逐项汇总包含 `item_id`、`source_path`、`source_sha256`、`scheme_id`、`scheme_version`、`run_id`、`output_version`、`output_kind`，可直接按来源和方案追溯低分。
