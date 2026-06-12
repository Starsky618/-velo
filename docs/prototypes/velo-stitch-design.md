# VELO × Google Stitch 设计生成弹药包

> **怎么用（3 步，5 分钟）**：
> 1. 打开 [labs.google/stitch](https://labs.google/stitch)（Google 账号登录）→ 新建项目（选 Mobile）
> 2. 把下面「DESIGN.md」整段贴进第一条消息发送（它是全部屏幕的设计基因）
> 3. 再逐条贴「屏幕 Prompt」，每条出 1 屏；同一条可以让它 regenerate 出多版——**你的眼睛挑，挑中截图发我，我负责像素级还原成小程序**
>
> 这份弹药 = 四轮设计迭代里被你确认过的全部认知（水印形态 / 内容主导 / Volt 单点缀 / 宽体字）+ 全部翻车点的反向禁令。

---

## DESIGN.md（第一条消息整段贴入）

```
# Design System: VELO — Road Cycling Companion App (WeChat Mini Program, 390px mobile)

## Visual Theme & Atmosphere
A photography-led, content-first interface for serious road cyclists. Think premium
cycling apparel brand (Rapha-like): real outdoor photography carries all emotion;
the UI itself stays quiet, airy and precise. Generous whitespace, calm order,
confident but never decorated. Data appears as quiet, precise overlays or clean
rows — like a watermark stamped on a photo, never as boxed "widgets".
The product's soul: "being seen by your riding friends" — finish a ride, get your
result, share a photo with data printed on it.

## Color Palette & Roles
- Canvas (#F6F6F4) — app background, neutral warm-gray white (NOT cream/beige)
- Surface (#FFFFFF) — cards and sheets
- Carbon Ink (#1B1C20) — primary text and large numbers
- Steel (#66676F) — secondary text, labels, units
- Hairline (#E9E9EC) — 1px dividers and borders
- Electric Lime (#D6FF42) — THE ONLY accent. Used sparingly: small sticker-like
  tags with near-black text, route/track lines on maps and photos, active tab
  indicator, primary button (lime bg + near-black text) or inverted (near-black
  bg + lime text). Never as large background areas, never as glowing neon.
- Amber (#E08A00) — semantic only: fatigue/risk warnings
Strictly one accent across the whole app. No purple, no gradients as decoration.

## Typography Rules
- Clean wide neo-grotesque / humanist sans (SF Pro / Helvetica Now feel).
  Friendly and wide, NOT condensed, NOT squeezed racing type.
- All metric numbers use tabular (monospaced-figure) numerals, medium-to-semibold
  weight, large but calm. Number + small unit pattern: "78.05 km" with unit smaller
  and lighter.
- Chinese text: clean heavy sans for titles (PingFang SC Semibold feel), regular
  for body. Moderate size contrast — hierarchy from weight and spacing, not from
  screaming size jumps.

## Component Stylings
- Photo cards: full-bleed photo with route name + small data row BELOW the photo
  on white, separated by hairlines (magazine listing style) — not text boxed over
  the image.
- Data rows: label in small gray + tabular number in dark, arranged in clean
  horizontal rows with hairline separators. No card-in-card stacking.
- Buttons: solid near-black with lime text, or lime with near-black text. Slightly
  rounded (8-12px). One primary action per screen.
- Share/result imagery: data printed directly on user photos as white text with
  subtle shadow + a thin lime GPS track line — watermark philosophy, no frames,
  no certificate borders, no stamps.
- Collapsible sections: plain rows with hairline dividers and chevrons.

## Layout Principles
- Single column, 390px mobile, generous vertical whitespace between sections.
- Content-first: photos and numbers are the heroes; chrome recedes.
- Calm asymmetry allowed; alignment always intentional. Max 1 highlight moment
  per screen.

## Anti-Patterns (NEVER)
- No dark "nightclub" screens with glowing neon for daily UI
- No certificate frames, stamps, seals, badges, diagonal ribbon bands
- No condensed/racing display numerals
- No giant ghost background words (EXPLORE etc.)
- No boxed translucent data widgets floating over photos
- No purple gradients, no cream/beige "premium" backgrounds, no Inter-default look
- No emoji as icons; no decorative gradients; no three-equal-cards rows
- No fake placeholder vibes: use realistic Chinese cycling content
```

---

## 屏幕 Prompts（逐条贴，每条一屏；不满意就 regenerate / 微调措辞）

### ① 探索页（路线百科门面）
```
Explore screen for VELO. Header: "探索" title with subtitle "太原 · 11 条官方路线",
search bar. Tabs: 官方路线 / 附近约骑 / 排行. Magazine-style route list: each item
is a full-bleed outdoor cycling road photo (mountain switchback roads in Shanxi),
with a small lime "官方" tag on the photo corner; BELOW each photo on white:
route name "天龙山盘山公路" with english eyebrow "TIANLONGSHAN CLIMB", and a clean
data row "10.0 km · 爬升 561 m · 均坡 5.6%" in tabular numerals, hairline divider
between items. Second item: "横岭 HENGLING — 11.0 km · 爬升 633 m". Bottom tab bar:
首页 / 探索 / 约骑 / 我的 with lime indicator on 探索.
```

### ② 路线详情页
```
Route detail screen for VELO. Full-bleed hero photo of mountain switchback road,
back button. Below: route name "天龙山盘山公路" + eyebrow "TIANLONGSHAN CLIMB",
one-line description with a key phrase highlighted by a lime marker-pen underline:
"太原公路车圈最经典的爬坡试金石". Large calm data row: 10.0 km 距离 / 561 m 爬升 /
5.6% 均坡 in tabular numerals separated by hairlines. An elevation profile line
chart (thin dark line, small lime dot at summit) on white. Primary button:
near-black with lime text "约骑这条路线". Then collapsible plain rows with
chevrons: 这是一条什么路 / 给真要去的骑友 / 怎么骑 / 骑友怎么说 / 安全.
```

### ③ 开奖结果页（骑行结束的奖赏时刻）
```
Ride result screen for VELO ("开奖" = your ride results revealed). Light, airy,
celebratory but calm. Top: small eyebrow "RESULT · 6月12日 晚骑" and title
"成绩已开奖". A large hero number "42.6 km" in tabular numerals (calm, wide,
not condensed). Below: clean data rows with hairlines: 总时长 1:47:32 / NP 功率
187 W / 总爬升 561 m. Two small lime sticker tags: "20分钟功率 新纪录" and
"单次爬升 新纪录". A thin elevation profile line as a quiet footer graphic.
Primary button: "生成水印照片" near-black with lime text, subtext "选一张今天的照片，
把成绩印上去". No dark background, no neon glow, no confetti.
```

### ④ 水印照片编辑器（成绩卡的真实形态）
```
Photo watermark editor screen for VELO. A user's own cycling photo (road cyclist
POV selfie on a mountain road) fills most of the screen. Printed directly on the
photo, bottom-left: vertical stack of white text with subtle shadow — 距离 78.05 km /
爬升海拔 1,302 m / NP 功率 187 W / 时间 3:56:08 — labels small, numbers large in
clean wide tabular numerals; plus a thin electric-lime GPS route outline drawing
and a small "VELO" wordmark with a tiny lime square. No frame, no border, no boxed
overlay — pure watermark on photo. Bottom bar: 更换照片 / 布局 switch (纵排 / 一行) /
保存到相册 button in near-black with lime text.
```

### ⑤ 个人主页（训练数据 + 本周状态）
```
Profile/training screen for VELO. Header: rider name "Starsky", small line
"FTP 200 W · 太原". A calm weekly summary block: "本周" with big tabular numbers —
骑行 3 次 / 186 km / 爬升 2,140 m, hairline separated. A simple clean line chart of
training load (CTL/ATL) in dark line + lime accent dot. List rows with chevrons:
我的活动 / 我的路书 / 我的约骑 / 荣誉. Light, white, generous spacing.
```

---

## 挑图标准（给眼睛的 checklist，不确定时回来看）

1. 这张图如果去掉 VELO 字样，像不像一个国际一线运动品牌的 App？（像 → 过）
2. 照片/数据是主角，还是装饰是主角？（装饰抢戏 → 毙）
3. 荧光绿出现了几处？（>3 处 → 毙；它是点缀不是主题）
4. 你有没有想把它发给车队群的冲动？（成绩相关屏幕的唯一标准）

挑中的帧直接截图发我 → 我做像素级还原（rpx 换算 / 等宽数字 / 真数据接口对接全是我的活，这条链路约骑原型已验证过）。
