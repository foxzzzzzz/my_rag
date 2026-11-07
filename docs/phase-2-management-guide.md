# 分类、Obsidian 往返与抖音链接操作说明

日期：2026-11-05，PRD v0.15。当前本机入口：<http://127.0.0.1:8765/>。

当前页面沿用`reports/phase2-content-20261105-07d9f46d/workflow.json`的数据，真实材料版本和评分未变。下方CLI示例中的`config/workflow.json`是正式开发默认目录；操作当前演示时须替换为上述workflow配置，避免选错数据库。

## 主题、标签与批量管理

在“分类”页手动创建主题、知识标签及别名；名称/别名在同一类型内不能重复。重命名沿用稳定ID，不需要移动笔记文件。当前提供人工分类，AI建议分类仍列后续待办，不冒充已自动分类。

资料库可按标题/文件名、类型、审核状态、多主题和标签筛选；维度之间为AND，同类多选为OR。资料详情可修改多个主题与标签，保存不改变正文版本或已有评分；同步失败时仍会暂停正式资格。

勾选资料后可追加、移除或替换分类。**替换会清除原主题及标签再使用所选值。** 批量提交保留勾选时的修订号；其他页面已更新的资料会逐项报告冲突，不覆盖。冲突后重新选择资料、核对当前分类，再保存。该过程不调用模型。

## Obsidian 导出与更新

详情页有两个不同用途的导出：

- “Markdown（含证据正文）”：完整归档阅读，沿用既有格式。
- “可编辑笔记”及“笔记与附件 ZIP”：用于本地修改后重传，格式标识`pkb-obsidian-v1`。下载文件名含稳定来源ID，避免多份笔记重名。ZIP内编辑`note.md`，其余证据和图片只读；将每个ZIP解压到独立目录，README中有附件相对链接。

修改可编辑笔记正文或标题后，在资料详情或“导入”页选择`.md`/`.zip`，点击“上传并预览差异”。此时尚不修改资料。核对服务端/上传笔记、标题、主题标签及正文/分类基准冲突后，选择“保留服务端”或“采用上传内容并重新审核”，再确认应用。

正文变化会生成独立人工版本，新版需本人重新评分；旧版本和评分保留。只改分类不制造正文版本；无变化不制造重复版本。预览后别人又改正文或分类时必须重新预览，不能直接覆盖。重复应用同一预览幂等；过期预览需重新上传。

保留笔记顶部的稳定ID、基准版本和SHA；不要把原归档MD直接当可编辑格式上传。属性支持JSON风格双引号、普通文本/单引号标量及简单列表；不支持任意YAML对象、标签/锚点展开和多行属性。`topic_ids`/`tag_ids`引用已有分类ID，未知ID不自动建类；分类主要在网页管理。尚未进行真实Obsidian客户端版本/插件改写属性的联调，不宣称所有插件格式都兼容。

上传自报`approved`无效，不能替换原视频、原HTML、证据JSON或关键帧；新增附件暂不从重传包接纳。ZIP不会落地任意解压，路径、重复项、符号链接、压缩/实际解压量均受限。限制和24小时预览默认值在`config/obsidian.json`。

CLI示例（不联网）：

```powershell
python -m tools.obsidian_cli --config config/workflow.json export-note <来源ID> --output tmp/editable-note.md
python -m tools.obsidian_cli --config config/workflow.json export-zip <来源ID> --output tmp/obsidian-export.zip
python -m tools.obsidian_cli --config config/workflow.json preview tmp/editable-note.md
python -m tools.obsidian_cli --config config/workflow.json apply <preview_id> --choice use_uploaded
```

导出不覆盖已有输出文件。CLI和网页共用同一协议；预览和正式任务/审核恢复仍依赖数据库备份。

## 抖音：已实现但默认关闭，真实下载待配置

本次隔离验收可通过完整配置复核缓存（不启动模型）：`python -m tools.douyin_cli --config tmp/d19-isolated-3/workflow.json --douyin-config tmp/d19-isolated-3/douyin.json jobs`。该目录与当前网页库不同，不要将验证用库替换为正式数据；执行清单在同目录execution-manifest.json。真实凭据仍从.env/指定秘密入口读取，验收配置不包含Cookie。

