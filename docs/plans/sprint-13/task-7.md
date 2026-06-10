# Sprint 14 Task-7 — 路线百科灌库（route_guides 表 + 灌库脚本 + 13 条内容）

> 所属：Sprint 14 路线百科上架 / 第 1 个 task / S14 线的地基，可与 S13 线并行。
> 上游：`docs/spec-v6.md` §2.2 / §3.6 / D5、D6、D11 / 风险 5。
> 前置门：T1 的迁移已 commit（本 task 迁移 down_revision 链在其后）。
> **分工硬约束（spec 风险 5）**：表 + 脚本可派 Codex；**13 条内容转换必须主 agent 亲自做、走 route skill 全部铁律**（零幻觉 / 零侵权 / 来源标注），不许派 subagent。

---

## ─────── 给 Tim 看 ───────

### 干啥用

把桌面上 17 个路线 HTML（13 条路线的心血）搬进生产数据库，变成 App 里能点开的官方路线库。介绍文字住新表 `route_guides`（防火墙：慢变的内容资产不和轨迹数据焊在一起），有 GPX 的路线轨迹半进 `route_books` 并打上"官方"标记。

类比：route_books 是仓库里的施工图纸，route_guides 是装裱好的导览手册。手册可以先上墙（还没图纸的路线照样有介绍页），图纸到了再挂到手册旁边。

### 用户故事

新用户打开路线页，看到 13 条太原路线——天龙山西线点进去：介绍、亮点、海拔曲线、轨迹图全有。汾河二库暂时还没轨迹文件，但介绍和亮点照样能看（只是没有曲线、不能一键发起约骑），等补上 GPX 重跑一遍脚本就齐了。

### 怎么算做对了

- ✓ 13 条路线在生产库各有一条 guide（汾河那条等你拍定本，拍板前只灌 12 条）。
- ✓ 有 track.gpx 的路线：海拔曲线预计算好存库、轨迹建成官方 route_book。
- ✓ 脚本重跑不产生重复数据（按路线名幂等）；后补 GPX 重跑 = 升级不重建。
- ✓ 内容零幻觉零侵权（route skill 铁律：来源标注、版权红线、地理事实逐个验证）。

### 这次不做

- 不灌汾河（3 版定本待你拍板，推荐最新「环太原汾河自行车道」版——**未决决策不进实施**）。
- 不给 route_books 加 description 列（必答 #5 三件套对比后否决，内容进新表）。
- 不造 GPX 绘制工具（无轨迹路线用现成工具补，补好再重跑脚本）。
- 不做前端页面（T8）。

### 估时

2 天（表+脚本 1 天派 Codex / 内容转换 1 天主 agent 亲自）。

---

## ─────── 执行技术细节 ───────

<details>
<summary>展开</summary>

## 1. 起手必跑

```bash
nl -ba docs/spec-v6.md | sed -n '67,91p;180,182p'        # §2.2 模型 + §3.6 管线全文
sed -n '1,60p' app/route_book/models.py                   # 现有模型 + CHECK 约束（联合 CHECK 是关键）
rg -n "def " app/route_book/service.py | head -20         # 可复用的建 route_book 函数
rg -n "def parse" app/parsing/gpx_parser.py               # GPX 纯函数解析器签名
ls ~/Desktop/*.html | head -20                             # 17 个 HTML 原始内容（路径以 Tim 桌面实际为准）
ls scripts/                                                # 既有脚本风格参考（backfill_phase5.py 等）
```

已验证事实（2026-06-11 主 agent grep）：
- route_book/models.py：`func` 已导入（:14 from sqlalchemy.sql），**Boolean / false 均未导入**——models 顶部要补 [✓ Read]
- route_books 现有列含 `distance`（NOT NULL）/ `climb` / `reference_line`（LINESTRING NOT NULL）/ `file_id` / `file_type` / `source` / `city`，**无 description / is_official** [✓ Read models.py:24-35]
- 联合 CHECK `ck_route_books_file_type_source` [✓ Read models.py:48-55]：`source='file_upload'` 必须 `file_type IN ('gpx','fit') AND file_id IS NOT NULL AND source_activity_id IS NULL`——灌库走 file_upload 路径三者联动缺一不可，缺 file_id INSERT 直接被 DB 拒（spec 已实证）
- **route_books.city 有 CHECK**（'beijing'…'taiyuan','unknown' 英文枚举，[✓ Read models.py:44-47]）：脚本建 route_book 时 **city 必须传 `'taiyuan'`**，不能把 meta.json 里的中文"太原"直接塞进去（route_guides.city 是新表无 CHECK，存中文"太原"没问题——两张表两套值域，别串）
- 迁移链：本 task 迁移 down_revision = `"20260611_meetup_activities"`（T1 的 revision 串）

