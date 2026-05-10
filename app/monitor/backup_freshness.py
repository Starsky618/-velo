"""
DB 备份新鲜度探针（Sprint 5 task-1 / 跟 processing_health / admin_h5_health 同 monitor 容器）。

干啥用：
- 检查 /backups 目录里最新 .sql.gz 备份文件的 mtime
- mtime > 30h → log warning（备份可能跳脚 / Tim 凌晨 cron 没跑 / 磁盘满 / db 连不上等）
- 无任何文件 → log error（备份从没成功跑过 / 部署后 Tim 忘手动 trigger）
- 健康（< 30h）→ 不打日志（避免日志噪音 / 跟 processing_health 风格一致）

操作注意：
- **只读不写**：探针只 stat 文件 / 不调 pg_dump / 不写任何文件
- **告警机制 = log-only**（D 决策 / Tim 2026-05-10 拍 / 跟 admin_h5_health 阶段决策一致）
- **30h 阈值的 6h buffer**：每天凌晨 cron 失败 1 次仍允许（24h+6h），失败 2 次才报 warning
- **首次部署后**：必须立即手动跑一次 backup 否则 30h 内会持续 warning
  → task 卡 §2 步骤 5 强制部署完手动 trigger 一次

数据流：
- 入：/backups 目录（容器内挂载点 / 只读 ro）
- 中：glob 'velo_*.sql.gz' → 取最新 mtime → 算距离 now 的小时数
- 出：log info/warning/error + 退码 0/1（cron 监控可用退码识别）

部署：docker-compose monitor 容器 command 加 `python -m app.monitor.backup_freshness || true`
"""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path


logger = logging.getLogger(__name__)


# 备份目录（容器内挂载点 / docker-compose 配 ./backups:/backups:ro）
BACKUP_DIR = Path("/backups")

# 备份新鲜度阈值：30 小时（24h cron + 6h buffer）
# 类比家里冰箱牛奶 —— 保质期 24h，超 6h 就别喝了
STALE_THRESHOLD_HOURS = 30


def check_backup_freshness(backup_dir: Path = BACKUP_DIR) -> int:
    """
    检查 backup_dir 里最新备份文件的 mtime / 报告状态。

    设计思路：
    - 不修不删 / 只读
    - 探针失败 ≠ 备份失败 —— 探针只是"通知"备份可能有问题，真原因要看 db-backup 容器日志
    - 类比家里烟雾报警器 —— 响了不一定真火，但总要去看看锅有没烧

    参数：
        backup_dir: 备份目录路径（默认 /backups / 测试可注入临时路径）

    返回：
        0 = 健康（最新备份 < 30h）
        1 = 不健康（无文件 / 最新备份 > 30h / 目录不存在）

    异常路径：
        - 目录不存在 → log error + 返 1
        - 目录为空 → log error + 返 1
        - 最新文件 mtime > 30h → log warning + 返 1
    """
    # 第 1 步：目录存在性检查
    # 防 docker volume 没挂 / 探针在错误环境跑
    if not backup_dir.exists():
        logger.error(f"backup dir 不存在: {backup_dir} / 检查 docker volume 挂载")
        return 1

    # 第 2 步：找所有备份文件
    # 用 'velo_*.sql.gz' glob 防误把其他文件算进来
    backup_files = list(backup_dir.glob("velo_*.sql.gz"))

    if not backup_files:
        logger.error(
            f"backup dir 为空: {backup_dir} / "
            "首次部署需手动跑一次 docker compose exec db-backup /scripts/backup_db.sh"
        )
        return 1

    # 第 3 步：找最新文件的 mtime
    # 用 mtime 不用文件名时间戳 —— mtime 更可靠（文件名是脚本生成时填的，可能跟实际写入时间略差）
    latest_file = max(backup_files, key=lambda p: p.stat().st_mtime)
    latest_mtime = datetime.fromtimestamp(latest_file.stat().st_mtime, tz=timezone.utc)

    # 第 4 步：算距今小时数
    now = datetime.now(timezone.utc)
    age_hours = (now - latest_mtime).total_seconds() / 3600

    # 第 5 步：按阈值分流
    if age_hours > STALE_THRESHOLD_HOURS:
        logger.warning(
            f"backup stale: 最新备份 {latest_file.name} 距今 {age_hours:.1f}h "
            f"(阈值 {STALE_THRESHOLD_HOURS}h) / 检查 db-backup 容器日志"
        )
        return 1

    # 第 6 步：健康路径不打日志（防噪音 / 跟 processing_health 一致）
    return 0


def main() -> int:
    """
    命令行入口（docker-compose monitor 容器主循环调用）。

    返回退码：0 = 健康 / 1 = 陈旧或无文件（外层 sh `|| true` 兜底不停容器）
    """
    return check_backup_freshness()


if __name__ == "__main__":
    import sys
    sys.exit(main())