最新（PRD v0.15）：用户已选择download_policy=authorized_playback，确认有权处理后保存平台返回的播放媒体，allow_download等标志不再单独拦截；strict保留旧检查。实际访问拒绝仍停止，不处理验证码/付费限制。media_referer必须为https://www.douyin.com/，仅对媒体域名发送，Cookie不发往CDN。

当前作品已在隔离库完成真实下载、统一导入、完整解码及重复缓存验证（D05通过此样本），未写入当前网页库或自动处理。全局模板enabled仍false、resolver_python仍待配置；正式使用仍按本页配置独立Python、Cookie及开关。workflow配置ffmpeg应指向可执行文件或PATH可用命令；本机已存在工具示例为D:/codex_project/My_RAG/PersonalKB/tmp/media-inspect-deps/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v9.0.2.exe，部署时替换为目标机器路径。缺工具会显示明确错误，不能用跳过媒体校验解决。

下面v0.14的“当前作品拒绝、D05未过”为历史strict模式结果，已被用户新授权策略和本次真实闭环更新；字段本身未被改写或假称为允许。

2026-11-05更新（PRD v0.14）：默认resolver_mode=minimal_detail，直接动态构造固定无尾斜杠详情端点的三参数，已用成功Cookie/UA通过正常解析入口取得目标许可结果，不需要每条复制签名URL。detail_aid/detail_version_code为外置数字字符串；max_detail_response_bytes同时限制原始和解压正文；download_chunk_bytes须不超过该限制。独立Python仍需安装httpx；只有手动选择resolver_mode=f2时使用旧SDK/Token路线，失败不自动切换。

当前测试作品接口标记allow_download=false、prevent_download_type=2，任务应提示平台禁止下载；未知/非法许可也拒绝。用户实测simpdown可下载同作品，但该扩展未检查这些字段，项目规则仍保持。D05下载/导入未通过，enabled仍为false，.env未改；之前403记录是历史F2路线，不应理解为minimal_detail仍然403。更换模式时需为已有私密配置补齐新字段，可参考完整config/douyin.json，不覆盖Cookie。

支持单条抖音分享文本、`v.douyin.com`短链和作品链接；默认关闭，不扫描账号/收藏，不自动获取浏览器Cookie。下载成功进入普通素材队列，仍需另行同意ASR/视觉费用并启动处理，最后由本人审核。解析失败或平台不允许下载时，可上传自己有权处理的MP4兜底。

本地参考：[TokBrain分析](../../TokBrain/project-analysis.md)。复用F2的单作品接口思路，**不导入其完整应用，也不使用Windows DPAPI保存云端Cookie**。F2和现有Web依赖版本有差异，必须使用独立Python环境。

### 准备独立解析环境

不需要新增模型API Key。Windows示例（先确认对应Python已安装）：

```powershell
py -3.12 -m venv .venv-douyin
.venv-douyin\Scripts\python -m pip install -r config/douyin-resolver-requirements.txt
.venv-douyin\Scripts\python -m pip install --no-deps -r config/douyin-resolver-f2.txt
```

Ubuntu示例（在独立应用目录，不操作原网站/小程序环境）：

```bash
python3 -m venv .venv-douyin
.venv-douyin/bin/python -m pip install -r config/douyin-resolver-requirements.txt
.venv-douyin/bin/python -m pip install --no-deps -r config/douyin-resolver-f2.txt
```

不要让pip自动安装F2自己的旧依赖列表，也不要混装到Web环境。当前本机Python3.14独立环境可构造SDK；历史工具未覆盖导入隐式同步Token请求，不能据旧记录承诺完整零网络。真实详情接口匹配UA仍403，D05未通过；D07修复见[联调记录](douyin-live-validation.md)。Python3.12尚待目标机验证，不同Python对应的Pydantic/PyYAML版本已在requirements条件中标明。

### 获取网页登录 Cookie（电脑 Chrome / Edge）