## 2. 文件改动清单

- Modify `app/route_book/models.py`：import 行补 `Boolean` + `false`；RouteBook 加 `is_official` 列；新增 RouteGuide 类；文件头 docstring 同步
- Create `migrations/versions/20260612_route_guides.py`（route_guides 表 + route_books.is_official 列，与 T1 迁移隔离回滚）
- Create `scripts/import_route_guides.py`
- Create `content/routes/<路线名>/`（guide.md + meta.json + 可选 track.gpx + 可选 cover）×12（汾河闸门）
- Create `tests/test_import_route_guides.py`
- **Do not** 改 route_book/service.py 现有函数签名 / **Do not** 动 segment / **Do not** 灌汾河

## 3. 完整代码（模型与迁移）

### 3.1 models.py（spec §2.2 原文 + import 修正）

```python
# import 行修正（实证现状：func 已导入，Boolean/false 均缺）：
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.sql import false, func


class RouteGuide(Base):
    """官方路线主实体（D11）——装裱好的导览手册，可以先于轨迹图纸存在。"""

    __tablename__ = "route_guides"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False, unique=True)     # 路线名，灌库幂等键
    city = Column(String(32), nullable=False, server_default="太原")
    route_book_id = Column(Integer, ForeignKey("route_books.id", ondelete="SET NULL"),
                           nullable=True, unique=True)          # 可空 = track_pending 态（D11）
    content_md = Column(Text, nullable=False)
    cover_url = Column(String(512), nullable=True)
    highlights = Column(Text, nullable=True)                    # JSON 数组文本
    elevation_profile = Column(Text, nullable=True)             # JSON [[累计km, 海拔m],...] ~100 点，
                                                                # 灌库时从 track.gpx 降采样预计算（D11）；
                                                                # 无轨迹时 NULL，前端 wx:if 整块隐藏（no-dash 判例）
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# RouteBook 追加一列（与 meetup 模块 Boolean 写法一致，D6）：
is_official = Column(Boolean, nullable=False, server_default=false())
```

注意：Text/text 大小写两个都要在 import 里（现有 `text` 用于 Index，新增 `Text` 用于列类型）——执行时核对现有 import 行实况后并入，别重复导入（陷阱：函数内重复 import 触发 UnboundLocalError 的同族错误）。

### 3.2 迁移 `20260612_route_guides.py`

```python
"""route_guides 表 + route_books.is_official（Sprint 14 T7）"""
from alembic import op
import sqlalchemy as sa

revision = "20260612_route_guides"
down_revision = "20260611_meetup_activities"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "route_guides",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("city", sa.String(32), server_default="太原", nullable=False),
        sa.Column("route_book_id", sa.Integer(), nullable=True),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column("cover_url", sa.String(512), nullable=True),
        sa.Column("highlights", sa.Text(), nullable=True),
        sa.Column("elevation_profile", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        # 显式命名（双审 I5）：ORM 列级 unique=True 按 spec 原文保留；迁移侧命名约束是为了
        # 未来 drop_constraint 不用 inspector 反查（陷阱 #6：PG 自动命名规则坑过 v4）
        sa.UniqueConstraint("name", name="uq_route_guides_name"),
        sa.UniqueConstraint("route_book_id", name="uq_route_guides_route_book_id"),
        sa.ForeignKeyConstraint(["route_book_id"], ["route_books.id"], ondelete="SET NULL"),
    )
    op.add_column("route_books", sa.Column("is_official", sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade():
    op.drop_column("route_books", "is_official")
    op.drop_table("route_guides")
```

## 4. 灌库脚本 `scripts/import_route_guides.py`（行为契约）

输入目录约定：`content/routes/<路线名>/`
- `guide.md`（必有，缺失**立即报错退出**，不进 DB 层撞 IntegrityError——spec 前置校验）
- `meta.json`：必填 `name`；可选 `city`（默认"太原"）/ `highlights`（数组）/ `cover_url`
- `track.gpx`（可选）
- 缺 cover_url → 存 NULL，前端空态占位图（T8 负责渲染）

核心流程（spec §3.6 + 三轮 B-I3 选项二）：

