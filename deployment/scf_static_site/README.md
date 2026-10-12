# VELO SCF 静态官网

只发布指定 Git commit 内的 `website/`，保留中英文首页、公司页、隐私页、Garmin 隐私页及原 ICP 展示。使用 **SCF Web 函数 + Python 3.10 原生 HTTP**，监听 `0.0.0.0:9000`；运行角色留空，无业务 API、数据库、凭据或外部 Python 依赖。

## 启动与传输

[官方启动合同](https://cloud.tencent.com/document/product/583/56126)要求包根目录的 `scf_bootstrap` 为 755、首行为 `#!/bin/bash`、LF 结尾，并使用对应运行时的绝对路径。本包执行 `/var/lang/python310/bin/python3.10 -B -u /var/user/http_server.py`，不依赖 PATH，不在只读代码目录写 pycache。

`http_server.py` 将 HTTP 方法、原始路径、请求域名头和查询参数交给只读 `handler.py`。返回体中的 Base64 在本进程解码后才写入 socket；`Content-Length` 按实际字节计算，只发送一个 Content-Type。HEAD 保留 GET 表示长度且无正文；304 无正文、无 Content-Length。重定向保留原始 query（包括重复键、空值与编码），不使用 `X-Forwarded-Host`。域名沿用 `x-scf-request-domain` 优先、Host 兼容的合同。

静态路由保留 GET/HEAD、目录 index、目录尾斜杠跳转、`www.weiluai.top` → `https://weiluai.top` 的 301、原 `404.html` 的 404、安全响应头与 `Cache-Control: no-cache`。ETag 支持 `If-None-Match` 的 304；文本支持 gzip。无 index 不列目录，其他方法一律 405；隐藏文件、越界/重复编码/异常路径拒绝，私有包文件不公开。Range 返回完整资源（200）。HTTP 服务每实例最多两个处理线程、连接读写超时 5 秒，每次响应后关闭连接，不读取请求体、不记录 HTTP 内容或平台注入的秘密头。

2026-10-12 旧事件函数真实验收发现：文本页正常，但 PNG/JPEG/WOFF 和 gzip 均返回声明长度却无正文（curl 18），包括 50 KB 字体。证据保留在离线备份 `domain-and-icp/scf-function-url-verification.json`。这否定了旧 Function URL 链路的二进制可用性；本包改用[官方 Web 原生 HTTP 模式](https://cloud.tencent.com/document/product/583/73483)，不继续猜测事件响应配置。`handler.main_handler` 现在仅是内部路由函数，**不是云端部署入口**。

## 构建与本地验证

```sh
python3 -m unittest discover -s tests -p 'test_scf_static_*.py' -v
python3 deployment/scf_static_site/build.py \
  --revision <REVIEWED_FULL_COMMIT_HASH> \
  --output /tmp/velo-scf-static-site.zip
```

完整 commit 必须包含三个运行文件和 `website/`；构建器只读 Git blob，忽略未提交/未跟踪内容，并拒绝未以 100755 提交的 bootstrap。ZIP 根目录包含 `scf_bootstrap`、`http_server.py`、`handler.py`、`deployment-manifest.json`、`website/`。清单记录源 commit、每个文件的源路径/大小/SHA-256/权限、Web 类型和监听地址；旁附 `.zip.manifest.json` 记录包 SHA-256。

ZIP 使用固定时间戳、排序和 ZIP_STORED，bootstrap 为 0755、其余文件为 0644，不依赖本地时区、mtime、zlib 或脏工作树；相同提交生成相同字节。构建拒绝隐藏文件、符号链接、子模块、非静态扩展名及 uploads/backups/node_modules，不带 .env、Git、备份或用户上传文件。

[Web 配额](https://cloud.tencent.com/document/product/583/56124)限制响应 body 6 MB；[部署限制](https://cloud.tencent.com/document/product/583/73923)为在线 ZIP 小于 50 MB、展开小于 500 MB。构建继续使用原有包含 JSON 转义/Base64 膨胀与 4 KB 头预留的保守内存/大小上界，比真实 HTTP body 更严格；任一超限直接失败。初始官网基线 `89b7a223370a9991dbdf4103d27ae03faa22d9fe` 最大文件为 `website/data/segments.json`（2,129,465 字节）。

## 云端配置与验收

新建 **Web 类型**函数，Python 3.10、128 MB、10 秒；上传该 ZIP，使用包内 `scf_bootstrap`，运行角色留空，单实例请求并发配置为 1。公网 Function URL 选择开放；同源官网不需要 CORS。证书维护函数仍独立使用事件类型和专用最小角色。

先对真实 Web Function URL 逐字节比较 PNG/JPEG/WOFF、gzip 解压内容与源码 SHA-256，并验收页面/HEAD/301/308/404/304/405及路径防护。此前本地通过不能代替此步骤。Function URL 是测试入口，平台可能附加下载保护，浏览器页面展示要在自定义域名阶段验收。

之后为 `weiluai.top`、`www.weiluai.top` 分别绑定该 Web 函数同地域 URL，使用覆盖全部路径的 `/*` 映射并关闭路径重写，配置证书及强制 HTTPS，再按实际 CNAME 调整 DNS。分别验证根域页面、www 保留 URI 的 301、资源字节、HTTPS/TLS 和浏览器布局；业务后端暂停不在本包验收范围。[官方域名与映射说明](https://cloud.tencent.com/document/product/583/110861)。当前代码与本地检查不宣称云端 Web、DNS、备案或告警已经验收。
