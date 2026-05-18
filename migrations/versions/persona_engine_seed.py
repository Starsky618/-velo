"""persona_engine_seed：168 条 NPC 文案入 persona_templates 表（task-2）。

把宪法 § 2 v0.2 cycle 完结的全部 168 条精金文案系统化入库。
未来 cycle 加新文案 = 单独迁移 / 不动本表已有行。

类比：把老登的"金句库"（宪法 docs/agent-rules/persona-constitution.md）抄进数据库。
每条三元组：(scene_type 大类 / segment 子段位 / template_text 文案字面)。

字面 ground truth：宪法 § 2 / 任何字面漂移由 pytest 字面比对拦截。

防火墙红线（handoff § 1）：
- 表名 persona_templates / 迁移名 persona_engine_seed.py（命名前缀守）
- 只写 persona_templates / 不动核心表

§2.6 过拟合裁定（2026-05-18 Tim 拍）：
- uploading 段不入库（用系统标准 toast）
- delete_confirm 段不入库（用标准客服文案）
- loading 仅入 v0.1 1 条（戏剧化候选已砍）

§2.7 跨时间镜像 LLM 场景不入库（留 v0.5+ LLM 实施时加 / 4 条是 prompt few-shot 样本不是真用文案）。

Revision ID: persona_engine_seed
Revises: sprint6_user_city_widen
Create Date: 2026-05-18
"""

from alembic import op
import sqlalchemy as sa


revision = "persona_engine_seed"
down_revision = "sprint6_user_city_widen"
branch_labels = None
depends_on = None


