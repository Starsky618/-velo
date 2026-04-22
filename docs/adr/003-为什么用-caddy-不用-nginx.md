# ADR-003: 为什么用 Caddy 不用 nginx

## 状态
accepted (2026-04-22)

## 上下文

velo 作为微信小程序后端,**微信强制要求所有 API 走 HTTPS**(小程序不允许调 HTTP)。因此反向代理必须提供:
- HTTPS 终结
- 证书自动申请与续期(Let's Encrypt)
- 将 `api.velo.xxx` 请求路由到内部 `api:8000` 容器

v0 期(2026-03 初)部署方案选型,候选有三:
- **nginx + certbot**: 行业最主流,性能最强,但证书续期要手动配 cron
- **Caddy 2**: 现代化,证书自动化内置
- **traefik**: Docker 生态原生,但学习曲线比 Caddy 陡

## 决策

velo 使用 **Caddy 2-alpine** 作为反向代理。

- 容器: `caddy:2-alpine`(轻量版)
- 配置文件: `Caddyfile`(生产)+ `Caddyfile.dev`(本地)
- 端口: 80 + 443 对外
- 证书: 自动 Let's Encrypt,Caddy 内置处理申请 + 续期

## 理由

1. **微信强制 HTTPS,证书自动化是刚需**。Let's Encrypt 证书 90 天过期,必须续期。nginx + certbot 需要额外 cron + 配置,出错不易察觉(证书过期 = 全站挂)。Caddy 内置证书生命周期管理,零配置。

2. **Caddyfile 配置文件比 nginx 短 5-10 倍**。典型 Caddy 反代配置:
   ```
   api.velo.xxx {
       reverse_proxy api:8000
   }
   ```
   同样功能的 nginx 配置需要 30+ 行(listen / server_name / ssl_certificate / ssl_protocols / proxy_set_header × N 等)。配置简洁意味着出错少、review 快。

3. **学生团队运维时间预算有限**。v0 部署时没有专职 DevOps,配 nginx 需要研究 ssl_ciphers / HSTS / gzip / http2 等细节。Caddy 默认配置已经做了这些现代 HTTPS 最佳实践(HSTS 自动开 / TLS 1.2+ 自动 / HTTP/2 自动 / 自动压缩)。

4. **性能足够**。Caddy 性能比 nginx 低 10-20%(Go vs C 的差距),但 velo 预期流量 QPS < 100,两者差距无感。

5. **出问题时日志更可读**。Caddy 的日志默认结构化 JSON + 彩色输出,nginx 默认 combined 格式需要额外解析。调试速度提升。

## 后果

### 正面
- 首次部署到生产 30 分钟搞定 HTTPS
- 证书续期 4 年来零人工干预(理论上,实际上 velo 2026 年才上线,但生态验证)
- Caddyfile 合并在 git,一目了然

### 负面
- 极端高并发场景性能不如 nginx(velo 不在此场景)
- 生态工具比 nginx 少(如没有 nginx-plus 级别的商业 WAF/LB)
- 如果未来需要 L7 特殊路由(ModSecurity WAF / 复杂 rate limit / upstream load balancing 策略等),Caddy 插件生态不如 nginx 丰富

### 触发重新评估的条件
- 日请求量 > 1000 万(Caddy 性能可能瓶颈)
- 需要商业级 WAF / DDoS 防护
- 需要多 upstream 复杂 LB 策略

## 违反代价

如果未来 PR 替换为 nginx,会触发:

1. **证书管理回退**: 需要重新配置 certbot + cron,并且面临续期失败导致全站挂的风险
2. **配置复杂度上升**: 团队要学习 nginx 完整配置语法,review 成本增加
3. **部署流程重做**: docker-compose.yml / Caddyfile / CI/CD 脚本都要改
4. **收益不明显**: velo 的流量规模根本触及不到 nginx 优势

**防御措施**: docker-compose.yml 中 caddy 服务配置稳定,不轻易改。新增域名只改 Caddyfile 一行。

## 相关文档

- 架构 guide v2 §3.1 caddy 容器 / §3.2 caddy 职责细则
- Caddyfile(仓库根目录)
- 附录: 部署经验:证书自动续期避免了生产事故
- ADR-006(为什么小程序优先)— 小程序 HTTPS 强制要求是本 ADR 核心驱动