1. 打开`https://www.douyin.com/`，用本人账号正常登录，并打开一条视频。
2. 按F12（或Ctrl+Shift+I）打开开发者工具，选择Network/网络，再刷新页面。
3. 可切换Fetch/XHR并搜索`aweme`；选择Request URL属于`www.douyin.com`的请求，不选视频CDN资源。没有匹配时清除筛选，重新选择抖音站点请求。
4. 右侧选择Headers/标头，展开**Request Headers/请求标头**，找到**Cookie**，复制完整字段值。仅复制`name=value; name2=value2`这一串，不包含`Cookie:`前缀；不要复制Response Headers里的Set-Cookie，也不要只取sessionid一项。
5. 同一请求中的User-Agent也可一并复制，填入下述user_agent配置；它不是Cookie。若显示临时请求标头，刷新后选择一条已完成的请求。

Cookie属于登录凭据，仅在本人机器/服务器的私密文件中填写；不要把Cookie、包含它的截图或整段cURL发到聊天。不要在浏览器Console运行陌生脚本获取Cookie。

操作依据：[Chrome Network官方说明](https://developer.chrome.com/docs/devtools/network/reference)、[F2抖音接口说明](https://f2.wiki/guide/apps/douyin/cli)。本文步骤不代表当前Cookie已经验证成功。

### 本次 Windows 本地联调的准确位置

Cookie填写在`D:/codex_project/My_RAG/PersonalKB/.env`，保留原有两个模型Key。若已有同名空项，替换原行，不重复新增；值保持一整行：

```dotenv
PERSONALKB_DOUYIN_COOKIE='把完整Cookie值粘贴在这里'
```

当前页面读取项目根目录`.env`。在`D:/codex_project/My_RAG/PersonalKB/config/douyin.json`中只调整下列字段，其余参数保留：

```json
{
  "enabled": true,
  "resolver_python": "D:/codex_project/My_RAG/tmp/douyin-resolver-env/Scripts/python.exe"
}
```

上面仅展示需要修改的两个字段，不能用它覆盖整个配置文件。此独立环境本机已存在、完成构造检查，完整零网络边界另见D07；属于临时开发环境，部署到服务器时应另建独立环境并更换为Linux路径。`user_agent`建议使用同一浏览器请求里的完整User-Agent。

配置后到当前`http://127.0.0.1:8765/`的“导入”页点击“重新检查下载配置”，通常无需重启。三个configured/enabled检查只说明本地配置存在，不验证Cookie有效性；后续以实际单条链接的解析/下载为准。Cookie过期或退出登录后，重新获取并替换原项。

### 私密配置与真实验证

在本机`.env`私密配置`PERSONALKB_DOUYIN_COOKIE`，不要发送到聊天或放入前端。`config/douyin.json`设置独立Python的绝对路径`resolver_python`，准备好后手动设`enabled=true`。也可复制一份私密配置，由所用`web.json`的`douyin_config`指向它；模板不存真实Cookie。

回到“导入”页点击“重新检查下载配置”。“配置存在”只表示本地字段存在，不表示Cookie已验证有效。提交一条本人有权处理且平台允许下载的公开视频，确认下载任务、原件、SHA去重、错误/兜底及随后视频处理。**未完成此步骤前D05保持未验收，不把测试替身当真实下载。**

Cookie只经标准输入交给独立解析器，不进入argv/继承环境/日志/API返回；F2日志初始化被禁用，原始错误和媒体签名URL不落库。下载逐跳校验域名和公共IP，固定已核验IP连接并保留原域名TLS验证；DNS、连接、读取、大小及磁盘均受限。运行租约在最终来源写入事务再次检查；过期任务待明确重试，不自动启动模型。

```powershell
python -m tools.douyin_cli --config config/workflow.json status
python -m tools.douyin_cli --config config/workflow.json import "<单条分享链接>" --rights-confirmed
python -m tools.douyin_cli --config config/workflow.json run-once
python -m tools.douyin_cli --config config/workflow.json jobs
python -m tools.douyin_cli --config config/workflow.json retry <下载任务ID>
python -m tools.douyin_cli --config config/workflow.json recover
```

实际CDN、Cookie状态、F2版本兼容及平台权限由真实联调确认；不能保证所有作品可下载。不支持任意自定义解析可执行程序或恶意派生进程；目标Linux硬中断/资源共存仍属后续验收。本轮没有修改云服务器、开通OSS或新增模型调用。
