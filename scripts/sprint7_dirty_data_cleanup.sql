-- ============================================================
-- Sprint 7 脏数据清理 SQL（部署后跑一次 / 不可逆 / 必须 Tim 拍）
--
-- 背景：
-- v5+ Fix 3 / 5 / 6 / 7 上线前 / DB 里有以下脏数据：
-- 1. 跑步活动被误标 activity_type='cycling'（tier1 不过滤 type / Bug B 根因）
-- 2. 半成品 status='importing' 卡着 / 永远不会完成的 Strava 骨架
-- 3. Strava 骨架 simplified_track IS NULL（拉了 list 没拉 detail / 列表里"空"骑行）
--
-- Fix 5/7 数据层 13 处过滤已挡住这些脏数据不显示给用户。
-- 但 DB 里仍占空间 + 让 admin H5 / SQL 直查 / 未来 segment_efforts join 困惑。
-- 一次性清干净。
--
-- 用户故事：Tim 打开 velo 列表 → 历史正常骑行还在 / 5-14 Morning Run 消失 /
-- 半成品 importing 消失 / 总里程减去 0.96km（Morning Run 的距离）。
--
-- ============================================================
-- 执行顺序（部署后 / 在生产服务器跑）：
--   1. 跑 -- PHASE 1（4 个 SELECT）确认目标行
--   2. Tim 肉眼检查行数 + 抽样行内容 / 拍同意
--   3. 跑 -- PHASE 2（BEGIN..COMMIT 事务包）/ 出错可 ROLLBACK
--   4. 跑 -- PHASE 3（Redis 缓存清 / shell 命令 / 不在 SQL 文件）
-- ============================================================


-- ============================================================
-- PHASE 1：SELECT 验证目标行（dry-run / 只读 / 安全）
-- ============================================================

-- 1.1 列出所有目标行（应被删的活动）
-- 期望：至少包含 Morning Run id=421（5-14 跑步）/ 半成品 importing 骑行
SELECT
    id,
    user_id,
    strava_activity_id,
    title,
    activity_type,
    status,
    distance,
    simplified_track IS NOT NULL AS has_track,
    started_at
FROM activities
WHERE data_source = 'strava'
  AND (
      -- 三类脏数据合并条件：
      activity_type != 'cycling'                                     -- 跑步 / 徒步 / other
      OR (simplified_track IS NULL AND status = 'completed')         -- 空骨架（list 拉了 detail 没拉 / 已 complete）
      OR (status = 'importing' AND created_at < NOW() - INTERVAL '24 hours')  -- 半成品卡 >24h 才算脏（防误删 scheduler 实时 tier1 骨架）
  )
ORDER BY started_at DESC NULLS LAST;


-- 1.2 检查是否被 duplicate_of 引用（FK SET NULL 风险防御）
-- 期望：空。如非空 → 停止删除！主活动被引用不能盲删 / 人工处理
SELECT
    a.id AS dup_id,
    a.duplicate_of AS pointing_to,
    target.title AS target_title,
    target.activity_type AS target_type
FROM activities a
JOIN activities target ON target.id = a.duplicate_of
WHERE a.duplicate_of IN (
    SELECT id FROM activities
    WHERE data_source = 'strava'
      AND (
          activity_type != 'cycling'
          OR (simplified_track IS NULL AND status = 'completed')
          OR (status = 'importing' AND created_at < NOW() - INTERVAL '24 hours')
      )
);


-- 1.3 检查关联的 notifications 数量（确认 SET NULL 影响范围）
-- notifications.activity_id 是 SET NULL（不是 CASCADE）/ 必须 PHASE 2 先 DELETE
SELECT COUNT(*) AS notifications_to_delete
FROM notifications
WHERE activity_id IN (
    SELECT id FROM activities
    WHERE data_source = 'strava'
      AND (
          activity_type != 'cycling'
          OR (simplified_track IS NULL AND status = 'completed')
          OR (status = 'importing' AND created_at < NOW() - INTERVAL '24 hours')
      )
);


