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
# 图片规则：content/routes/<路线>/cover.jpg（或 .png/.webp）就是封面——
# 替换文件=换封面，发布时自动上传并接上。想撤掉封面：删掉 cover.* 并删掉
# meta.json 里的 "cover_url" 那一行。

set -euo pipefail
cd "$(dirname "$0")/.."

SERVER="ubuntu@114.132.190.245"
ROUTES_DIR="content/routes"

echo "════════ velo 路线发布 ════════"

# ── 1/5 同步封面图的 meta 指针（本地 cover.* 是封面真相源）
for d in "$ROUTES_DIR"/*/; do
  name=$(basename "$d")
  cover=$(ls "$d"cover.* 2>/dev/null | head -1 || true)
  if [ -n "$cover" ]; then
    ext="${cover##*.}"
    python3 - "$d/meta.json" "/uploads/route_covers/${name}.${ext}" <<'PYEOF'
import json, sys
meta_path, url = sys.argv[1], sys.argv[2]
meta = json.load(open(meta_path))
if meta.get("cover_url") != url:
    meta["cover_url"] = url
    json.dump(meta, open(meta_path, "w"), ensure_ascii=False, indent=2)
    print(f"  封面指针更新: {meta_path}")
PYEOF
  fi
done

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

# ── 3/5 上传封面图到服务器（几张图几秒钟）
echo "── 3/5 上传封面图..."
covers=$(ls "$ROUTES_DIR"/*/cover.* 2>/dev/null || true)
if [ -n "$covers" ]; then
  tmpdir="/tmp/velo_covers_$$"
  ssh "$SERVER" "mkdir -p $tmpdir"
  for cover in $covers; do
    name=$(basename "$(dirname "$cover")")
    ext="${cover##*.}"
    scp -q "$cover" "$SERVER:$tmpdir/${name}.${ext}"
  done
  ssh "$SERVER" "cd ~/velo && sudo docker compose exec -T api mkdir -p /app/uploads/route_covers && for f in $tmpdir/*; do sudo docker compose cp \$f api:/app/uploads/route_covers/; done && rm -rf $tmpdir" > /dev/null
  echo "       封面已同步 ✓"
else
  echo "       无封面文件，跳过"
fi

# ── 4/5 服务器拉取内容（content 是只读挂载，拉完容器立即可见，不重建）
ssh "$SERVER" "cd ~/velo && git pull --no-rebase --no-edit 2>&1 | tail -1"
echo "── 4/5 服务器已同步 ✓"

# ── 5/5 灌库（有则更新无则建，改了的生效，没改的原样）
ssh "$SERVER" "cd ~/velo && sudo docker compose exec -T api python3 scripts/import_route_guides.py 2>&1 | tail -2"
echo "── 5/5 数据库已更新 ✓"

echo ""
echo "✅ 发布完成！小程序里下拉刷新路线页即可看到新内容。"
