"""路线图片同步器测试——验证 Tim 在文件夹里增删图片后，指针和打包间都跟得上。"""

import json
from pathlib import Path

from scripts import sync_route_images


def _make_route(tmp_path: Path, name: str, files: dict[str, bytes], meta: dict | None = None) -> Path:
    route_dir = tmp_path / "routes" / name
    route_dir.mkdir(parents=True)
    (route_dir / "meta.json").write_text(
        json.dumps(meta if meta is not None else {"name": name}, ensure_ascii=False),
        encoding="utf-8",
    )
    for filename, content in files.items():
        (route_dir / filename).write_bytes(content)
    return route_dir


def test_cover_and_gallery_pointers_written_and_staged(tmp_path):
    route_dir = _make_route(
        tmp_path,
        "tianlongshan",
        {
            "cover.jpg": b"cover-bytes",
            "02_盘山公路.jpg": b"photo-two",
            "01_航拍.webp": b"photo-one",
            "guide.md": b"# x",  # 非图片文件不该被当成实景图
        },
    )
    staging = tmp_path / "staging"

    sync_route_images.main(["--content-dir", str(tmp_path / "routes"), "--staging-dir", str(staging)])

    meta = json.loads((route_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["cover_url"] == "/uploads/route_covers/tianlongshan.jpg"
    # 实景图按文件名排序：01_ 在前；URL 带 g 序号 + 内容哈希
    assert len(meta["gallery_urls"]) == 2
    assert meta["gallery_urls"][0].startswith("/uploads/route_covers/tianlongshan/g01_")
    assert meta["gallery_urls"][0].endswith(".webp")
    assert meta["gallery_urls"][1].startswith("/uploads/route_covers/tianlongshan/g02_")
    # 打包间：封面平铺 + 实景图进子目录，文件名与 URL 尾段一致
    assert (staging / "tianlongshan.jpg").exists()
    staged = sorted(p.name for p in (staging / "tianlongshan").iterdir())
    assert staged == [url.rsplit("/", 1)[1] for url in meta["gallery_urls"]]


def test_changed_photo_changes_url_hash(tmp_path):
    # 换图必换 URL（内容哈希进文件名）——否则小程序图片缓存会一直显示旧图
    route_dir = _make_route(tmp_path, "langpo", {"01_pic.jpg": b"old-bytes"})
    staging1 = tmp_path / "s1"
    sync_route_images.main(["--content-dir", str(tmp_path / "routes"), "--staging-dir", str(staging1)])
    url_old = json.loads((route_dir / "meta.json").read_text(encoding="utf-8"))["gallery_urls"][0]

    (route_dir / "01_pic.jpg").write_bytes(b"new-bytes")
    staging2 = tmp_path / "s2"
    sync_route_images.main(["--content-dir", str(tmp_path / "routes"), "--staging-dir", str(staging2)])
    url_new = json.loads((route_dir / "meta.json").read_text(encoding="utf-8"))["gallery_urls"][0]

    assert url_old != url_new


def test_deleting_all_photos_removes_gallery_key(tmp_path):
    # 图删光 = 撤下长廊：meta 里 gallery_urls 整个 key 消失（灌库存 NULL，前端整块隐藏）
    route_dir = _make_route(
        tmp_path,
        "qingxu",
        {},
        meta={"name": "qingxu", "gallery_urls": ["/uploads/route_covers/qingxu/g01_dead.jpg"]},
    )
    staging = tmp_path / "staging"

    sync_route_images.main(["--content-dir", str(tmp_path / "routes"), "--staging-dir", str(staging)])

    meta = json.loads((route_dir / "meta.json").read_text(encoding="utf-8"))
    assert "gallery_urls" not in meta


def test_hidden_symlink_and_uppercase_files_filtered_correctly(tmp_path):
    # 三类边界：macOS 伴生的 ._ 隐藏文件不进实景图（破图防线）、符号链接不跟随、
    # 大写后缀 .JPG 照常认（相机导出常见）
    route_dir = _make_route(
        tmp_path,
        "hengling",
        {
            "01_real.JPG": b"real-photo",
            "._01_real.JPG": b"apple-double-junk",
            ".hidden_draft.jpg": b"draft",
        },
    )
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"outside-bytes")
    (route_dir / "02_link.jpg").symlink_to(outside)
    staging = tmp_path / "staging"

    sync_route_images.main(["--content-dir", str(tmp_path / "routes"), "--staging-dir", str(staging)])

    meta = json.loads((route_dir / "meta.json").read_text(encoding="utf-8"))
    assert len(meta["gallery_urls"]) == 1
    assert meta["gallery_urls"][0].endswith(".jpg")  # 后缀统一小写
    assert meta["gallery_urls"][0].startswith("/uploads/route_covers/hengling/g01_")


def test_route_without_cover_keeps_meta_untouched(tmp_path):
    # 没封面没实景图的路线（如还没配图的新卡）：meta 原样不动，不写空指针
    route_dir = _make_route(tmp_path, "aoshen", {})
    before = (route_dir / "meta.json").read_text(encoding="utf-8")
    staging = tmp_path / "staging"

    sync_route_images.main(["--content-dir", str(tmp_path / "routes"), "--staging-dir", str(staging)])

    assert (route_dir / "meta.json").read_text(encoding="utf-8") == before
