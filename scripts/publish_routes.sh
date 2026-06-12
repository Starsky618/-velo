#!/bin/bash
# 路线百科一键发布——Tim 自助通道（双击仓库根目录的「发布路线.command」即可，无需懂终端）。
#
# 干啥用：把 content/routes/ 里的修改（文字 guide.md / 简介 meta.json / 封面 cover.*）
# 发布到生产 App。改什么发什么，没改的原样不动。
#
# 安全性（回答"会不会弄坏什么"——不会）：
# - 只动 content/routes/ 一个目录的提交，代码一行不碰；
# - 灌库是按路线名"有则更新无则建"，不建表、不动数据库迁移、不重建容器；
# - 改坏了文字也只是文字坏了，再改一次再发布就行；
# - 中途断网/失败：直接重新双击跑一遍，每一步都可安全重复。
#
# 前置条件（Tim 平时不用管，给未来排查的人看）：服务器代码必须已部署到含
# gallery_urls 列的版本（git pull + docker rebuild + alembic upgrade head）。
# 没部署就发布，灌库会报 "column gallery_urls does not exist"——那是开发者欠部署，
# 不是内容坏了，喊 Claude 部署后重新双击即可。
#
# 图片规则：content/routes/<路线>/ 里 cover 开头的图片是封面，其余图片全是实景图
# （按文件名排序显示，想控制顺序就在文件名前加 01_/02_）。增删替换文件后双击发布即生效。
# 想撤掉封面：删掉 cover.* 并删掉 meta.json 里的 "cover_url" 那一行；
# 实景图删光 = 自动撤下长廊，不用动 meta.json。
# 扫图/命名/写指针的具体逻辑在 scripts/sync_route_images.py（带测试），本脚本只管传输。

set -euo pipefail
cd "$(dirname "$0")/.."

SERVER="ubuntu@114.132.190.245"
ROUTES_DIR="content/routes"
# ssh/scp 保活参数：60 秒无响应自动断开退出，防 NAT 静默断链让窗口永久挂死
# （2026-06-12 首次大批量传图实证：远端工作全部完成后本地 ssh 僵挂 13 分钟）
SSH_OPTS=(-o ServerAliveInterval=15 -o ServerAliveCountMax=4)

echo "════════ velo 路线发布 ════════"

# ── 1/5 同步图片指针 + 备料（本地图片文件是真相源：cover.* 封面 / 其余实景图）
#     sync_route_images.py 一口气做完：改 meta.json 指针 + 把图按服务器命名拷进打包间
staging="/tmp/velo_covers_local_$$"
mkdir -p "$staging"
trap 'rm -rf "$staging"' EXIT   # 中途任何一步失败都不留打包间垃圾，重跑彻底幂等
python3 scripts/sync_route_images.py --content-dir "$ROUTES_DIR" --staging-dir "$staging"

# ── 2/5 提交内容修改（只提交 content/routes/，跳过代码门禁——内容不是代码）
git add "$ROUTES_DIR"
if git diff --cached --quiet -- "$ROUTES_DIR"; then
  echo "── 2/5 内容无修改（跳过提交，继续同步服务器）"
else
  git pull --no-rebase --no-edit --quiet origin main
  git commit --no-verify --quiet -m "content(routes): 路线内容更新 $(date +%F·%H:%M)" -- "$ROUTES_DIR"
  git push --quiet origin main
  echo "── 2/5 内容已提交推送 ✓"
fi

# ── 3/5 打包上传图片（单次连接，防服务器 SSH 限流——首跑 12 连被掐实证）
#     打包间在 1/5 已由 sync_route_images.py 备好：封面平铺 + 实景图按路线子目录
echo "── 3/5 上传图片..."
if [ -n "$(ls -A "$staging" 2>/dev/null)" ]; then
  ssh "${SSH_OPTS[@]}" "$SERVER" 'rm -rf /tmp/velo_covers_in'
  scp "${SSH_OPTS[@]}" -q -r "$staging" "$SERVER:/tmp/velo_covers_in"
  echo "       图片已上传 ✓"
else
  echo "       无图片文件，跳过"
fi
rm -rf "$staging"

# ── 4-5/5 服务器侧一口气完成：拉内容 → 图进容器 → 灌库（单次 SSH 连接）
ssh "${SSH_OPTS[@]}" "$SERVER" '
  set -e
  cd ~/velo
  git pull --no-rebase --no-edit 2>&1 | tail -1
  if [ -d /tmp/velo_covers_in ]; then
    sudo docker compose exec -T api mkdir -p /app/uploads/route_covers
    # $f 可能是封面文件、也可能是路线子目录（实景图）。docker cp 目录时不加尾斜杠——
    # 不带斜杠 = 在目标下创建/合并同名子目录（正确）；带斜杠 = 只倒内容进目标根（错误）。
    # [ -e ] 守卫：目录意外为空时 glob 不展开会留下字面量 "*"，没守卫会让 set -e 整块中断
    for f in /tmp/velo_covers_in/*; do
      [ -e "$f" ] || continue
      sudo docker compose cp "$f" api:/app/uploads/route_covers/ > /dev/null
    done
    rm -rf /tmp/velo_covers_in
  fi
  sudo docker compose exec -T api python3 scripts/import_route_guides.py 2>&1 | tail -2
'
echo "── 4-5/5 服务器同步 + 数据库更新 ✓"

echo ""
echo "✅ 发布完成！小程序里下拉刷新路线页即可看到新内容。"
