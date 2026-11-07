# 离线工具协议

> **协议范围：annotated_benchmark（历史v0.1/以后可选专项基准），不是当前审批协议。** 依据 [PRD v0.2](PRD.md)，现有3视频+2HTML直接真实转换展示，由本人整体0–100分及approve/rework/reject评审，默认≥98分且明确批准。无强制gold/样本数量；主观98分不等于本工具计算的98%准确率/覆盖率。当前协议见 [personal-review-contract.md](personal-review-contract.md)，用例见 [personal-review-test-cases.md](personal-review-test-cases.md)。

旧 `formal_pass`、`formal_eligible`、`passed` 仅表示下述专项标注基准结果，**不代表当前personal_review批准、审核就绪、选型冻结或RAG写入授权**；`config/acceptance-policy.json` 是该旧基准配置，不是新工作流审批政策。新工作流必须绑定来源哈希、run_id、方案及不可变输出版本，分开保存机器原始/人工修订结果；内容变化重评，同版本最新决定撤销过时批准。当前离线评审不实际入库。

以下CLI和字段保留为旧工具兼容说明，不能要求当前用户先完成这些数据才能运行demo。启用专项benchmark时单独报告，预算100元及离线预检边界仍有效。

## 历史 v0.1 / 可选专项标注基准协议

运行 `python -m tools.research_cli --config config/research.json validate --root 样本目录 --manifest 清单.json`；`freeze` 增加 `--lock 锁.json`；`evaluate` 增加 `--lock 锁.json --results 结果.json`。`budget-check --actual 0 --pending 0 --new 100` 用人民币十进制金额。命令成功返回 0，结构错误返回 2；预算超限和正式验收未达标返回 1。冻结使用独占创建，绝不覆盖。

清单为 `{"samples":[{"id":"v1","kind":"video","split":"dev","path":"video/v1.mp4","sha256":"文件SHA256","annotation":"gold/v1.json","duration_seconds":60,"tags":["口播"],"rights_confirmed":true}]}`。视频 split 为 dev 或 acceptance，HTML 的 kind 和 split 均为 html。标注为 `{"reviewer":"姓名","confirmed":true,"facts":[{"id":"g1","text":"事实","evidence":{"type":"audio","start":0,"end":1}}]}`。路径相对 root，文件均须存在；视频标注非空，视频时长为正的有限秒数，HTML 时长为 null；媒体的内容不得重复。标签覆盖与扩展名由配置指定，rights_confirmed 必须为 true。视频事实 evidence 必须含类型、起止秒且在视频时长内；HTML 事实 evidence 可为 null。清单、配置快照及所有媒体和标注的内容哈希写入锁文件。

结果为 `{"split":"acceptance","version":"machine_initial","reviewer":"姓名","confirmed":true,"samples":[{"id":"v1","predictions":[{"id":"p1","text":"预测","decision":"correct","gold_id":"g1","evidence":{"type":"audio","start":0,"end":1},"duplicate_of":null}]}]}`。每个分集的视频必须全部提交；decision 为 correct、incorrect 或 duplicate；重复项 duplicate_of 指向同一视频内非重复项的预测 ID。正确项的证据类型为 audio、visual 或 audio_visual，时间单位为秒。machine_initial 是未经修改的机器原输出经人评分，human_reviewed 是人工修改后的结果，只有 acceptance 的 machine_initial 可获得 formal_pass，输出包含 passed、formal_eligible 和 formal_pass。工具只验证结构，无法证明语义或原输出未被修改。

预算检查仅为离线只读预检，不连接服务也不能阻断外部调用。

正式基线在 `config/acceptance-policy.json`，不接受 CLI 覆盖，冻结文件保存其快照。基线变更属于产品规格变更，须按项目规范记录版本；快照不是加密签名或不可篡改的可信根。实验配置阈值低于正式基线、样本量不足、非验收集或非机器初始输出均不能正式通过。报告给出准确率、覆盖率、配置阈值和未正式通过原因，零分母显示 null。

预算预检采用实验配置预算和正式基线预算中较低者作为上限。
