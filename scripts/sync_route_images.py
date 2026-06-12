"""路线图片同步器——发布前把 content/routes 里的图片整理成"可上传 + 可入库"的形状。

这个文件是干什么的：像快递打包员——Tim 在路线文件夹里随手增删图片后，
它负责两件事：① 把每条路线的图片指针写进 meta.json（封面 cover_url + 实景图 gallery_urls），
② 把图片按服务器命名规则拷进一个临时"打包间"（staging 目录），等发布脚本一次 scp 走。

操作注意事项：
- 它只被 scripts/publish_routes.sh 调用，在 Tim 的 mac 上跑，不进容器、不连数据库；
- 命名规则改动要同时想清"重发布"场景——服务器文件名带内容哈希，
  换图必换 URL，小程序图片缓存天然失效，这是刻意设计不要省掉；
- 删图只影响 meta.json 列表（不再显示），服务器旧文件留作孤儿（几十 KB 级，无害）。

输入/输出：
- 输入：content/routes/<路线>/ 下的图片文件（cover.* = 封面，其余按文件名排序 = 实景图）
- 输出：改写各路线 meta.json 的 cover_url / gallery_urls 字段；staging 目录里备好待上传文件
  （封面平铺为 <路线>.<ext> 兼容老结构；实景图进 <路线>/ 子目录，命名 gNN_<内容哈希8位>.<ext>）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

# 认这些后缀是图片（统一小写比较）；cover.* 是封面，其余全算实景图
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
URL_PREFIX = "/uploads/route_covers"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Sync route images: write meta pointers + fill staging dir.")
    parser.add_argument("--content-dir", default="content/routes")
    parser.add_argument("--staging-dir", required=True)
    args = parser.parse_args(argv)

    content_dir = Path(args.content_dir)
    staging_dir = Path(args.staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)

    for route_dir in sorted(path for path in content_dir.iterdir() if path.is_dir()):
        sync_route(route_dir, staging_dir)


def sync_route(route_dir: Path, staging_dir: Path) -> None:
    """处理单条路线：算指针、改 meta.json、备好上传文件。"""
    meta_path = route_dir / "meta.json"
    if not meta_path.exists():
        return  # 没 meta.json 的目录不是路线（如 README 同级杂物），跳过不报错

    name = route_dir.name
    cover = find_cover(route_dir)
    gallery = find_gallery(route_dir)

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    changed = False

    if cover is not None:
        cover_url = f"{URL_PREFIX}/{name}{cover.suffix.lower()}"
        if meta.get("cover_url") != cover_url:
            meta["cover_url"] = cover_url
            changed = True
        # 封面平铺进打包间（沿用老命名 <路线>.<ext>，已发布的封面 URL 不漂移）
        shutil.copy2(cover, staging_dir / f"{name}{cover.suffix.lower()}")

    gallery_urls = []
    for index, photo in enumerate(gallery, start=1):
        server_name = _server_name(index, photo)
        gallery_urls.append(f"{URL_PREFIX}/{name}/{server_name}")
        route_staging = staging_dir / name
        route_staging.mkdir(parents=True, exist_ok=True)
        shutil.copy2(photo, route_staging / server_name)

    if gallery_urls:
        if meta.get("gallery_urls") != gallery_urls:
            meta["gallery_urls"] = gallery_urls
            changed = True
    elif "gallery_urls" in meta:
        # 图全删光 = 撤下实景图长廊：meta 删 key，灌库存 NULL，前端整块隐藏
        del meta["gallery_urls"]
        changed = True

    if changed:
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  图片指针更新: {meta_path}")


def _is_photo(path: Path) -> bool:
    """真图片的三重门：是普通文件（不跟符号链接）、不是点号开头的隐藏文件、后缀认识。

    隐藏文件这条专防 macOS：访达拷图、解压 zip 经常伴生 `._xxx.jpg`（AppleDouble 元数据），
    后缀像图片但内容不是——不滤掉就会被当实景图发布，用户看到一格格破图。
    """
    return (
        path.is_file()
        and not path.is_symlink()
        and not path.name.startswith(".")
        and path.suffix.lower() in IMAGE_EXTS
    )


def find_cover(route_dir: Path) -> Path | None:
    """封面 = 名字以 cover 开头的图片文件（现有约定不变），同时存在多个取排序第一个。"""
    covers = sorted(
        path for path in route_dir.iterdir()
        if _is_photo(path) and path.stem.lower().startswith("cover")
    )
    return covers[0] if covers else None


def find_gallery(route_dir: Path) -> list[Path]:
    """实景图 = 除封面外的所有图片，按文件名排序（Tim 用 01_/02_ 前缀控制顺序）。"""
    return sorted(
        path for path in route_dir.iterdir()
        if _is_photo(path) and not path.stem.lower().startswith("cover")
    )


def _server_name(index: int, photo: Path) -> str:
    """服务器文件名 = g序号_内容哈希8位.后缀。

    为什么带哈希：URL 即缓存键——换图必换 URL，小程序端旧缓存自然失效；
    为什么带序号：排序意图直接可见，服务器上肉眼可对照本地顺序。
    """
    digest = hashlib.md5(photo.read_bytes()).hexdigest()[:8]
    return f"g{index:02d}_{digest}{photo.suffix.lower()}"


if __name__ == "__main__":
    main()
