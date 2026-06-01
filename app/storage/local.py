"""
本地文件存储实现——把 GPX 文件存到服务器硬盘上。

好比大楼的"纸质档案室"：文件按年月分柜存放，每个文件贴唯一编号（UUID），
需要时凭编号去对应柜子里取。

存储路径规则：./uploads/202604/a1b2c3d4.gpx
- uploads 是档案室的门
- 202604 是年月柜子（自动创建）
- a1b2c3d4.gpx 是唯一编号，防止重名覆盖

注意事项：
- 这是开发环境用的存储方式，生产环境将来会切换到腾讯云 COS
- UPLOAD_DIR 配置在 .env 中，默认是 ./uploads
- 不要手动改动 uploads 文件夹内的目录结构
"""

import os
import uuid
from datetime import datetime

from app.config import settings
from app.storage.base import StorageBackend


class LocalStorage(StorageBackend):
    """
    本地文件系统存储实现。
    文件存到 {UPLOAD_DIR}/{年月}/{uuid}.gpx 的路径下。
    """

    def __init__(self):
        # 存储根目录，从配置中读取（默认 ./uploads）
        self.root = os.path.abspath(settings.UPLOAD_DIR)

    def _safe_path(self, file_id: str) -> str:
        """
        拼接路径并做安全校验，防止"路径穿越"攻击。

        什么是路径穿越？如果有人传入 "../../etc/passwd" 作为文件名，
        os.path.join 会拼出档案室外面的路径，导致读取或删除服务器上的其他文件。
        这个方法确保最终路径一定在档案室（UPLOAD_DIR）内部，出界就报错。
        """
        full = os.path.normpath(os.path.join(self.root, file_id))
        # 用 commonpath 而非 startswith 校验：startswith 会把 "/srv/uploads_evil" 误判成
        # 在 "/srv/uploads" 内（同前缀目录绕过），commonpath 按路径分段比较，只有真正落在
        # root 内部才通过，堵住这个潜在脚枪。
        if os.path.commonpath([self.root, full]) != self.root:
            raise ValueError(f"非法文件路径: {file_id}")
        return full

    def upload(self, file_bytes: bytes, filename: str, subdir: str = "") -> str:
        """
        把文件存到本地硬盘。

        步骤：
        1. 可选 subdir 子目录隔离不同类文件（如约骑照片存 meetup_media/，避免和私密 GPX
           混在 uploads 根、被 caddy 静态服务一起暴露——见隐私事故修复 2026-06-01）
        2. 用当前年月创建子文件夹（如 202604），按月归档方便管理
        3. 用 UUID 生成唯一文件名，避免不同用户上传同名文件互相覆盖
        4. 保留原文件的扩展名（.gpx）
        5. 返回相对路径（含 subdir 前缀）作为文件标识，存入数据库
        """
        # subdir 只允许简单目录名（防路径穿越）：当前调用方都硬编码（如 "meetup_media"），
        # 但加白名单式校验，避免将来有人把用户输入透传进来后能写到 uploads 外面。
        if subdir and (os.path.sep in subdir or (os.path.altsep and os.path.altsep in subdir) or ".." in subdir or os.path.isabs(subdir)):
            raise ValueError(f"非法子目录: {subdir}")
        # 按年月归档，比如 2026年4月 → "202604"；subdir 非空时多一层隔离目录
        month_dir = datetime.now().strftime("%Y%m")
        rel_dir = os.path.join(subdir, month_dir) if subdir else month_dir
        dir_path = os.path.join(self.root, rel_dir)
        os.makedirs(dir_path, exist_ok=True)

        # 提取原文件扩展名（.gpx），拼上 UUID 作为新文件名
        ext = os.path.splitext(filename)[1] or ".gpx"
        unique_name = f"{uuid.uuid4().hex}{ext}"
        file_path = os.path.join(dir_path, unique_name)

        # 以二进制模式写入文件
        with open(file_path, "wb") as f:
            f.write(file_bytes)

        # 返回相对路径（如 "meetup_media/202604/a1b2c3d4.jpg" 或 "202604/x.gpx"），存入数据库。
        # file_id 含 subdir 前缀，download/delete 用它能定位，前端拼 URL 也带前缀。
        return os.path.join(rel_dir, unique_name)

    def download(self, file_id: str) -> bytes:
        """
        从本地硬盘读取文件。
        file_id 就是上传时返回的相对路径。
        """
        file_path = self._safe_path(file_id)
        with open(file_path, "rb") as f:
            return f.read()

    def delete(self, file_id: str) -> bool:
        """
        从本地硬盘删除文件。
        返回 True 表示删除成功，False 表示文件本来就不存在。
        """
        file_path = self._safe_path(file_id)
        if os.path.exists(file_path):
            os.remove(file_path)
            return True
        return False
