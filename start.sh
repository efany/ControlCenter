#!/bin/bash

# 确保数据库目录存在
mkdir -p /app/data

# 如果数据库文件不存在，创建它
if [ ! -f /app/data/database.db ]; then
    echo "Initializing database..."
    sqlite3 /app/data/database.db "CREATE TABLE IF NOT EXISTS run_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id TEXT NOT NULL,
        project_title TEXT NOT NULL,
        command TEXT NOT NULL,
        working_directory TEXT NOT NULL,
        status TEXT NOT NULL,
        output_file TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        duration REAL
    );"
fi

# 确保数据库文件权限正确
chown www-data:www-data /app/data/database.db

# 启动nginx
service nginx start

# 启动Flask应用
python app.py 