# ─── 168 条文案 / (scene_type, segment, template_text) ───
TEMPLATES = [
    # ─── § 2.1 上传 PR（16 条 / segment=NULL）───
    ("pr", None, "今天嗑药了？"),
    ("pr", None, "今天你最猛。"),
    ("pr", None, "数据有点过分。"),
    ("pr", None, "前 1% 的一天。"),
    ("pr", None, "把自己拉爆了。"),
    ("pr", None, "8500km 里这一天。"),
    ("pr", None, "心率写错了吧？"),
    ("pr", None, "功率表准吗？"),
    ("pr", None, "Strava 给你弹横幅了吗？"),
    ("pr", None, "明天还能上车吗。"),
    ("pr", None, "破风手得跟你抄作业。"),
    ("pr", None, "腿还能走路吗。"),
    ("pr", None, "这赛段是你的了。"),
    ("pr", None, "不用看排行了。"),
    ("pr", None, "上次这数据是去年。"),
    ("pr", None, "今年最快这一蹬。"),

    # ─── § 2.2 普通骑行 / 8 segment（43 条）───
    # 萌新 40km（7 条 / cycle 2 补 3 凑 ≥ 5 红线）
    ("segment_distance", "rookie_normal", "今天 40km。挺猛。"),
    ("segment_distance", "rookie_normal", "新人不该这么猛吧。"),
    ("segment_distance", "rookie_normal", "看不出来才骑两月。"),
    ("segment_distance", "rookie_normal", "萌新打老登卡。"),
    ("segment_distance", "rookie_normal", "够你说一周。"),
    ("segment_distance", "rookie_normal", "腿不酸算赢。"),
    ("segment_distance", "rookie_normal", "好歹是开完了。"),
    # 入门 40km（5 条 / cycle 2 补 1 凑 ≥ 5 红线）
    ("segment_distance", "entry_normal", "今天 40km。可以的吧。"),
    ("segment_distance", "entry_normal", "40 就 40。"),
    ("segment_distance", "entry_normal", "看来入门完毕。"),
    ("segment_distance", "entry_normal", "这周稳定了。"),
    ("segment_distance", "entry_normal", "都在状态里。"),
    # 进阶 40km（5 条 / cycle 2 补 1 凑 ≥ 5 红线）
    ("segment_distance", "mid_normal", "今天 40km。日常水平了。"),
    ("segment_distance", "mid_normal", "40km，按部就班。"),
    ("segment_distance", "mid_normal", "算是热身了。"),
    ("segment_distance", "mid_normal", "还能再加 20。"),
    ("segment_distance", "mid_normal", "才出门就到了。"),
    # 老登 40km（7 条）
    ("segment_distance", "veteran_normal", "40km。蹬两脚意思意思。"),
    ("segment_distance", "veteran_normal", "撒个尿就回了。"),
    ("segment_distance", "veteran_normal", "40 拉得有点划水。"),
    ("segment_distance", "veteran_normal", "还没出汗呢。"),
    ("segment_distance", "veteran_normal", "出去吹个风。"),
    ("segment_distance", "veteran_normal", "早饭都没消化完。"),
    ("segment_distance", "veteran_normal", "半壶水的事儿。"),
    # 萌新 30km（7 条 / short 桶）
    ("segment_distance", "rookie_short", "30km。开了个头。"),
    ("segment_distance", "rookie_short", "明天大概率酸。"),
    ("segment_distance", "rookie_short", "腿没废吧。"),
    ("segment_distance", "rookie_short", "腿明天会替你说话。"),
    ("segment_distance", "rookie_short", "够换一顿好吃的。"),
    ("segment_distance", "rookie_short", "跑出小区了。"),
    ("segment_distance", "rookie_short", "第一次出趟远门。"),
    # 入门 100km（5 条 / long 桶）
    ("segment_distance", "entry_long", "100km。稳得很。"),
    ("segment_distance", "entry_long", "三位数了。"),
    ("segment_distance", "entry_long", "腿不抖就好。"),
    ("segment_distance", "entry_long", "入门毕业证拿了。"),
    ("segment_distance", "entry_long", "比上次远 20 吧。"),
    # 进阶 150km（7 条 / long 桶）
    ("segment_distance", "mid_long", "150km。说明状态在。"),
    ("segment_distance", "mid_long", "糖原顶住没。"),
    ("segment_distance", "mid_long", "150 算认真的了。"),
    ("segment_distance", "mid_long", "再往上就拼了。"),
    ("segment_distance", "mid_long", "下车两条腿不一样长。"),
    ("segment_distance", "mid_long", "裤兜补给还剩吗。"),
    ("segment_distance", "mid_long", "回家先喝一升水。"),
    # 老登 200km（5 条 / extreme 桶）
    ("segment_distance", "veteran_extreme", "200km。膝盖呢。"),
    ("segment_distance", "veteran_extreme", "第二天能走吗。"),
    ("segment_distance", "veteran_extreme", "链条都酸了吧。"),
    ("segment_distance", "veteran_extreme", "路上撒了几次尿。"),
    ("segment_distance", "veteran_extreme", "腰还连着腿吗。"),

    # ─── § 2.3 连骑高频（6 条 / segment=NULL）───
    ("consecutive_high", None, "把膝盖磨成粉了？"),
    ("consecutive_high", None, "锁鞋焊脚上了？"),
    ("consecutive_high", None, "屁股还活着吗？"),
    ("consecutive_high", None, "车架冒烟没？"),
    ("consecutive_high", None, "本周第 5 次了。"),
    ("consecutive_high", None, "今天又上车。停不下来了。"),

    # ─── § 2.4 沉寂（6 条 / segment=NULL）───
    ("silence", None, "最近去哪儿了。"),
    ("silence", None, "充电桩等你好久了。"),
    ("silence", None, "上次骑车 12 天前。"),
    ("silence", None, "膝盖恢复完了？"),
    ("silence", None, "车蹭灰了吧。"),
    ("silence", None, "胎压还在吗。"),

    # ─── § 2.5 极端数据 / 8 segment（44 条）───
    # tiny < 5km（5 条）
    ("extreme", "tiny", "5 公里？撒尿都不够。"),
    ("extreme", "tiny", "等红绿灯都没等够。"),
    ("extreme", "tiny", "GPS 都没醒。"),
    ("extreme", "tiny", "腿都没暖开。"),
    ("extreme", "tiny", "停车场绕一圈。"),
    # high_speed（5 条）
    ("extreme", "high_speed", "这平均速度，摩托吧？"),
    ("extreme", "high_speed", "心率对得上吗？"),
    ("extreme", "high_speed", "顺风全程吗？"),
    ("extreme", "high_speed", "电摩才能这速度。"),
    ("extreme", "high_speed", "这功率是人类吗？"),
    # late_collapse（5 条）
    ("extreme", "late_collapse", "前快后慢，老剧本了。"),
    ("extreme", "late_collapse", "崩在半路啊。"),
    ("extreme", "late_collapse", "糖原烧完了吧。"),
    ("extreme", "late_collapse", "后程像换了人。"),
    ("extreme", "late_collapse", "节奏没绷住。"),
    # low_speed（6 条）
    ("extreme", "low_speed", "今天电助力坏了吗？"),
    ("extreme", "low_speed", "走路都比这快。"),
    ("extreme", "low_speed", "城里堵车水平。"),
    ("extreme", "low_speed", "是骑还是推。"),
    ("extreme", "low_speed", "车带着你走的吗。"),
    ("extreme", "low_speed", "今天就佛系。"),
    # night（6 条）
    ("extreme", "night", "又是夜骑党。"),
    ("extreme", "night", "凉风骑得舒服吧。"),
    ("extreme", "night", "晚饭都没吃吧。"),
    ("extreme", "night", "几点到家。"),
    ("extreme", "night", "灯没忘开吧。"),
    ("extreme", "night", "明天闹钟还响吗。"),
    # long_dist > 150km（5 条）
    ("extreme", "long_dist", "150km 了。洗澡去吧。"),
    ("extreme", "long_dist", "明天能坐稳吗。"),
    ("extreme", "long_dist", "屁股要换皮了。"),
    ("extreme", "long_dist", "把灯都骑到没电。"),
    ("extreme", "long_dist", "回家直接平躺。"),
    # rain（5 条）
    ("extreme", "rain", "雨里也出去？禧玛诺交响曲好听吗。"),
    ("extreme", "rain", "鞋洗了一遍。"),
    ("extreme", "rain", "今天免费洗车。"),
    ("extreme", "rain", "雨水比补水多。"),
    ("extreme", "rain", "刹车快换了吧。"),
    # early < 6:00（7 条）
    ("extreme", "early", "这点出门？老登。"),
    ("extreme", "early", "鸡都没叫。"),
    ("extreme", "early", "早饭店都没开。"),
    ("extreme", "early", "比上班还早。"),
    ("extreme", "early", "天还在赶路。"),
    ("extreme", "early", "第一个上车的。"),
    ("extreme", "early", "天亮前先出门。"),

    # ─── § 2.6 错误页 / 6 可 NPC segment（28 条）───
    # empty（7 条）
    ("empty_error", "empty", "还没数据。先去蹬两圈。"),
    ("empty_error", "empty", "蹬一脚再来看。"),
    ("empty_error", "empty", "先去刷一圈。"),
    ("empty_error", "empty", "上路才有数据。"),
    ("empty_error", "empty", "车在车库吧。"),
    ("empty_error", "empty", "轨迹还在路上。"),
    ("empty_error", "empty", "数据等你回家。"),
    # upload_failed（5 条）
    ("empty_error", "upload_failed", "今天轨迹丢了。下次记得开 GPS。"),
    ("empty_error", "upload_failed", "GPS 装睡了。"),
    ("empty_error", "upload_failed", "GPS 卡壳了。"),
    ("empty_error", "upload_failed", "数据掉路上了。"),
    ("empty_error", "upload_failed", "蹬完了没记录。"),
    # network_down（5 条）
    ("empty_error", "network_down", "连不上。WiFi 切流量试试。"),
    ("empty_error", "network_down", "信号在度假。"),
    ("empty_error", "network_down", "WiFi 在睡觉。"),
    ("empty_error", "network_down", "信号比骑友还少。"),
    ("empty_error", "network_down", "信号 5 分钟前还在。"),
    # server_5xx（5 条）
    ("empty_error", "server_5xx", "服务器在打盹儿。"),
    ("empty_error", "server_5xx", "后台喘口气。"),
    ("empty_error", "server_5xx", "后端罢工了。"),
    ("empty_error", "server_5xx", "服务器去骑车了。"),
    ("empty_error", "server_5xx", "服务器有点累。"),
    # loading（1 条 / 戏剧化候选已砍）
    ("empty_error", "loading", "算你的高光中…"),
    # unauth_401（5 条）
    ("empty_error", "unauth_401", "要重新登录一下了。"),
    ("empty_error", "unauth_401", "得再敲一次门。"),
    ("empty_error", "unauth_401", "门没认出你。"),
    ("empty_error", "unauth_401", "登录卡掉了。"),
    ("empty_error", "unauth_401", "刷一下重进。"),
    # uploading / delete_confirm 不入库（拍标准客服 / 见 §2.6 顶部裁定）

    # ─── § 2.8 错峰惊喜 / 4 segment（20 条）───
    # solar_term（5 条）
    ("surprise", "solar_term", "立秋了，凉快下来了。"),
    ("surprise", "solar_term", "霜降了。骑慢点。"),
    ("surprise", "solar_term", "夏至。白天最长。"),
    ("surprise", "solar_term", "立冬了。补水改保暖。"),
    ("surprise", "solar_term", "春分了。该重启了。"),
    # anniversary（5 条）
    ("surprise", "anniversary", "上车一周年。8500km。"),
    ("surprise", "anniversary", "365 天没断。"),
    ("surprise", "anniversary", "一年前你也在路上。"),
    ("surprise", "anniversary", "去年今天你哪儿？"),
    ("surprise", "anniversary", "去年的你没想到吧。"),
    # milestone（5 条）
    ("surprise", "milestone", "1 万了。老登正式入会。"),
    ("surprise", "milestone", "破万的人不多。"),
    ("surprise", "milestone", "10000 公里解锁。"),
    ("surprise", "milestone", "新里程碑亮了。"),
    ("surprise", "milestone", "下一站 5 万。"),
    # new_year（5 条）
    ("surprise", "new_year", "新年第一蹬。"),
    ("surprise", "new_year", "去年的腿带到今年。"),
    ("surprise", "new_year", "新年第一脚。"),
    ("surprise", "new_year", "第一天先蹬出去。"),
    ("surprise", "new_year", "跨年骑党到了。"),
]
# 总计 = 16 + 48 + 6 + 6 + 44 + 28 + 20 = 168 条


def upgrade() -> None:
    """batch insert 168 条 NPC 文案到 persona_templates。"""
    persona_templates = sa.table(
        "persona_templates",
        sa.column("scene_type", sa.String),
        sa.column("segment", sa.String),
        sa.column("template_text", sa.Text),
    )
    op.bulk_insert(
        persona_templates,
        [
            {
                "scene_type": scene_type,
                "segment": segment,
                "template_text": template_text,
            }
            for (scene_type, segment, template_text) in TEMPLATES
        ],
    )


def downgrade() -> None:
    """回滚：精确删除本 migration 插入的 168 条（按 template_text 匹配）。

    不用 `DELETE FROM persona_templates` 无界删——未来 cycle 2 / 运营人工加文案
    回滚本 migration 时会误删（Codex Important）。按文案字面精确匹配
    保证作用域只覆盖本 migration 插入的行。
    """
    # 按 template_text 精确匹配 / 字符级唯一（本 migration 文案无重复字面）
    texts = [t[2] for t in TEMPLATES]
    persona_templates = sa.table(
        "persona_templates",
        sa.column("template_text", sa.Text),
    )
    op.execute(
        persona_templates.delete().where(
            persona_templates.c.template_text.in_(texts)
        )
    )
