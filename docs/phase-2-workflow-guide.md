# Phase 2A 本地持久流程操作说明

日期：2026-11-04。本轮提供后端领域服务和CLI，不需要新增API Key。不会读取`.env`、联网或调用模型。Web复核页与自动音画处理接入在Phase 2后续交付。

## 文件与参数

| 文件 | 用途 |
|---|---|
| `config/workflow.json` | 数据目录、文件上限、磁盘保护、质量目标、租约、尝试上限、媒体探测和HTML提取参数 |
| `personalkb/workflow_store.py` | SQLite来源/任务/版本/审核事务与正式知识资格 |
| `personalkb/workflow.py` | 本地导入、单次worker、显式已有视频结果接入、Markdown导出 |
| `tools/workflow_cli.py` | 本轮本地操作入口；成功输出JSON，失败输出安全错误JSON并退出2 |

默认数据目录为项目根下`data/workflow`，其中`originals/<SHA256>`保存原件、`workflow.sqlite3`保存流程记录。视频支持MP4，要求真实容器头及FFmpeg检测到视频流；HTML支持`.html/.htm`且包含HTML结构。原名只用于展示，不参与落盘路径。数据目录和原件路径拒绝符号链接。FFmpeg不在PATH时，请把`ffmpeg`配置成实际可执行文件的绝对路径，不能把研究包路径当永久部署依赖。

默认单文件上限1GiB，HTML单独上限16MiB；接收后预留磁盘8GiB。质量目标98分、租约300秒、最多3次领取，均由外部配置提供。当前worker为显式运行一次；后续长耗时模型编排必须按阶段续租，不能据此认为后台守护进程已经完成。

## 命令示例

在`D:\codex_project\My_RAG\PersonalKB`执行，示例中的ID、SHA、文件路径须替换为实际返回值：

```powershell
python -m tools.workflow_cli --config config/workflow.json init
python -m tools.workflow_cli --config config/workflow.json import "你的材料.html" --rights-confirmed
python -m tools.workflow_cli --config config/workflow.json tasks
python -m tools.workflow_cli --config config/workflow.json work-once
python -m tools.workflow_cli --config config/workflow.json show SOURCE_ID
```

HTML会输出静态正文、表格文本、正文预览、完整笔记及缺失警告，不运行JavaScript、不获取外链、不把预览说成AI摘要。脚本、SVG图表、图片或公式等存在提取局限；新结果未继承原先模型整理质量评分。

已有视频真实预研结果可显式接入，先导入对应MP4，再执行：

```powershell
python -m tools.workflow_cli --config config/workflow.json work-once --bundle reports/demo-baseline-v1-20261104/bundle.json
```

worker按队列顺序领取，不是按bundle选任务；bundle只会用于所领取的视频。必须存在唯一原件SHA匹配项、真实provider标识及完整正文/转录/视觉/摘要/笔记，保留原run/输出版本，不接收反馈文件充当产物。无匹配结果明确失败，不自行调用模型。补齐本地结果后可对失败任务显式`retry TASK_ID`；`work-once`再次运行时传入正确bundle。它不是视频自动转换服务，也不继承旧批准。

## 查看、评分与修订

`show`返回不可变结果版本，其中`id`为审核的VERSION_ID，`content_sha256`为CONTENT_SHA。本人核对后显式执行：

```powershell
python -m tools.workflow_cli --config config/workflow.json review SOURCE_ID --version VERSION_ID --sha256 CONTENT_SHA --score 99 --decision approve --reviewer "本人"
python -m tools.workflow_cli --config config/workflow.json eligible
```

只有当前未删除版本最新决定为approve且达标时有正式知识资格；低分approve被拒绝。资格查询不是已写入向量索引。撤回时再次提交当前版本、SHA和实际分数，决定用`rework`或`reject`即可即时失效。评分为本人判断，不能称统计准确率。

修订时复制`show`中当前version的`result`对象到独立JSON文件，修改正文/笔记，并设置`output_kind`和`provenance`为`human_edited`；保留完整证据、方案身份等字段。只传result对象，不传外层source/version：

```powershell
python -m tools.workflow_cli --config config/workflow.json revise SOURCE_ID --expected-version VERSION_ID --result "修订结果.json"
```

修订生成新version_id/内容SHA，旧输出保留，旧评分不迁移；再次查看、核对、评分。旧expected-version或旧内容SHA不能覆盖新结果。

## 重试、取消、删除及导出

```powershell
python -m tools.workflow_cli --config config/workflow.json cancel TASK_ID
python -m tools.workflow_cli --config config/workflow.json retry TASK_ID
python -m tools.workflow_cli --config config/workflow.json delete SOURCE_ID
python -m tools.workflow_cli --config config/workflow.json export --version VERSION_ID --output-dir "D:\codex_project\My_RAG\PersonalKB\data\workflow\exports"
```

retry只允许安全的失败/取消任务且未达到尝试上限；远端调用开始或task_id已记录但状态未知时进入needs_attention，不允许普通重试重新提交。当前只提供检查点存储，远端查询恢复命令留待Phase 2B。取消/删除使旧worker令牌失效；软删除不物理擦除历史和原件，同字节重导入不会悄悄复活。

导出目录须位于data_dir内部；文件名由version_id生成，不覆盖已有文件。Markdown包含来源/版本/SHA/审核状态与方案信息，保留笔记和原文；未获批或旧版本标为`draft_or_inactive`。导出是当时快照，后续审核变更不会修改已下载副本。当前仅Markdown，不包含完整附件ZIP或Obsidian重上传更新功能。

## 恢复与已知边界

重新打开同一数据库即可查看现有任务/版本，claim会安全回收过期租约。原件先原子落盘，再由单事务登记来源和任务；DB登记失败可能产生未引用原件，不能把孤儿当知识或任意删除同SHA文件。自动孤儿扫描、视频7天清理、备份和恢复演练另行集成。

任务保留当前阶段/错误、累计尝试次数和创建/更新时间；审核以服务端追加序号为最新顺序，含服务端创建时间。它不是完整任务事件日志。现有正式OSS对象归属仍未接入持久任务，真实OSS联调、API会话/HTTPS、主题管理和资源监测均未借本轮离线通过而宣称完成。
