# Phase 4 目标服务器预检与子域核对

日期：2026-11-06。输入为本人下载目录preflight-report.json及DNS控制台截图。原报告已复制至[归档](../reports/phase4-20261106/target-preflight-report.json)，未修改下载原件。

## 结论

**目标服务器预检通过，可进入镜像构建和资料迁移准备；当前子域HTTPS尚未就绪，不能据此宣布上线通过。** 本轮没有操作服务器、修改Nginx或签发证书。

| 报告项 | 结果 | 判读 |
|---|---|---|
| 系统/架构 | Linux/x86_64 | 与部署包目标一致 |
| Compose | 可用，报告版本5.3.1 | 只确认工具可用，镜像实际构建尚待执行 |
| FFmpeg | 可用 | 不替代容器内媒体实测 |
| 生产配置/口令哈希 | config_valid/auth_valid=true | 当前预检读取的配置与哈希通过 |
| 秘密文件/权限 | 存在，private=true | 通过预检权限检查 |
| 应用端口 | 可用 | 当前没有占用冲突，不等于外网应开放该端口 |
| 磁盘剩余 | 15,494,434,816字节，约14.43GiB | 高于8GiB保留线；构建/迁移后需重查，不能全部用满 |
| model_key_in_environment | false | 仅宿主进程环境检测，不能据此断定挂载的秘密文件缺Key；模型权限/余额仍待后续真实验证 |
| tls_verified/domain_verified | false | 原预检工具不执行这两项；下面另有实际外部核验 |
| CPU/内存/资源共存 | 本报告未提供负载证据 | 不能把ready=true扩大为整机资源或完整Phase 4通过 |

## 子域实测

DNS截图为主机记录kb、A记录106.53.20.177、TTL600秒，结构符合独立子域需求。本机DNS查询实际返回`kb.yuanzhll.top → 106.53.20.177`，未取得AAAA地址；不将单地查询解释为所有网络均已同步。

对公开根路径各发一次HEAD，未跟随重定向，HTTPS使用默认CA与主机名校验，没有绕过证书错误：

- HTTP：200，Server为nginx/1.24.0 (Ubuntu)，无Location；尚未观察到HTTP→HTTPS跳转。
- HTTPS：主机名验证失败，证书不适用于kb.yuanzhll.top。这说明当前该SNI请求收到的证书未正确覆盖该子域；不能判断服务器是否另有未绑定的合适证书。

DNS只指向服务器IP，不会自动创建Nginx站点或安装证书。为此子域新增独立server块，配置匹配证书和到127.0.0.1:8768的代理，保留原官网配置。[Nginx官方HTTPS配置](https://nginx.org/en/docs/http/configuring_https_servers.html)

证书可以单独申请kb.yuanzhll.top，也可以复用有效且SAN包含该名称或适用通配名`*.yuanzhll.top`的证书；只含根域/其他子域的证书不能直接当作已覆盖。支持多域名证书不等于当前证书已经包含该子域。[Let's Encrypt证书名称说明](https://letsencrypt.org/docs/faq/)

## 下一步

1. 第一节预检已完成，无需重新生成口令或覆盖配置。
2. 按[服务器手册第二节](phase-4-server-guide.md)为kb添加独立Nginx站点，申请/选择覆盖该子域的证书并配置证书路径。证书未就绪时只启用HTTP/ACME部分，避免配置不存在的证书导致nginx -t失败。
3. `sudo nginx -t`成功后再reload，保留官网/小程序；应用继续只绑定回环8768，不对公网开放8768或数据库端口。
4. 执行手册第三节构建、迁移与启动，再运行第六节HTTPS验收工具。上线判断需证书验证、登录/CSRF、真实链路、共存及备份恢复证据。

本人随后确认采用云控制台下载、手动上传配置；已提供[具体SSL安装步骤](phase-4-nginx-ssl-guide.md)和专属站点配置，等待服务器执行与回传，不再重复询问证书管理方式。
