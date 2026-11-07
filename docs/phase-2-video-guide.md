# Phase 2B 视频自动处理、恢复与清理

本轮在Phase 2A之上增加独立的视频CLI；原`tools.workflow_cli work-once`继续默认离线。视频处理产生待审核新版本，不继承旧评分，不写入正式向量索引。

## 配置与运行

在项目根目录执行：

```powershell
python -m pip install -r config/video-requirements.txt
python -m tools.workflow_cli --config config/workflow.json import "你有权处理的视频.mp4" --rights-confirmed
python -m tools.video_cli --workflow-config config/workflow.json run TASK_ID --live
python -m tools.video_cli --workflow-config config/workflow.json status TASK_ID
```

替换TASK_ID为导入返回的任务ID。FFmpeg必须安装并在`config/workflow.json`配置可执行路径；新依赖仅`psutil==7.2.2`，正式OSS依赖仍使用单独的`config/oss-requirements.txt`。`run`与`resume`必须显式`--live`，会产生模型费用；缺标志在读取密钥前拒绝。

默认读取项目运行目录的`.env`，也可在子命令前传`--env-file 私密文件路径`；系统环境变量优先。所需仍为`DASHSCOPE_API_KEY`、`DEEPSEEK_API_KEY`。`status`不读密钥、不调用模型。不要将真实密钥、Cookie或签名URL写到配置、命令参数、截图和报告中。

`config/video-pipeline.json`引用已验证的模型、策略与存储配置，不在代码内固定调参。已知三视频按原件SHA选取既有profile；未知视频使用明确配置的默认profile，仍需本人逐条核对质量。视觉为抽样，不保证每一快闪画面均被覆盖。

预算默认单视频保守预留上限5元，研究累计100元，仍使用原`reports/research-budget.sqlite`。不要为绕过历史额度另换账本；测试可以使用标为合成的隔离账本，真实研究必须保留同一累计账本。先检查完整剩余批次上界，再按每次付费POST原子预留；缓存和ASR查询恢复不重复预留，未知费用不自动释放。usage和公开单价估算不代替官方实付账单。日常月成本仍只观察Todo。

资源默认磁盘余量8GiB、可用内存至少512MiB、整机占用代理上限3,000,000,000字节，FFmpeg线程2、滤镜线程1。每阶段/子进程检查保护并续租；这些是主动停止条件，不是CPU或内存硬隔离，也不代替共享服务器上的完整业务共存验收。

## 恢复规则

```powershell
python -m tools.video_cli --workflow-config config/workflow.json resume TASK_ID --live
```

先查看`status`和安全错误码。运行中断后，过期租约会转为needs_attention；显式resume领取新令牌。取消、删除、方案指纹不符或已有其他运行任务时拒绝。

| 已保存状态 | 恢复行为 |
|---|---|
| ASR已得到task_id、结果未保存 | 仅查询同一远端任务和下载结果，不重新上传或POST |
| ASR/视觉/文本结果completed | 校验阶段输入SHA与结果SHA，复用已有输出 |
| prepared且尚未外呼 | 核对同request_id的预算预留，可继续原阶段 |
| ASR提交未知且无task_id | 停止，不能知道服务端是否接受，不自动重发 |
| 同步视觉/文本请求未知 | 停止；接口没有本项目可用的结果查询，不自动重发 |
| 远端明确失败 | 持久记录失败终态，允许安全清理；不自动改模型重新提交 |

一次resume可继续完成该任务尚未调用的新视觉/文本阶段，所以仍需`--live`，不承诺resume全程免费。已过期的上传URL不妨碍按已保存ASR task_id查询；远端任务/结果自身的保留期限仍由供应商决定，不保证无限期可恢复。

本地媒体缓存绑定来源/策略与文件SHA，读取缓存还核对真实WAV时长/格式和帧时间覆盖。媒体进程异常退出如遗留`.media.lock`或无完整manifest的部分文件，会明确停止；人工确认无旧进程后才可处理该任务独占目录，不提供任意路径自动删除。跨主机硬杀恢复和实际资源上限仍需服务器验收。

## 存储清理

```powershell
python -m tools.video_cli --workflow-config config/workflow.json cleanup TASK_ID
```

清理不提交模型请求；正式OSS模式会访问对象存储，因此仍需对应私密凭证。维护事务与任务领取互斥，只清理已确认远端终态、证据已保存或明确失败的对象；远端结果未知则保留，不能通过普通retry绕过。

默认临时上传：只标记`provider_managed`，实际由百炼按48小时有效期管理，不声称主动删除。正式OSS：上传前登记asset_id、任务、原件摘要及不可变桶/地域/Endpoint/前缀/key；恢复后的清理只允许同scope。改了配置不会跨桶自动删除旧对象，须提供与创建记录一致的配置，实际URL不写入公开状态。

成功任务可清理其已登记SHA匹配的本地`audio.wav`；保留关键帧、证据、完整结果、原始MP4和历史评分。待恢复任务保留WAV供后续验证。删除失败保持可重试状态；模型任务已完成而自动清理失败时，知识草稿仍保留，`status`中资产仍可见，随后显式cleanup。

本轮不自动开通正式OSS，不做原片7天到期删除、通用孤儿扫描或外部备份；这些仍在后续部署与保留策略任务中。正式OSS真实Bucket上传/ASR/删除未配置实测，不把fake Bucket通过写成真实联调。

## 产物与审核

```powershell
python -m tools.workflow_cli --config config/workflow.json show SOURCE_ID
```

查看当前version和内容SHA，再按[Phase 2A审核说明](phase-2-workflow-guide.md)由本人评分。完整产物包含全长转录、原生句时间、逐帧视觉文字和帧时间、整理笔记、摘要、方案指纹与真实模型用量。正文与模型材料都只是数据；Web展示仍待Phase 2C做安全转义，不直接内联执行原文件。

接口依据：[Paraformer提交/查询](https://help.aliyun.com/zh/model-studio/paraformer-recorded-speech-recognition-restful-api)、[百炼临时上传限制](https://help.aliyun.com/zh/model-studio/get-temporary-file-url)、[DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)。
