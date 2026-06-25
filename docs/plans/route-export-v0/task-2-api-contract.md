# Task 2：后端接口合同

## 目标

让小程序能创建导出任务并下载二进制文件，同时不暴露内部 `file_id`。

## 用户多了什么体验

小明点“下载 GPX”，后端马上返回一个受控下载地址；小程序拿到的是真文件，不是一段 JSON，也不是裸露的服务器文件路径。

## 改动范围

- `app/route_book/router.py`
- `app/route_book/schemas.py`
- `tests/test_route_book_api.py`
- `tests/conftest.py`

## 合同

- `POST /api/route-books/{route_book_id}/exports`
- `GET /api/route-books/{route_book_id}/exports/{artifact_id}/download`
- 公开已发布路线允许匿名导出。
- 私有路线只允许创建者或管理员导出。
- 没有 `current_version_id` 返回 422。
- 响应不返回 `file_id`。
- 下载响应必须是二进制文件，并带附件文件名。

## 验收

```bash
pytest tests/test_route_book_api.py
```
