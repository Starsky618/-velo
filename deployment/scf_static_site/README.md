# VELO SCF 静态官网

只发布指定 Git commit 内的 `website/`，保留中英文首页、公司页、隐私页、Garmin 隐私页及原 ICP 展示。无业务 API、数据库、环境变量或外部 Python 依赖。入口为 **`handler.main_handler`**，函数类型必须是**事件函数**，运行时 Python 3.10 或更新。

## 构建与本地验证

在完成审查的提交上构建；`--revision` 必须是完整 commit hash，且该提交已经包含本目录的 handler。构建器只读 Git blob，忽略工作树内未提交或未跟踪内容。

```sh
python3 -m unittest discover -s tests -p test_scf_static_site.py -v
python3 deployment/scf_static_site/build.py \
  --revision <REVIEWED_FULL_COMMIT_HASH> \
  --output /tmp/velo-scf-static-site.zip
```

ZIP 根目录只有 `handler.py`、`deployment-manifest.json`、`website/`；旁边生成 `.zip.manifest.json`，记录源 commit、文件清单、SHA-256、包大小和最大响应上界。ZIP 使用固定时间戳、排序、0644 权限和 `ZIP_STORED`，不依赖本地时区、mtime、zlib 版本或工作树。相同 commit 得到相同字节。构建器拒绝隐藏文件、符号链接、子模块、非静态扩展名及 `uploads/backups/node_modules`，不打包任何 `.env`、Git、备份或用户上传目录。

静态路由保留 GET/HEAD、目录 index、目录尾斜杠跳转、`www.weiluai.top` → `https://weiluai.top` 的 301、原 `404.html` 的 404、安全响应头与 `Cache-Control: no-cache`。ETag 支持 `If-None-Match` 的 304；文本支持 gzip。目录无 index 时不列目录，非 GET/HEAD 返回 405。隐藏文件、越界/重复编码/异常路径拒绝；请求无法选择静态根目录。无 Range/分段下载需求，Range 目前返回完整资源（200）。

## 腾讯云配置与真实验收

创建公网 Function URL，授权类型为开放；官网同源资源不需要 CORS。为 `weiluai.top` 与 `www.weiluai.top` 分别绑定同地域的函数 URL，配置覆盖全部路径的 `/*` 映射且关闭路径重写，配置证书并启用强制 HTTPS。按控制台实际返回的 CNAME 修改 DNS。根路径 `/`、子页面、资产路径必须分别真实验收，不能只验证首页。

协议按[官方 Function URL 概述](https://cloud.tencent.com/document/product/583/96099)及[官方国际中文版](https://intl.cloud.tencent.com/zh/document/product/583/69491)核对：输入使用 `httpMethod`、`path`、`headers`、对象形式的 `queryString`；输出 `statusCode`、`headers`、字符串 `body`。不读取 `requestContext`、`queryStringParameters` 或 AWS `rawPath`。URL 文档不提供原始 query 字节，跳转按 `queryString` 重新编码，不能保证重复键或原始编码形式保持不变。

域名判定优先读取 `headers["x-scf-request-domain"]`，仅在该字段缺失时兼容 `Host`；不读取 `X-Forwarded-Host`。[官方 Function URL 调用示例](https://cloud.tencent.com/document/product/583/47610)展示的事件包含 `x-scf-request-domain` 且没有 `Host`。真实自定义域名验收仍需分别确认根域返回页面、`www` 返回保留路径和查询参数的 301。

二进制和 gzip body 使用 Base64 字符串及 `isBase64Encoded: true`，依据[官方 Python 二进制集成响应示例](https://intl.cloud.tencent.com/zh/document/product/583/40327)。该示例描述 API 网关，而 Function URL 概述没有明确说明这个响应字段：**上线前必须用真实 Function URL 下载 PNG/JPEG/WOFF、gzip 资源，与源文件 SHA-256 比对；仅本地通过不证明网关已经解码。** HEAD、301/308、404、304、POST 405、路径防护也需在真实 URL 复验，再验收自定义域名与 TLS。

[配额](https://cloud.tencent.com/document/product/583/11637)：同步响应 6 MB；[部署限制](https://cloud.tencent.com/document/product/583/73923)：在线 ZIP 小于 50 MB、展开小于 500 MB。构建器采用十进制 MB 保守门槛，同时检查 JSON 转义、Base64 膨胀和 4 KB 响应头预留。初始官网基线 `89b7a223370a9991dbdf4103d27ae03faa22d9fe` 最大原文件是 `website/data/segments.json`（2,129,465 字节），完整结果见本次构建清单；超限直接构建失败，不静默漏资产。

[自定义域名与映射规则](https://cloud.tencent.com/document/product/583/110861)。本目录和本地测试不创建资源、不购买套餐、不改 DNS，也不能证明备案或云端访问状态。
