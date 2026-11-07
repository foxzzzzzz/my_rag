# SQLite索引本地性能验证

日期：2026-11-04。结论：SQLite FTS5＋sqlite-vec的本机1万块原型满足p95≤1秒；**目标Linux服务器尚未验收，未冻结生产索引方案。**

## 数据与实现

实际安装sqlite-vec **0.1.9**、psutil **7.2.2**至被忽略的`tmp/benchmark-deps`，不修改全局Python。复用已获批材料的128个标题块及v4的1024维向量，校验分块哈希与维度；额外9872块以原文复制和确定性向量扰动合成，总计10000块。合成扩充只测试负载，不能解释为1万块真实知识的语义验收。

SQLite三表持久化正文、中文双字/英文词FTS5、vec0余弦向量；不再使用此前Python全量向量排序原型。混合检索分别取词法与向量Top10，用RRF融合并返回文本。SQLite采用WAL、synchronous=NORMAL；缓存等参数见`config/index-benchmark.json`。

## 实测

环境：Windows 11，Python3.14.10、SQLite3.50.4，主机16逻辑CPU、约12.8GiB内存。单进程顺序查询，无外部模型调用。

| 路径 | 暖缓存次数 | 暖缓存p50 | 暖缓存p95 | 新连接次数 | 新连接p95 |
|---|---:|---:|---:|---:|---:|
| 词法 | 100 | 5.77ms | 9.06ms | 10 | 14.11ms |
| 向量 | 100 | 28.23ms | 33.26ms | 10 | 33.47ms |
| 混合 | 100 | 33.74ms | 40.09ms | 10 | 40.13ms |

新连接计时从加载扩展和打开数据库后开始，未清理操作系统文件缓存，因此**不是冷启动或冷磁盘性能**。p95使用nearest-rank，10次时等于该组最大值；数据量和并发场景仍有限。

索引构建约5.82秒；数据库67,092,480字节，约63.98MiB。Python进程采样RSS峰值87,040,000字节，约83.01MiB；不是整机内存、不是全媒体处理链路峰值，也不能证明4GB服务器整体满足3GB门槛。

完整产物：[report.json](../reports/index-benchmark-20261104/report.json)。SQLite文件在同目录`benchmark.sqlite`，仅为实验索引，可重建。

## 正确性及边界

- 实际执行向量距离与原128块参照余弦数值核对，容差1e-5。
- 正文、FTS、向量三表计数均为10000；临时探针执行新增、更新、删除后均恢复。
- 独立用例先复现外层事务被提前提交的问题，再改用SAVEPOINT；外层更新/删除回滚及跨三表一致性通过。
- 约束来源的查询正确性通过；该路径用SQL scalar距离＋来源过滤，与全局vec0 KNN路径不同，**未压测过滤路径p95**。
- 尚未实现正式业务的审核状态/版本元数据隔离、增量任务队列、备份恢复等，不以实验库替代主体设计或验收。

本轮完整85项回归通过，含SQLite索引6项和环境脚本7项；独立审查确认本机/合成/新连接口径，提出服务器cgroup与成本伸缩一致性问题，均修正或明确为unknown。目标机按[自行验证指南](server-resource-validation.md)另测。

复现：

```powershell
python -m pip install --target tmp/benchmark-deps -r config/research-requirements.txt
python tools/index_benchmark.py
```

工具不覆盖已有benchmark.sqlite；复跑须在配置中指定新产物目录。官方API依据：[Python扩展加载与float32](https://alexgarcia.xyz/sqlite-vec/python.html)、[vec0 KNN/余弦接口](https://alexgarcia.xyz/sqlite-vec/features/knn.html)，核实于2026-11-04。
