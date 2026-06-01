"""
文件存储的"接口规范"——定义了档案室必须提供的三项服务。

好比一份"档案室管理条例"：不管你是纸质档案室（本地硬盘）还是电子档案室（云存储），
都必须能做这三件事：存文件、取文件、删文件。

这样设计的好处：现在用本地硬盘存 GPX 文件，将来要换腾讯云 COS，
只需要按这份"条例"再建一个新档案室，上层代码一行不改。

注意事项：
- 这个文件只定义接口，不写具体实现
- 新增存储方式时，继承 StorageBackend 并实现全部三个方法
- 不要在这里 import 任何业务模块
"""

from abc import ABC, abstractmethod


class StorageBackend(ABC):
    """
    存储后端的抽象基类——所有存储实现的"模板"。
    定义三个必须实现的方法：上传、下载、删除。
    """

    @abstractmethod
    def upload(self, file_bytes: bytes, filename: str, subdir: str = "") -> str:
        """
        上传文件。
        参数：file_bytes 是文件内容（二进制），filename 是原始文件名，
              subdir 是可选子目录（如约骑照片用 "meetup_media" 和私密 GPX 隔离开）。
        返回：文件的唯一标识（本地实现返回相对路径含 subdir 前缀，云存储返回 object key）。

        注意：将来换腾讯云 COS 实现时，subdir 隔离必须照样实现，否则约骑照片会和私密轨迹混在一起。
        """
        ...

    @abstractmethod
    def download(self, file_id: str) -> bytes:
        """
        下载文件。
        参数：file_id 是上传时返回的唯一标识。
        返回：文件内容（二进制）。
        """
        ...

    @abstractmethod
    def delete(self, file_id: str) -> bool:
        """
        删除文件。
        参数：file_id 是上传时返回的唯一标识。
        返回：True 表示删除成功，False 表示文件不存在。
        """
        ...
