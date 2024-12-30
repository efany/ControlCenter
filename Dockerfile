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
    libssl-dev \
    libffi-dev \
    libfreetype6-dev \
    libpng-dev \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 设置环境变量
ENV PIP_NO_CACHE_DIR=off \
    PIP_DEFAULT_TIMEOUT=100 \
    PIP_DISABLE_PIP_VERSION_CHECK=on

# 升级pip
RUN pip install --upgrade pip setuptools wheel

# 安装Python包（包括MySQL相关包和cryptography）
RUN pip install --no-cache-dir flask
RUN pip install --no-cache-dir py7zr
RUN pip install --no-cache-dir APScheduler
RUN pip install --no-cache-dir GitPython
RUN pip install --no-cache-dir PyMySQL
RUN pip install --no-cache-dir mysqlclient
RUN pip install --no-cache-dir cryptography
RUN pip install --no-cache-dir requests
RUN pip install --no-cache-dir beautifulsoup4
RUN pip install --no-cache-dir urllib3
RUN pip install --no-cache-dir tushare
RUN pip install --no-cache-dir selenium
RUN pip install --no-cache-dir backtrader
RUN pip install --no-cache-dir pandas
RUN pip install --no-cache-dir openpyxl
RUN pip install --no-cache-dir fsspec 
RUN pip install --no-cache-dir numpy
RUN pip install --no-cache-dir Pillow
RUN pip install --no-cache-dir loguru

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