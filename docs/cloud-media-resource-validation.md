# 云端视频处理资源压测操作指南

日期：2026-11-04，PRD v0.6。月费仅列观察/优化待办，不再阻断当前阶段；预研累计模型额度仍100元。本轮不调用模型，不需要Key。

最新结果：用户已运行并回传，三视频离线媒体资源阶段通过，且反馈网站/小程序正常。见[目标机结果核对](target-media-resource-validation.md)。下方命令保留供回归，不要求重复执行。

## 你需要做什么

下载[media-resource-kit.zip](../reports/media-resource-kit.zip)，约139MiB，已含三条现有私有demo，上传到服务器自己的工作目录，例如`~/my_rag/`。不用再挑视频或改名。包内没有.env、评分或原HTML，视频仍是个人材料，不放到网站公开目录。

### 1. 准备FFmpeg

此前报告未在PATH检测到FFmpeg；若仍未安装，在服务器审阅并执行：

```bash
sudo apt-get update
sudo apt-get install --no-install-recommends ffmpeg
ffmpeg -version
```

Ubuntu24.04官方提供FFmpeg包：[Ubuntu noble ffmpeg](https://packages.ubuntu.com/noble/ffmpeg)。安装由你操作，测试脚本不会自动安装。报错时回传输出，无需停业务或修改软件源安全设置。

### 2. 解压并运行

以下从**压缩包所在目录**执行；若已进入解压后的目录，跳过前两行，不重复解压/cd。

```bash
python3 -m zipfile -e media-resource-kit.zip media-resource-kit
cd media-resource-kit
python3 -m venv .venv
.venv/bin/python -m pip install -r config/media-requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tools/media_resource_trial.py
```

工具适配当前Python3.12，只安装psutil7.2.2到虚拟环境。先看单元测试结果；如有失败，回传输出，暂不继续最后一行。缺venv/pip也先回传报错。每轮自动创建独立run目录，不覆盖旧报告。

网站、小程序和数据库保持运行。期间正常访问网站/小程序，记录有无明显变慢或报错；工具不主动检查业务接口。手动停止按Ctrl+C，会尝试终止自己启动的FFmpeg并保留部分报告。

### 3. 回传结果

```bash
find reports/media-resource-runs -name report.json -type f
```

下载最新run目录内的`report.json`，本机建议命名`media-resource-report.json`，并告诉我业务访问是否正常。即使`resource_stage_pass=false`或报错，也回传报告；必要时加该run的logs。不要自行调高阈值、停原有服务或清缓存来通过。

## 测试范围与保护

逐条处理4K短片、屏幕教程和长口播：完整视频解码（-xerror且验证progress=end、帧数/时长）、完整16kHz单声道音频、既有21/22/16时点的59张JPEG；记录字节/哈希。然后主动取消另一个解码任务，验证自己的进程组/后代已退出；无法验证则失败。最后只清理本次独占work内登记的3个WAV和59个JPEG，保留原视频、日志和报告。

默认解码/输出线程2、滤镜线程1、单任务，不是硬CPU隔离。每0.2秒记录本进程树RSS、整机可用内存/CPU/Swap和磁盘。触发以下任一条件停止本测试启动的任务，不操作其他业务：

- 整机`MemTotal-MemAvailable`采样代理值超过**3,000,000,000字节（3.0GB，约2.79GiB）**。
- 可用内存低于512MiB，或数据盘可用低于8GiB。
- 单个子任务超过900秒。

这是离线媒体预处理资源验收，不包含云模型上传/推理、正式业务队列或生产停收接口。研究工具的保护不能冒充尚未实现的系统能力；total-available是资源代理值，进程树RSS可能重复统计共享页，采样也可能遗漏瞬时峰值。业务响应另依据你的实际观察，不能只凭自动字段判无影响。

## 交付前验证

M01–M08已在[实施前用例](media-resource-test-cases.md)记录。完整项目99项unittest，Windows上97通过、2跳过（POSIX后代、符号链接环境限制），两项随包在Linux复验。后代测试允许无法证明清理时返回失败，只证明不误报通过；云端真实FFmpeg中断仍看termination字段。

本机真实完成三条全解码、3份全音频、59帧、主动中断与62个临时文件清理，共66阶段。**Windows功能冒烟放宽了主机内存阈值，不能作为目标3GB资源通过证据**；原报告在`reports/media-resource-local-smoke/`。独立审查发现进程组清理、解码证据及中断记录问题后已修复并复核。

包大小145,436,079字节。三视频SHA、59时点、3.0GB配置、源码一致性、ZIP CRC与逐文件SHA核对通过，未发现实际API Key。包内有SHA256SUMS，构建脚本在`tmp/build_media_kit.py`。
