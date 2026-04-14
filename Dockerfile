# RIDEMAP 后端 Docker 镜像
#
# 基于 Python 3.11 精简版，只装运行时依赖，不装开发工具。
# 构建：docker build -t ridemap-api .
# 运行：由 docker-compose.yml 编排，不需要手动 docker run。

FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 先复制依赖清单，利用 Docker 缓存：
# 只要 requirements.txt 没变，下次构建就跳过 pip install（省几分钟）
COPY requirements.txt .
# 使用腾讯云 pip 镜像（服务器在腾讯云，走内网下载，速度从分钟级降到秒级）
RUN pip install --no-cache-dir -r requirements.txt -i https://mirrors.cloud.tencent.com/pypi/simple --trusted-host mirrors.cloud.tencent.com

# 再复制全部代码
COPY . .

# 默认启动命令（docker-compose.yml 中会覆盖）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
