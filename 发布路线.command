#!/bin/bash
# 双击我 = 发布路线修改到 velo 生产环境。
# （macOS 双击 .command 文件会自动打开终端窗口显示进度，跑完按回车关窗口）
cd "$(dirname "$0")"
./scripts/publish_routes.sh || echo "❌ 出错了——把这个窗口截图发给 Claude 看一眼"
echo ""
read -p "── 按回车键关闭窗口 ──"
