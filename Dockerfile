FROM python:3.9-slim

# 安装系统依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    nginx \
    cron \
    p7zip-full \
    git \
    pkg-config \
    build-essential \
    python3-dev \
    libmariadb-dev \
    && rm -rf /var/lib/apt/lists/*

# 升级pip
RUN pip install --upgrade pip setuptools wheel

# 安装Python包（不包含MySQL相关包）
RUN pip install --no-cache-dir \
    flask \
    py7zr \
    APScheduler \
    GitPython

# 单独安装MySQL相关包
RUN pip install --no-cache-dir PyMySQL && \
    pip install --no-cache-dir mysqlclient

# 设置工作目录
WORKDIR /app

# 复制应用文件
COPY templates/ /app/templates/
COPY static/ /app/static/
COPY app.py /app/
COPY nginx/nginx.conf /etc/nginx/nginx.conf
COPY examples/ /app/examples/

# 创建必要的目录
RUN mkdir -p /app/uploads /app/uploads/thisisaexample /app/downloads /app/data && \
    chown -R www-data:www-data /app/uploads /app/downloads /app/data && \
    # 复制示例文件到uploads目录
    cp /app/examples/* /app/uploads/thisisaexample/

# 暴露端口
EXPOSE 80

# 启动脚本
COPY start.sh /start.sh
RUN chmod +x /start.sh

CMD ["/start.sh"] 