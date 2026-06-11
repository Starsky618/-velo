#!/bin/bash
# 路线百科一键发布——改完内容跑这一条命令，全链自动走完。
#
# 干啥用：把 route skill 工作区（route.json，内容真相源）的修改发布到生产 App。
# 链路：投影器(route.json→guide.md) → git 提交推送 → 服务器拉取 → 容器内灌库(幂等 upsert)。
#
# 操作注意事项（回答"会不会破坏容器/迁移"——不会，原理如下）：
# - 内容走数据通道：content/ 以只读卷挂进 api 容器，git pull 即可见，零 rebuild 零停机；
# - 灌库脚本是按路线名幂等 upsert：改介绍=UPDATE 该行，不建表、不动迁移、不碰其他数据；
# - 改坏了也只坏内容本身：回滚 = git revert 内容 commit 再跑一次本脚本。
#
# 用法：
#   ./scripts/publish_routes.sh            # 发布全部路线
#   ./scripts/publish_routes.sh hengling   # 只重新投影某条（灌库仍全量幂等扫，安全）
#
# 天龙山例外：定本是手工转写（不在工作区），直接改 content/routes/tianlongshan/guide.md 后跑本脚本。

set -euo pipefail
cd "$(dirname "$0")/.."

SERVER="ubuntu@114.132.190.245"

echo "═══ 1/4 投影：route.json → guide.md + meta.json"
python3 scripts/render_route_guides_md.py "${1:-}"

echo "═══ 2/4 提交推送内容变更"
git add content/routes/
if git diff --cached --quiet; then
  echo "内容无变化，跳过提交（继续走服务器灌库，幂等无害）"
else
  git commit -m "content(routes): 路线介绍更新 $(date +%F)"
  git push origin main
fi

echo "═══ 3/4 服务器拉取（content 是只读挂载卷，拉完容器立即可见，不 rebuild）"
ssh "$SERVER" "cd ~/velo && git pull --no-rebase --no-edit 2>&1 | tail -1"

echo "═══ 4/4 灌库（幂等 upsert：改了的更新，没改的原样）"
ssh "$SERVER" "cd ~/velo && sudo docker compose exec -T api python3 scripts/import_route_guides.py 2>&1 | tail -3"

echo "✅ 发布完成。小程序里下拉刷新路线页即可看到新内容（无需重新上传小程序）。"
