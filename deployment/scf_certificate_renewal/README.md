# VELO 免费证书维护函数

独立的 Python 3.10+ **事件函数**，入口 `handler.main_handler`。仅维护广州 `weiluai.top` 与 `www.weiluai.top`，与静态站函数分开；静态站仍无需执行角色。代码只准备本地部署包，不创建资源或策略。

## 行为与边界

- 每日检查当前两域名绑定的证书；最早到期时间剩余 **25 天**时开始维护。证书日期按官方定义的 GMT+8 解析。
- 先获取当前证书，再按 `SearchKey=weiluai.top` 分页查询并精确过滤主域名。优先部署已签发、生效、`Deployable` 明确为布尔 `true`、SAN 同时包含两个域名、到期时间更晚且仍有超过 25 天有效期的证书。只对有效期确实增加的域名写入。不可部署或缺少 `Deployable` 的更长证书不参与排序；若没有其他可用候选，则抛错并禁止重复申请。官方列表结构列出这个布尔字段，但未明确承诺历史记录一定提供，故不将缺失视为 `true`；临近到期的旧证书仅用于判断续签时间，不要求其仍可重新部署。
- 根域名已有待验证/待签发/处理中订单时不重复申请；等待超过 3 天或当前证书剩余不足 7 天则抛出告警错误，不在函数内轮询。失败、取消或吊销的本轮续签订单要求人工检查，避免每日消耗免费申请额度。旧的无关失败订单不阻塞后续周期。
- 申请固定使用 `ApplyCertificate(DvAuthMethod=DNS_AUTO, PackageType="83", ValidityPeriod="3", DomainName="weiluai.top")`。仅旧证书未过期且余期不超过 30 天时传 `OldCertificateId`；已过期时新申请，并在申请后抛错提醒已有服务风险。免费证书界面的赠送 www 不能代替签发后的 SAN 检查。
- 每次只读两个自定义域名。写入前重读校验；携带原 `Protocol/EndpointsConfig/WafConfig`，仅替换 `CertConfig.CertificateId`；写入后重读比较全部配置（包括 Tags）。不下载/输出私钥、不购买付费证书、不删除/吊销证书、不调用 DNSPod 或跨资源部署 API。`DNS_AUTO` 由 SSL 服务自行处理域名验证 DNS 记录，函数不直接操作 DNS；要求域名托管于同账号腾讯云 DNS。
- 两域名其中一个已更新，下一次只补未完成者。申请响应超时不立即重试；下一次从云端证书订单恢复。单次最多 16 次云 API、单请求超时 5 秒、单类列表最多 5 页，每页 100 条；超限、分页不一致、未知结构/状态、权限错误和网络失败均抛错，绝不伪报成功。

UpdateCustomDomain 文档将非域名字段标为可选，并给出省略路由的示例，但没有明确承诺每个省略字段的 PATCH 语义。本实现保留并重发官方列出的现有可写配置，随后验证；不声称该 API 支持条件写入。它没有 CAS/版本锁，因此证书维护执行时避免同时从控制台修改域名配置；新的未知配置字段会阻止更新，要求重新核对接口。

## 执行角色与调度

1. 审查 `cam-policy.json`，将 `${ACCOUNT_UIN}` 替换为部署账户的主账号 UIN。为专用运行角色创建这份策略，角色可信实体选择 `scf.qcloud.com`，不要给静态站函数附加角色。
2. 策略仅允许 4 个动作。`ssl:ApplyCertificate` 官方只支持操作级 `resource="*"`，**CAM 无法把这个动作限定到 weiluai.top**，域名限制由固定代码落实；此权限边界应在授权时明确说明。`DescribeCertificates` 只允许本账号证书元数据；SCF 读写只允许广州的两个域名。不附加 SSL 全权、DNSPod 写入、下载、删除或吊销策略。
3. 配置事件函数 **128 MB、120 秒超时**，使用专用执行角色注入 `TENCENTCLOUD_SECRETID/SECRETKEY/SESSIONTOKEN`，不得手工设置长期密钥。函数只访问固定 HTTPS 云 API，使用 TC3 签名，不跟随重定向，不打印凭据、API 请求/响应或原始异常。
4. 仅配置一个每日定时触发器，不创建 Function URL。并发上限设为 1、每实例并发为 1，关闭该函数的异步自动重试；避免部署者手工同时触发。ApplyCertificate 没有幂等 token，本地无持久锁，不能宣称在并发调用或证书列表尚未可见时严格 exactly-once；每日串行执行和订单复查负责正常重入。
5. 在云监控为该函数的错误/超时配置告警，确认接收人和真实通知投递，再启用定时器。`healthy/requested/pending/updated` 是返回状态；错误会抛出，不吞没。函数不会自行发送邮件/短信或创建收费通知服务。

上线验收必须另外验证：运行角色实际授权、DescribeCertificates 元数据、DNS_AUTO 能签发且 SAN 正确、两域名配置只有证书 ID 改变、线上 TLS 实际使用新证书，以及失败告警可达。首次每日运行距到期远时只会读 API；这不能证明 65 天后的申请/签发/部署链路已真实通过。

## 本地测试与构建

```sh
python3 -m unittest discover -s tests -p test_scf_certificate_renewal.py -v
python3 deployment/scf_certificate_renewal/build.py \
  --revision <REVIEWED_FULL_COMMIT_HASH> \
  --output /tmp/velo-scf-certificate-renewal.zip
```

构建只读完整 commit 的 handler Git blob，忽略脏工作树；ZIP 仅包含 `handler.py` 和版本/哈希清单，固定排序、时间戳和权限，使用 ZIP_STORED，旁附包 SHA-256。角色策略、测试、README、凭据和官网资产均不进入运行包。

## 一手来源（2026-10-12 核对）

- [ApplyCertificate](https://cloud.tencent.com/document/product/400/41678)、[DescribeCertificates 与分页/状态](https://cloud.tencent.com/document/api/400/41671)、[证书字段、SAN、GMT+8 与续签关系](https://cloud.tencent.com/document/api/400/41679)
- [GetCustomDomain](https://cloud.tencent.com/document/api/583/111924)、[UpdateCustomDomain](https://cloud.tencent.com/document/api/583/111922)、[CertConf/EndpointsConf/WafConf](https://cloud.tencent.com/document/api/583/17244)
- [SSL CAM 资源粒度](https://cloud.tencent.com/document/product/598/98168)、[SCF CAM 资源粒度](https://cloud.tencent.com/document/product/598/70005)、[执行角色临时凭据](https://intl.cloud.tencent.com/zh/document/product/583/38176)
- [TC3 官方规范及 Python 示例](https://cloud.tencent.com/document/api/213/30654)
