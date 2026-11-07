# 目标服务器自行验证指南

日期：2026-11-04；用户选择自行执行脚本并回传报告，不提供SSH访问。

当前进度：环境报告已收到并核对，服务器为Ubuntu24.04x86_64且有既存业务；下一步请使用[目标索引包与运行说明](server-environment-assessment.md)。下方第一步检查说明保留供查阅，无需重复提交相同环境报告。

## 第一步：环境检查

将[server-readiness-kit.zip](../reports/server-readiness-kit.zip)上传到服务器的任意临时目录。系统需已有Python 3.8或以上；脚本只使用标准库，不需pip安装、sudo或API Key。

在上传目录运行：

```bash
python3 -m zipfile -e server-readiness-kit.zip server-readiness-kit
cd server-readiness-kit
python3 server_probe.py --config server-probe.json --output server-report.json --data-path / --network-check
```

将生成的`server-report.json`下载到本机并提供路径。若知识库将使用独立数据盘，把`--data-path /`改成该盘上已经存在的目录，例如`--data-path /data`。不要用临时tmpfs目录代表实际数据盘。脚本不会覆盖已有报告；再次运行时换一个输出文件名。

检查内容包括：Linux发行版、CPU架构/核数及亲和性、内存/Swap、cgroup v2限制、目标数据盘总量和剩余空间、Python/SQLite版本，以及Docker和FFmpeg是否可用。未知或无法可靠解析的资源限制返回unknown，不当作通过。只查工具版本，不启动、停止或安装服务。

`--network-check`可省略；加上后只向百炼、DeepSeek、PyPI固定HTTPS地址发起不带Key的访问，检查直接出网与TLS。401/403代表服务器可到达但没有认证，不表示模型权限或账户余额通过。不会绕过证书校验、跟随重定向或继承代理环境；如果实际部署必须经过代理或内网软件镜像，请一并说明。

脚本不读取.env、SSH文件、密码或进程列表；不采集公网IP/主机名。不需发送密钥或账号密码。报告包含系统版本和你指定的数据路径，可自行查看后回传。

报告以外，请补充一句：**这台服务器是否还运行其他业务、数据准备放在哪个目录**。这决定空闲内存、磁盘和并发预算；Docker版本存在不代表服务正在运行或可用。

## 第二步：目标机负载验证

收到环境报告后，再按实际架构准备目标Linux的sqlite-vec依赖和可复现负载包。先在目标机运行1万块检索及三表一致性验证，区分本地Windows结果。

随后验证单任务媒体解码、音频转换、抽帧、索引与问答时的整机/进程峰值、可用空间<8GB时停收、任务中断和清理。若完整业务尚未实现，相关系统级测试必须继续标记未验收，不能用环境脚本代替。真实模型连通和完整处理需要服务器本地安全配置Key，届时再明确调用范围与预留费用；第一步无需配置Key。

验收依据：4核、名义4GB内存、40GBSSD、无GPU；整机峰值目标不超过3GB，1万块排除外部模型调用后p95≤1秒，可用磁盘低于8GB停收。环境配置合理与真实负载通过是两件事。

## 本地准备验证

环境脚本7项模拟用例通过，包括嵌套cgroup v2取最严格限制、CPU affinity、无法解析时unknown和HTTP错误响应关闭；尚未运行于真实目标Linux。工具与配置见`tools/server_probe.py`及`config/server-probe.json`。
