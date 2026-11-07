# PersonalKB

PersonalKB 是一个面向单用户的自托管知识库。它把有权处理的视频和 HTML 整理成可长期保存的 Markdown 和原始证据，经过人工审核后，可按资料、主题或标签检索和问答。

## 功能

- 导入视频和 HTML，跟踪处理任务，查看正文与来源证据。
- 审核、评分和修订资料。使用主题和标签组织资料，导出 Markdown 和附件到 Obsidian。
- 从已批准的资料构建索引，支持本地关键词检索和混合检索。问答可展开引用查看证据，依据不足时给出拒答。
- 通过 HTTPS 和密码保护知识库。Docker Compose 分开运行 Web 和单个 worker，支持冷备份、快照校验和独立目录恢复。

## 下载代码

服务器部署以 Ubuntu 24.04 x86-64 为目标。准备 Git、Python 3、Docker Engine 和 Docker Compose 插件，并配置域名、TLS 证书及同机 Nginx 反向代理。

首次获取代码可执行以下命令。

```bash
mkdir -p "$HOME/my_rag/personalkb" &&
git clone --branch main https://github.com/foxzzzzzz/my_rag.git \
  "$HOME/my_rag/personalkb/app-git"
```

默认目录布局如下。`app-git/config/` 是仓库内的配置模板，服务器使用同级 `config/` 中的生产配置。

```text
~/my_rag/personalkb/
├── app-git/                 # Git 检出目录
├── config/                  # 生产配置
├── state/                   # 资料、审核、索引和预算账本
│   └── tmp/                 # 应用临时目录
├── secrets/personalkb.env   # 登录哈希和模型凭据
└── backups/                 # 冷备份快照
```

## 一键部署

### 已有服务器

从手工部署切换到 Git 时，在原安装根目录下新建上面的 `app-git` 检出目录。继续使用同级的生产配置、秘密文件、资料和备份目录。确认没有正在处理的任务，并在切换前完成冷备和快照校验。[备份与部署操作](deploy/README.md)

### 新服务器

首次安装时，将示例中的 `kb.example.com` 替换为你的知识库域名，再准备生产配置和登录口令。

```bash
(
  set -eu
  cd "$HOME/my_rag/personalkb/app-git"
  mkdir -p ../state/tmp ../backups ../secrets
  chmod 700 ../state ../state/tmp ../backups ../secrets
  python3 deploy/configure.py --hostname kb.example.com --output ../config
  python3 -m tools.auth_setup \
    --config ../config/auth.json --output ../secrets/personalkb.env
)
```

口令由终端私密提示输入。如果两次输入不一致且生产配置已生成，只需重试 `tools.auth_setup` 命令。

将 HTTPS 虚拟主机代理到 `127.0.0.1:8768`，并核对域名和证书。[Nginx 配置模板](deploy/nginx.conf.template) · [域名和证书操作参考](docs/phase-4-server-guide.md#2-dns证书与独立nginx配置)

迁移已有资料时，请准备原安装导出的迁移包。在 `app-git` 目录按手册第 3 节执行独立目录导入、核验和数据放置，再回到本页执行一键部署。[迁移操作参考](docs/phase-4-server-guide.md#3-构建迁移与启动)

### 执行部署与后续更新

已有服务器完成冷备后，或新服务器完成一次性准备后，从 Git 检出目录执行以下命令。

```bash
cd "$HOME/my_rag/personalkb/app-git" &&
sudo sh deploy/deploy.sh --check &&
sudo sh deploy/deploy.sh
```

预检成功时显示 `Preflight passed`，部署和健康检查完成时显示 `Deployment healthy`。脚本构建候选镜像，切换本项目的 Web 和 worker，并验证回环和 HTTPS。升级切换失败时，脚本尝试恢复旧镜像并核对服务状态。数据库和资料通过冷备恢复。

后续升级前也应结束正在处理的任务，保留经过校验的冷备，再在同一检出目录拉取更新并部署。

```bash
cd "$HOME/my_rag/personalkb/app-git" &&
git pull --ff-only &&
sudo sh deploy/deploy.sh
```

## 使用

1. 访问配置好的 HTTPS 域名，用设置的口令登录。
2. 导入资料，查看正文与证据，完成审核。批准后可将资料纳入索引。
3. 在问答页按需选择资料范围。本地关键词检索无需模型费用。构建索引、混合检索和生成回答需要配置相应模型凭据，并确认本次费用。

模型凭据保存在服务器的 `secrets/personalkb.env`。生产配置默认关闭视频和 HTML 的实时模型处理以及抖音链接下载，按需启用。请将资料、数据库、备份和秘密文件保存在代码检出目录之外。[问答与引用指南](docs/phase-3-rag-guide.md) · [服务器凭据配置](docs/phase-4-server-guide.md#4-启用真实处理与重新建索引)

## 技术栈与文档

后端使用 Python、FastAPI 和 SQLite，检索使用 SQLite FTS5 和 sqlite-vec。前端使用 React 和 Vite，视频处理使用 FFmpeg。生产环境通过 Docker Compose 运行，由 Nginx 提供 HTTPS 入口。

| 文档 | 内容 |
| --- | --- |
| [产品规格](docs/PRD.md) | 功能范围、数据规则和审核边界 |
| [部署说明](deploy/README.md) | Git 部署、运行参数、备份和恢复 |
| [部署验收](docs/phase-4-validation.md) | 已实测的服务切换、资料和索引验证 |
| [实施计划](docs/PLAN.md) · [待办](docs/TodoList.md) · [变更记录](docs/CHANGELOG.md) | 当前进度与后续验收 |

现有服务器从手工部署切换到 Git 一键部署已验收。空机首装与故障回滚已有本机回归，目标服务器演练单独记录。[验收范围](docs/phase-4-test-cases.md)
