# Phase 2C1 网页流程验收

日期：2026-11-05。先定义[W01–W16](phase-2-web-test-cases.md)及[API契约](phase-2-web-contract.md)，再实施FastAPI、持久派发和React，合并后做独立审查与真实浏览器验收。本轮范围为三个网页流程，不是整个Phase 2完成。

## 自动回归与构建

- Python完整unittest：235项，233通过、2项既有POSIX媒体用例在Windows跳过；新增Web领域/派发16项、API14项，共30项。
- 前端Node测试：7组全部通过，覆盖分数门槛、上传限制、进度与时区等辅助规则。Vite生产构建通过，保留精确版本与package-lock。
- Python主依赖及传递依赖18项锁定在web-requirements-lock.txt；只安装到隔离目录，未修改系统Python。
- 独立只读复核：API+服务30/30、前端7/7通过，此前5个问题关闭，无新增已知阻断。

## 浏览器实际操作

使用本机`http://127.0.0.1:8765/`，数据为2B V01独立副本与新建测试HTML，视频调用开关关闭，不加载秘密执行模型。

| 用例 | 真实结果 |
|---|---|
| W01/W02/W04 | 选择文件对话框选择测试HTML，授权后上传；开始前无产物，点击开始后才派发并成功；未确认视频没有被抢先处理 |
| W05 | 真实V01显示21/21帧、24/24阶段；HTML完成后已打开详情自动出现新产物，无需重新选择资料 |
| W07/W12 | HTML中的script不执行，编码img/onerror显示为文本；缺失警告可见；原件只作附件 |
| W07 | 真实视频readyState=4、duration=20.48秒、无媒体错误，可播放/暂停；点击5.25秒帧后currentTime=5.25；21张JPEG逐一HTTP校验成功，原件Range返回206 |
| W08/W09 | 测试资料输入97分不能批准；99分显式approve后资格有效，再80分rework即时失效；仅测试HTML写入2条评分 |
| W10/W11 | 修订后新版本未审核；两个标签页并发修改，第一个标签页99分旧表单收到更新提示且按钮禁用，旧输入未自动绑定新版；多标签页会话不互相破坏CSRF |
| W14 | 浏览器实际下载Markdown，含版本/SHA和draft_or_inactive；当前测试HTML已3个版本，历史保留 |
| W16 | 桌面文档宽980/滚动宽980；窄屏文档宽375/滚动宽375，无横向溢出；重置viewport；第二标签页控制台错误为空 |

W03/W06/W13等危险/故障路径通过API与领域故障注入验证：声明/实际大小、JSON1MiB、无授权、恶意文件名、Host/Origin/CSRF、过期派发重排、未知外呼不自动重发。未声称在云端真实硬杀付费任务。

## 修复记录

1. 取消后重试先改queued再校验付费会留下可执行请求：改为事务内先授权，取消同事务撤销派发；回归证明未授权重试保持cancelled、无pending、fake runner调用0。
2. 帧时间字段错误、详情不更新：统一seconds/useRef，增加详情轮询与旧表单失效提示。
3. 补全六种文本编辑和上传大小/格式预检；使用中文状态及真实进度，不展示JSON调试对象。
4. JSON限量、非有限配置、非法CSRF、并发会话与第二标签页会话复用加固；数据库UTC，网页按配置Asia/Shanghai显示。

## 数据与费用核对

真实V01的审核记录仍为0，原件SHA一致；新建测试HTML的评分均带“仅测试资料”审核人。未将测试分数算作质量通过，未复制旧评分。当前正式资格仍为0。

本轮新模型调用0，同一研究账本保守预留仍22.00元。API详情没有lease_token、blob_relpath、file_url、object_key及实际两API Key。验收配置live_video_enabled=false，不开通正式OSS。

报告：[verification.json](../reports/phase2c-web-20261105-dadc8620/verification.json)。截图：[桌面](../reports/phase2c-web-20261105-dadc8620/browser-final.jpg)、[窄屏](../reports/phase2c-web-20261105-dadc8620/browser-mobile.jpg)、[旧版本禁用](../reports/phase2c-web-20261105-dadc8620/browser-version-conflict.jpg)。

## 保留边界

仍需2C2主题标签/批量管理、附件ZIP/Markdown重上传冲突和抖音链接/Cookie接入；尚未进入Phase 3。当前页面仅本机访问，正式认证/HTTPS、目标Linux资源/共存、硬杀与子进程治理、原片保留和外部备份在后续验收。关闭超时不冒称已终止远端任务。正式OSS真实Bucket链路仍未测。
