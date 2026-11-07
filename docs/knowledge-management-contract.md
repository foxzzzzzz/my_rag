# 分类管理与 Obsidian 往返契约

日期：2026-11-05，PRD v0.13。测试见[编码前用例](phase-2-management-test-cases.md)。

## 分类

主题与知识标签是来源级元数据，不等同审核问题标签。使用稳定分类ID、类型topic/tag、名称及别名；归一后同类型名称和别名唯一。关联和分类目录均带修订号，用户保存须提供预期修订号，不能覆盖其他标签页的更新。

分类不改变正文版本或评分，但更新长期笔记当前属性/校验状态；目录迁移不是分类操作。批量更新按来源单独事务并返回逐项结果，单项失败不假称整批成功。筛选维度间AND，同一维度多选OR；未审核内容可在管理页看到，正式问答仍遵守批准及同步校验。

SQLite是分类和审核的信任根，当前note.md及下载包含分类快照；不可变内容版本不随分类改写。名称/别名变更沿用稳定ID；源文件和机器输出保留。

## Obsidian 格式与审核

保留已有含完整证据的Markdown下载；新增明确标识的可编辑Obsidian笔记格式及附件ZIP。可编辑正文为笔记，标题与分类在属性中，证据/原始正文以只读附件或结构化证据保存。格式标识、稳定note/source ID、基准版本与内容SHA用于识别，不能凭上传自报review_status获得批准。

上传只做安全解析并持久预览，不修改知识；页面展示当前/上传差异、基准冲突及允许动作。选择保留服务端不变更；采用上传内容需再次核对预览时当前版本和元数据版本，创建human_edited版本并待审核。重复应用预览幂等。无内容变化不新增版本；仅分类变化不制造正文版本。

附件/证据仅允许当前已有材料的受校验副本，不能借ZIP替换原件。未知/新增图片暂不自动接纳；非法ZIP、越界路径、重复成员、过大体积、伪造身份/基准明确拒绝。CLI和网页共用协议，不引入任意YAML执行或远程资源加载。

配置分别放config/classification.json与config/obsidian.json，含名称/别名/批量数、ZIP/正文大小、预览有效期等含义。演示与真实目录隔离；不改写既有真实评分。手工分类/Obsidian往返不调用模型；PRD v0.16的AI建议仅在明确同意后调用既有text模型，生成/应用分离、预算及CAS边界见[2D补充契约](phase-2-integration-contract.md)，不新增服务Key。

## 已实现 API（PRD v0.13）

| 方法/路径 | 作用 |
|---|---|
| GET/POST `/api/classifications` | 读取目录`{items:[]}`/创建kind、name、aliases |
| POST `/api/classifications/{id}` | expected_revision、name、aliases更新目录 |
| POST `/api/sources/{id}/classification` | expected_revision、topics/tags的ID数组更新来源 |
| POST `/api/classifications/bulk` | items含来源及预期revision，operation=add/remove/replace，topics/tags；逐项回执 |
| GET `/api/sources` | kind、q、重复topics/tags/reviews参数；默认不含删除来源；返回title/classification/review_status |
| GET `/api/sources/{id}/obsidian/note或zip` | 带稳定ID文件名的可编辑笔记/附件包 |
| POST `/api/obsidian/preview?filename=...` | 有界原始文件字节，持久preview_id、当前/上传内容与分别的正文/分类冲突 |
| POST `/api/obsidian/apply` | preview_id、keep_server/use_uploaded，原子更新及幂等回执 |
| GET `/api/douyin/status或jobs` | 只返回配置存在状态或安全下载任务，不返回凭据/媒体URL |
| POST `/api/douyin/import` | share_text、rights_confirmed，持久排队，不自动调用模型 |
| POST `/api/douyin/jobs/{id}/retry` | 显式重试下载；不复活未知模型POST |

所有写入沿用会话/CSRF与安全文本展示。Obsidian支持常见受限属性格式，不执行通用YAML；已有归档MD与新可编辑格式明确分开。抖音任务使用同一全局单worker互斥；租约过期恢复不依赖Cookie或下载配置有效性，不能因可选功能缺配置阻断HTML任务。
