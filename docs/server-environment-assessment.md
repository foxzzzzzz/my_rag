# 目标服务器环境报告核对与索引压测准备

日期：2026-11-04。用户已回传`C:/Users/25311/Downloads/server-report.json`；原件快照与[核对记录](../reports/server-environment-20261104/assessment.json)保存，未修改下载原件。

最新进展：用户已回传目标索引完整report.json，配置及哈希核对通过；Linux一万块混合p95为36.26ms，索引阶段通过，见[目标机索引验收](target-index-validation.md)。下方压测操作保留供查阅，无需重复运行。

## 观察结论

| 项目 | 报告值 | 解释 |
|---|---|---|
| 系统/架构 | Ubuntu24.04.4 LTS / x86_64 | 已明确目标依赖环境 |
| CPU | 4核，affinity4 | 名义配置符合计划；有效cgroup配额未知 |
| 内存 | 总3.64GiB、可用1.72GiB | 共享业务正在运行，不能将总内存全部分配给知识库 |
| Swap | 约1.94GiB，总占用约0.49GiB | 不单凭占用推断当前持续换页，需负载监测 |
| 数据盘 | 根分区约39.26GiB，剩余11.63GiB | 高于8GiB停收线，但仅剩3.63GiB余量；不是40GB空盘 |
| Python/SQLite | 3.12.3 / 3.45.1 | 可准备隔离Python环境与真实扩展测试 |
| Docker | 已取得29.6.1版本 | 仅确认版本存在，未检查权限、运行服务或兼容性 |
| FFmpeg | 未检测到 | 当前PATH不可见，不断言整机从未安装；索引压测不需它，媒体验收仍需准备 |
| 百炼/DeepSeek | HTTPS401 | 网络可达、未认证；不代表Key权限/余额验收 |
| PyPI | HTTPS200 | 索引站点可达，实际wheel下载/安装仍以执行结果为准 |
| cgroup限制 | reliable=false | 不能据此判CPU/内存失败或通过，也不要求修改内核/容器安全设置 |

用户补充：服务器同时运行网站、小程序后台及其数据库；知识库共用根分区，数据库独立。当前按**应用数据库分开、物理磁盘容量仍共享**理解，不视为新增独立磁盘。保留原有服务运行，不释放/停止它们来制造验收结果。

环境信息已核对，不等于资源负载验收通过；整机峰值≤3GB、真实目标机检索p95≤1秒仍待测。现有可用内存说明可准备小规模单进程索引验证，但不保证媒体解码/抽帧余量。

## 下一步：只运行索引基准

下载[target-index-kit.zip](../reports/target-index-kit.zip)，上传到服务器根分区的工作目录；它不含.env、API Key、原视频/HTML或用户评分，含必要的获批文本块和已生成向量，因此仍是个人知识材料，请放在自己的目录中。

在上传目录运行：

```bash
python3 -m zipfile -e target-index-kit.zip target-index-kit
cd target-index-kit
mkdir -p reports
python3 -m venv .venv
.venv/bin/python -m pip install --target tmp/benchmark-deps -r config/research-requirements.txt
.venv/bin/python tools/index_benchmark.py
```

无需API Key、FFmpeg、GPU或sudo，无模型费用。保留网站、小程序和数据库正常运行，单进程测索引；安装只在工作目录的虚拟环境和tmp内进行。如果缺venv、pip或扩展无法安装，把报错回传，暂不修改系统或停服务。运行前如磁盘已低于8GiB或现有服务明显缺内存，先回报情况。

回传结果文件：

```text
target-index-kit/reports/index-benchmark-target/report.json
```

建议下载时命名为`target-index-report.json`，与第一次`server-report.json`区分。无需回传实验SQLite数据库。重复执行会拒绝覆盖旧数据库；需复测时在`config/index-benchmark.json`中将output改为reports下新目录。

验证内容：1万块/1024维，FTS、vec0余弦及混合p95；原始128块与9872合成扩充严格区分；更新/删除/回滚一致性；索引大小和进程采样峰值。新连接测试不清OS缓存、计时排除打开/加载扩展，不称冷启动。

基准报告中的`scope`沿用同一跨平台研究工具，仍标注local/synthetic；实际环境由报告的OS和Python字段识别。`target_server_pass=null`表示整机/完整资源验收仍未完成，不能把它误读为索引路径失败。Linux索引阶段是否达标将依据实际环境、p95及一致性单独判断。

## 包内检查及待验收范围

仅白名单13个文件：脚本、配置、必要向量/文本样本、README及SHA256清单。数据128块、1024维、15查询数量和哈希检查通过；ZIP CRC及逐文件SHA通过，无实际API Key。全新解压目录140块本机冒烟通过；这不是Linux1万块验收，也不是整机资源结论。

索引测试后，仍需解决cgroup有效资源未知并规划单媒体任务、整机内存/Swap、磁盘停收、中断和清理验证。原业务与数据库不由本项目操作。完整系统尚未实现的功能继续标记待验收。

月费问题按PRD v0.6独立保留在Todo，暂不作为核心指标或阶段阻断。服务器索引通过仍不能替代剩余媒体资源验收。