-- 1.4 检查关联的 segment_efforts 数量（CASCADE 会自动清 / 只看影响范围）
SELECT COUNT(*) AS efforts_to_cascade
FROM segment_efforts
WHERE activity_id IN (
    SELECT id FROM activities
    WHERE data_source = 'strava'
      AND (
          activity_type != 'cycling'
          OR (simplified_track IS NULL AND status = 'completed')
          OR (status = 'importing' AND created_at < NOW() - INTERVAL '24 hours')
      )
);


-- 1.5 NOTE 2026-05-21：原 persona_outputs 影响范围检查已移除
-- Persona 模块整模块砍（stage 2 代码层 / stage 3 reverse migration 才真 drop 3 张表）。
-- 若在 stage 3 完成前真跑此脚本：persona_outputs 表仍存在 / FK 仍是 SET NULL / 影响行为未变 / 但代码已不查。


-- ============================================================
-- PHASE 2：DELETE 事务包（出错 ROLLBACK / 成功 COMMIT）
-- ============================================================
-- ⚠️ 跑前必须：
--   1. PHASE 1 跑过 / Tim 看过 1.1 + 1.5 行数确认
--   2. duplicate_of 引用 SELECT 1.2 返空（如非空停止 / 人工处理被引用主活动）
--   3. 确认服务器最近 DB 备份 < 24h（ls ~/velo/backups/ / 或手动触发 backup_db.sh）
--   4. 建议先暂停 scheduler 容器（docker compose stop scheduler）防 tier1 并发：
--      跑完 PHASE 2 + COMMIT 后再 docker compose start scheduler
-- ⚠️ 出错立刻 ROLLBACK 不要 COMMIT
-- ⚠️ 必须 psql 交互模式逐段粘贴（不能 psql -f / -f 会自动 ROLLBACK 让你以为生效）
-- ============================================================

BEGIN;

-- 2.1 先 DELETE notifications（activity_id 是 SET NULL 不是 CASCADE / 必须显式删）
-- 不删 = 留 activity_id=NULL 的孤儿通知 / 用户看到无效通知
DELETE FROM notifications
WHERE activity_id IN (
    SELECT id FROM activities
    WHERE data_source = 'strava'
      AND (
          activity_type != 'cycling'
          OR (simplified_track IS NULL AND status = 'completed')
          OR (status = 'importing' AND created_at < NOW() - INTERVAL '24 hours')
      )
);

-- 2.2 DELETE activities（CASCADE 自动清 trackpoints / segment_efforts / activity_privacy）
DELETE FROM activities
WHERE data_source = 'strava'
  AND (
      activity_type != 'cycling'
      OR simplified_track IS NULL
      OR status = 'importing'
  );

-- 2.3 验证删除后 PHASE 1 SELECT 应返空
-- 在 COMMIT 前手动 SELECT 确认（在同事务内 / ROLLBACK 还能撤）
-- SELECT COUNT(*) FROM activities WHERE data_source = 'strava'
--   AND (activity_type != 'cycling' OR simplified_track IS NULL OR status = 'importing');
-- 上面 SELECT 应返 0 / 不返 0 → ROLLBACK 不要 COMMIT

-- COMMIT 或 ROLLBACK 由人工决定（看 PHASE 1 + 上面验证 SELECT 结果）：
-- COMMIT;
-- ROLLBACK;


-- ============================================================
-- PHASE 3：Redis 缓存清（部署后跑 / shell 命令 / 不在本 SQL 文件）
-- ============================================================
-- 在服务器 shell（不是 psql）跑：
--
--   redis-cli KEYS "heatmap:user_*" | xargs redis-cli DEL
--   redis-cli KEYS "power_curve:user_*" | xargs redis-cli DEL
--
-- 不清 = 1h TTL 内用户看到旧热力图（含跑步轨迹）/ 等自然过期也行 / 主动清更稳
-- ============================================================
