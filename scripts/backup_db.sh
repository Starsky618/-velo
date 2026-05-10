#!/bin/sh
# velo 生产数据库自动备份脚本（Sprint 5 task-1）
#
# 干啥用：
# - 在 db-backup 容器（postgres:16-alpine 镜像）内每天凌晨跑一次
# - pg_dump velo 库 → gzip 压缩 → 写到 /backups/velo_YYYYMMDD_HHMMSS.sql.gz
# - 删 7 天前的 .sql.gz 文件（滚动保留）
#
# 操作注意：
# - 用 PGPASSWORD env 自动认证 / 不写密码到命令行（避免 ps -ef 泄露）
# - pg_dump 失败 → echo error + exit 1（让 sh 主循环看到失败但不停 / 下次 86400s 后重试）
# - find -mtime +7：删 mtime 超 7 天的文件 / 不删今天的（即使 7 天前那条今天又被某种原因覆盖也安全）
# - 不依赖 docker exec：本容器直连 db 服务（同 docker network / hostname=db）
#
# 数据流：
# - 入：环境变量 PGPASSWORD（docker-compose 注入 / 来自 .env DB_PASSWORD）
# - 中：pg_dump -h db -U velo -d velo | gzip > /backups/velo_*.sql.gz
# - 出：/backups 卷文件（host 路径 ~/velo/backups/）+ stdout 日志
#
# 部署：docker-compose db-backup 服务 sh -c "while true; do /scripts/backup_db.sh || true; sleep 86400; done"

set -e  # 任何命令失败立即退出（让外层 sh 循环看到非 0）

BACKUP_DIR="/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/velo_${TIMESTAMP}.sql.gz"
RETENTION_DAYS=7

# 第 1 步：sanity check / 备份目录必须存在（docker volume 挂载点）
if [ ! -d "${BACKUP_DIR}" ]; then
    echo "[$(date -Iseconds)] ERROR: backup dir ${BACKUP_DIR} not found / docker volume 挂载漏配" >&2
    exit 1
fi

# 第 2 步：sanity check / PGPASSWORD 必须有值
if [ -z "${PGPASSWORD}" ]; then
    echo "[$(date -Iseconds)] ERROR: PGPASSWORD env 未设置 / 检查 docker-compose environment" >&2
    exit 1
fi

# 第 2.5 步：等 PG ready（codex 异源审 2026-05-10 抓 Important）
# depends_on 只保证 db 容器先 start，不等 PG 进程真 ready
# 没这个等待 → 容器启动时第一次跑 backup 可能撞 db 启动窗口失败 → sleep 86400 → 这天丢备份
WAIT=0
# MAX_WAIT 是 WAIT 累加上限（每轮 sleep 5 + pg_isready -t 5 自身超时 5s = 实际最坏 ~2 分钟到 exit）
# 简化模型：60s 预算 / 真实最坏 ~115s / 都比 db 启动正常 5-10s 远大 → MVP 够（codex 异源审 round-2 Nice）
MAX_WAIT=60
until pg_isready -h db -U velo -d velo -t 5 > /dev/null 2>&1; do
    WAIT=$((WAIT + 5))
    if [ "${WAIT}" -ge "${MAX_WAIT}" ]; then
        echo "[$(date -Iseconds)] ERROR: PG 等待 ${MAX_WAIT}s 仍未 ready / 检查 db 容器" >&2
        exit 1
    fi
    echo "[$(date -Iseconds)] INFO: 等 PG ready... (${WAIT}/${MAX_WAIT}s)"
    sleep 5
done

# 第 3 步：跑 pg_dump → gzip（拆两步避免 pipe 退码陷阱）
# 设计原因：sh 默认 `pg_dump | gzip` 只看 gzip 退码 / pg_dump 失败时 gzip 仍可能写空文件成功退 0
#         → if then 分支被错走 / partial 文件留下 / freshness 探针被骗"有备份"
# alpine sh 不支持 set -o pipefail，所以拆：先 pg_dump 到 .sql 文件（独立退码可判）→ 成功才 gzip
PLAIN_FILE="${BACKUP_DIR}/velo_${TIMESTAMP}.sql"  # 中间裸 SQL 文件 / gzip 后变 .sql.gz 即 BACKUP_FILE
echo "[$(date -Iseconds)] INFO: backup start → ${BACKUP_FILE}"

if ! pg_dump -h db -U velo -d velo --no-owner --no-acl > "${PLAIN_FILE}"; then
    echo "[$(date -Iseconds)] ERROR: pg_dump 失败 / 删除 partial 文件 ${PLAIN_FILE}" >&2
    rm -f "${PLAIN_FILE}"  # 清理失败的半文件 / 防 freshness 探针误判
    exit 1
fi

if ! gzip "${PLAIN_FILE}"; then
    echo "[$(date -Iseconds)] ERROR: gzip 失败 / 清理 ${PLAIN_FILE} + ${BACKUP_FILE}" >&2
    rm -f "${PLAIN_FILE}" "${BACKUP_FILE}"  # gzip 失败可能两个都在或都不在，全 rm -f 兜底
    exit 1
fi

# gzip 默认行为：gzip foo.sql → 生成 foo.sql.gz 并删除 foo.sql
# 所以 PLAIN_FILE 已自动消失 / BACKUP_FILE（=PLAIN_FILE.gz）已就位
SIZE=$(ls -lh "${BACKUP_FILE}" | awk '{print $5}')
echo "[$(date -Iseconds)] INFO: backup ok / size=${SIZE}"

# 第 4 步：删 7 天前的备份文件
# -mtime +7：找修改时间超过 7 天的文件
# 用 -name 过滤防误删人工放的其他文件
DELETED=$(find "${BACKUP_DIR}" -name 'velo_*.sql.gz' -mtime +${RETENTION_DAYS} -print -delete | wc -l)
if [ "${DELETED}" -gt 0 ]; then
    echo "[$(date -Iseconds)] INFO: 滚动清理 / 删除 ${DELETED} 个 ${RETENTION_DAYS} 天前的备份文件"
fi

# 第 5 步：报告当前备份目录状态
TOTAL=$(find "${BACKUP_DIR}" -name 'velo_*.sql.gz' | wc -l)
echo "[$(date -Iseconds)] INFO: backup done / 当前共 ${TOTAL} 个备份文件"
