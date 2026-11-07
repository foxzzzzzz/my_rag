# kb子域：云控制台证书手动安装

日期：2026-11-06。本人确认官网证书采用云控制台下载、手动上传配置；知识库沿用此方式，不安装Certbot、不改官网证书。以下命令由本人在服务器执行，本机未代为操作。

## 1. 申请和下载

在现有云SSL证书控制台申请覆盖`kb.yuanzhll.top`的证书，按控制台完成域名验证；已有有效通配证书`*.yuanzhll.top`或包含kb名称的多域证书也可使用。签发后选择**Nginx格式**下载，取得证书链文件和与其配对的私钥。[云平台Nginx安装说明](https://cloud.tencent.com/document/product/400/35244)

证书链文件常见名为`kb.yuanzhll.top_bundle.crt`或`_bundle.pem`，私钥为`.key`。使用完整证书链，不要只取根CA文件；Nginx要求服务器证书在前、中间证书随后。[Nginx证书链说明](https://nginx.org/en/docs/http/configuring_https_servers.html)

## 2. 上传并安装证书文件

先将证书文件放到本人服务器目录，例如`~/kb-cert/`；私钥不要发到聊天。以下以实际文件名与示例一致为前提，不一致时替换源文件名：

```bash
sudo install -d -m 700 /etc/nginx/ssl/personalkb
sudo install -m 644 ~/kb-cert/kb.yuanzhll.top_bundle.crt /etc/nginx/ssl/personalkb/fullchain.crt
sudo install -m 600 ~/kb-cert/kb.yuanzhll.top.key /etc/nginx/ssl/personalkb/privkey.key
sudo openssl x509 -in /etc/nginx/ssl/personalkb/fullchain.crt -noout -subject -dates -ext subjectAltName
```

检查证书在有效期内、SAN包含kb或适用通配名。以上路径为知识库专用，不覆盖官网目录。若使用`_bundle.pem`，同样可以安装到fullchain.crt，关键是文件内容为正确的PEM证书链。

## 3. 核对站点位置并增加专属配置

先只查看Nginx是否已有kb配置、是否加载conf.d目录：

```bash
sudo nginx -T 2>/dev/null | grep -n 'server_name.*kb\.yuanzhll\.top'
sudo nginx -T 2>/dev/null | grep -E 'include .*conf.d|include .*sites-enabled'
```

第一条无结果可表示尚无专属站点；若已有kb的server块，就只调整该专属块，不再重复添加同名站点。第二条应显示`/etc/nginx/conf.d/*.conf`等已加载目录；如果实际使用其他目录，在实际加载目录新增配置，不盲改主配置，也不需要回传完整nginx -T。

已生成[知识库专用配置](../reports/phase4-20261106/personalkb-nginx.conf)，假设使用默认应用端口8768和上节证书路径。将它上传到`~/kb-cert/personalkb-nginx.conf`。确认没有现有同名配置、conf.d被加载后执行：

```bash
sudo install -d -m 755 /var/www/personalkb-acme
sudo install -m 644 ~/kb-cert/personalkb-nginx.conf /etc/nginx/conf.d/personalkb.conf
sudo nginx -t
```

若personalkb.conf已存在，先保留旧副本并仅合并/修正该文件，避免覆盖不明配置。**只在nginx -t成功后**执行：

```bash
sudo systemctl reload nginx
```

配置包含独立kb的80→HTTPS跳转、443证书、回环8768代理以及既定上传/事件流参数，不包含default_server、不改官网server_name，不需要给公网开放8768。实际应用端口若更改，配置中的proxy_pass也须同步。

## 4. 检查结果

```bash
curl -I http://kb.yuanzhll.top
curl -I https://kb.yuanzhll.top
```

HTTP应返回301并指向HTTPS；HTTPS不能再出现证书主机名/证书链错误，不要加`-k`绕过验证。

- 如果应用已启动：继续打开HTTPS页面登录，运行正式验收工具。
- 如果Docker应用尚未启动：HTTPS可能返回502，这表示后端回环8768暂不可用；只要证书验证正常，此时可先确认SSL，再按[服务器手册第三节](phase-4-server-guide.md)构建、迁移并启动。502不能算完整上线通过。
- 如果证书仍不匹配：检查专属配置是否被加载、是否有重复kb server块、ssl_certificate是否指向新证书，以及IPv4/IPv6实际访问路径。

回传`sudo nginx -t`及两条curl检查输出即可；不需要私钥或含秘密的配置。证书以后到期需按云控制台续签后更新专用文件、nginx -t通过再reload；手动安装不会自动续期。