```
for 每个路线目录:
  前置校验 guide.md / meta.json
  guide = db.query(RouteGuide).filter_by(name=meta.name).first()   # name 是幂等键
  if 有 track.gpx:
      points = 复用 parsing/gpx_parser 纯函数解析（执行时 re-grep 签名）
      if guide 已存在且 guide.route_book_id 非空:
          # 幂等重跑已有轨迹：更新旧 book 的 reference_line/distance/climb，不新建（防孤儿 book）
          更新 book 行
      else:
          建 route_book(is_official=True, source='file_upload', file_type='gpx',
                        file_id=<GPX 存储路径>, city='taiyuan',        # CHECK 值域，英文！
                        distance/climb 从轨迹算, reference_line=LINESTRING)
      elevation_profile = 降采样(points, 目标 ~100 点)   # [[累计km, 海拔m], ...]
  upsert guide(name/city/content_md/highlights/cover_url/route_book_id/elevation_profile)
  db.commit()  # 逐条提交，崩在中途已入库的保留，重跑幂等续灌
```

硬要求：
- **standalone 脚本 ORM 加载陷阱**（判例 standalone_script_orm_loading）：脚本顶部显式 import 所有外键关联 ORM——`User` / `Activity` / `RouteBook` / `RouteGuide` / （meetup 若被 metadata 链到也要带上），`# noqa: F401`；否则真跑必炸 "could not find table"
- 降采样：按累计距离等距取点，首尾点必保留；经纬度距离用 `app/parsing/geo_math.py` 的 haversine（纯函数模块 [✓ grep]——**app/common/geo.py 里没有 haversine**，那里只有 infer_city_from_coords，双审实证别走错门）
- meta.json 前置校验追加：`highlights` 存在时必须能 `json.loads` 成数组，否则报错退出（双审 hot spot：单引号假 JSON 入库后 T8 接口 loads 必炸）
- `--dry-run` 先行（打印将建/将更新清单不落库），真跑前 dry-run 输出贴交付报告（判例：backfill 真跑前 dry-run + apply 1 条是唯一 gate）
- 运行方式：生产 api 容器内 `sudo docker compose exec api python3 scripts/import_route_guides.py --dry-run`（与 backfill_phase5 同通道）

## 5. 内容转换（主 agent 亲自，route skill 铁律）

- 源：桌面 17 个 HTML = 13 条路线；多版路线选定本后**一线一份 guide.md**——天龙山定本 v11（Tim 已拍）；**汾河 3 版定本待拍，拍板前不灌**
- 走 route skill 全部铁律：文案禁忌（禁"不是X是Y"句式 / 禁文艺比喻）、版权红线（图只能无人风景 / velo 自绘 / 授权 UGC）、地理事实逐个验证过的才保留、来源标注
- highlights 从卡片亮点区提取为 JSON 数组；cover_url 用已确权的图，没有就 NULL
- 转换是"机械搬运已审内容"不是再创作——HTML 里 Tim 审过的文案一字不改，只换格式

## 6. 测试用例

| # | 用例 | 断言 |
|---|---|---|
| 1 | 幂等重跑 | 连跑两遍，guides/books 行数不变，updated_at 变 |
| 2 | track_pending 升级 | 先无 GPX 灌（route_book_id NULL）→ 补 GPX 重跑 → 同一 guide 挂上新 book，不新建 guide |
| 3 | 已有轨迹重跑 | 更新旧 book 字段，不产生孤儿 book |
| 4 | guide.md 缺失 | 立即报错退出，DB 零写入 |
| 5 | 降采样 | 输出 ≤100 点、首尾保留、累计 km 单调递增 |
| 6 | CHECK 满足 | 建出的 book：source=file_upload + file_type=gpx + file_id 非空 + city='taiyuan' |

（PostGIS 函数 SQLite 跑不了的部分按陷阱 #15 dialect 守卫/真 PG 验证，测试里注明。）

## 7. 自检（commit 前）

- [ ] `rg -n "noqa: F401" scripts/import_route_guides.py` → ORM 预加载 import 齐
- [ ] `rg -n "'太原'|\"太原\"" scripts/` → 只出现在 route_guides 侧，route_books 侧全是 'taiyuan'
- [ ] dry-run 输出 12 条（无汾河）
- [ ] 自检三问：做了卡外的事吗 / 验收命令都真跑了吗 / 与 spec §3.6 逐条对照过吗

## 8. commit 指令

```
feat(route_book): S14-T7 路线百科灌库（route_guides 表 + is_official + 灌库脚本）
docs(content): S14-T7 12 条路线 guide.md 定本入库源（汾河待定本）
```

</details>
