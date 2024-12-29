from flask import Flask, render_template, request, jsonify, send_from_directory, Response, stream_with_context, send_file
import os
from werkzeug.utils import secure_filename
import subprocess
import sys
from threading import Timer
import zipfile
import tarfile
import py7zr
import shutil
from apscheduler.schedulers.background import BackgroundScheduler
import json
from datetime import datetime, timezone
import string
import random
import git
import tempfile
import pymysql
from pymysql.cursors import DictCursor
import threading
import queue
import time
import fcntl
import select
from io import BytesIO
import signal
import pytz

app = Flask(__name__)

# 配置
UPLOAD_FOLDER = 'uploads'
EXTRACT_FOLDER = 'uploads/extracted'
DOWNLOAD_FOLDER = 'downloads'
TASKS_FILE = 'tasks.json'

app.config.update(
    UPLOAD_FOLDER=UPLOAD_FOLDER,
    EXTRACT_FOLDER=EXTRACT_FOLDER,
    DOWNLOAD_FOLDER=DOWNLOAD_FOLDER,
    MAX_CONTENT_LENGTH=16 * 1024 * 1024  # 16MB
)

# 创建必要的目录
for folder in [UPLOAD_FOLDER, EXTRACT_FOLDER, DOWNLOAD_FOLDER]:
    os.makedirs(folder, exist_ok=True)

# 初始化调度器
scheduler = BackgroundScheduler()
scheduler.start()

# 数据库配置
DB_CONFIG = {
    'host': '192.168.0.11',
    'port': 3306,
    'user': 'root',
    'password': '123456',
    'db': 'controlcenter',
    'charset': 'utf8mb4',
    'cursorclass': DictCursor
}

# Store running processes in a dictionary
running_processes = {}

# Define the Beijing timezone
beijing_tz = pytz.timezone('Asia/Shanghai')

def get_current_time():
    """Get the current time in Beijing timezone."""
    return datetime.now(beijing_tz)

def get_db():
    return pymysql.connect(**DB_CONFIG)

# 初始化数据库
def init_db():
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            # 检查表是否存在
            cursor.execute('''
                SELECT COUNT(*) 
                FROM information_schema.tables 
                WHERE table_schema = 'controlcenter'
                AND table_name IN ('projects', 'run_records', 'scheduled_tasks')
            ''')
            result = cursor.fetchone()
            
            # 如果所有表都存在，直接返回
            if result['COUNT(*)'] == 3:
                return

            # 创建项目表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS projects (
                    id VARCHAR(12) PRIMARY KEY,
                    title VARCHAR(255) NOT NULL,
                    description TEXT,
                    source_type VARCHAR(50) NOT NULL,
                    git_url VARCHAR(255),
                    git_branch VARCHAR(100),
                    repo_name VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            ''')

            # 创建运行记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS run_records (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    project_id VARCHAR(12) NOT NULL,
                    project_title VARCHAR(255) NOT NULL,
                    command TEXT NOT NULL,
                    working_directory TEXT NOT NULL,
                    status VARCHAR(50) NOT NULL,
                    running_status VARCHAR(20) DEFAULT 'completed',
                    output_file VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    duration FLOAT,
                    FOREIGN KEY (project_id) REFERENCES projects(id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            ''')

            # 创建定时任务表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS scheduled_tasks (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    project_id VARCHAR(12) NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    cron_expr VARCHAR(100) NOT NULL,
                    command TEXT NOT NULL,
                    status VARCHAR(50) DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_run TIMESTAMP NULL,
                    next_run TIMESTAMP NULL,
                    FOREIGN KEY (project_id) REFERENCES projects(id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            ''')

        conn.commit()
    finally:
        conn.close()

# 在 app 初始化后调用
init_db()

def load_tasks():
    if os.path.exists(TASKS_FILE):
        with open(TASKS_FILE, 'r') as f:
            return json.load(f)
    return []

def save_tasks(tasks):
    with open(TASKS_FILE, 'w') as f:
        json.dump(tasks, f)

# 路由
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/projects')
def projects():
    return render_template('projects.html')

@app.route('/runner')
def runner():
    return render_template('runner.html')

@app.route('/scheduler')
def scheduler_page():
    return render_template('scheduler.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'project' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    files = request.files.getlist('project')
    uploaded_files = []
    extract_results = []
    
    for file in files:
        if file.filename:
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            uploaded_files.append(filename)
            
            # 如果是压缩文件，尝试解压
            if filename.endswith(('.zip', '.tar.gz', '.rar', '.7z')):
                success, result = extract_archive(file_path, filename)
                extract_results.append({
                    'filename': filename,
                    'status': 'success' if success else 'error',
                    'result': result
                })
    
    return jsonify({
        'message': 'Files uploaded successfully',
        'files': get_all_files(),
        'extractions': extract_results
    })

def extract_archive(filepath, target_dir):
    """
    解压文件到指定目录
    filepath: 压缩文件路径
    target_dir: 解压目标目录
    """
    try:
        if filepath.endswith('.zip'):
            with zipfile.ZipFile(filepath, 'r') as zip_ref:
                zip_ref.extractall(target_dir)
        elif filepath.endswith('.tar.gz'):
            with tarfile.open(filepath, 'r:gz') as tar_ref:
                tar_ref.extractall(target_dir)
        elif filepath.endswith(('.rar', '.7z')):
            with py7zr.SevenZipFile(filepath, mode='r') as z:
                z.extractall(target_dir)
        return True, "解压成功"
    except Exception as e:
        return False, f"解压失败: {str(e)}"

@app.route('/files')
def list_files():
    return jsonify({'files': get_all_files()})

def get_all_files():
    files = []
    # 获取上传的文件
    for file in os.listdir(app.config['UPLOAD_FOLDER']):
        if os.path.isfile(os.path.join(app.config['UPLOAD_FOLDER'], file)):
            files.append(file)
    
    # 获取解压的Python文件
    for root, _, filenames in os.walk(app.config['EXTRACT_FOLDER']):
        for filename in filenames:
            if filename.endswith('.py'):
                rel_path = os.path.relpath(
                    os.path.join(root, filename),
                    app.config['EXTRACT_FOLDER']
                )
                files.append(f"extracted/{rel_path}")
    
    return files

@app.route('/run/<path:filename>', methods=['POST'])
def run_python_file(filename):
    try:
        if filename.startswith('extracted/'):
            file_path = os.path.join(
                app.config['EXTRACT_FOLDER'],
                filename.replace('extracted/', '', 1)
            )
        else:
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        if not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404

        # 创建输出文件
        output_filename = f"output_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        output_path = os.path.join(app.config['DOWNLOAD_FOLDER'], output_filename)

        # 运行Python件并捕获输出
        process = subprocess.Popen(
            [sys.executable, file_path] + request.json.get('args', '').split(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        try:
            stdout, stderr = process.communicate(timeout=30)
            
            # 存输出到文件
            with open(output_path, 'w') as f:
                f.write(f"=== STDOUT ===\n{stdout}\n\n=== STDERR ===\n{stderr}")

            return jsonify({
                'output': stdout,
                'error': stderr,
                'output_file': output_filename,
                'status': 'success' if process.returncode == 0 else 'error'
            })

        except subprocess.TimeoutExpired:
            process.kill()
            return jsonify({
                'error': '程序运行超时（30秒）',
                'status': 'timeout'
            })

    except Exception as e:
        return jsonify({
            'error': str(e),
            'status': 'error'
        })

@app.route('/download/<filename>')
def download_output(filename):
    return send_from_directory(app.config['DOWNLOAD_FOLDER'], filename)

@app.route('/tasks', methods=['GET', 'POST'])
def manage_tasks():
    if request.method == 'GET':
        return jsonify({'tasks': load_tasks()})
    
    data = request.json
    tasks = load_tasks()
    
    # 创建新任务
    task = {
        'id': len(tasks) + 1,
        'name': data['name'],
        'filename': data['filename'],
        'cron': data['cron'],
        'args': data.get('args', ''),
        'status': 'active'
    }
    
    # 添加到调度器
    scheduler.add_job(
        run_scheduled_task,
        'cron',
        id=str(task['id']),
        **parse_cron(data['cron']),
        args=[task]
    )
    
    tasks.append(task)
    save_tasks(tasks)
    
    return jsonify(task)

def parse_cron(cron_str):
    minute, hour, day, month, day_of_week = cron_str.split()
    return {
        'minute': minute,
        'hour': hour,
        'day': day,
        'month': month,
        'day_of_week': day_of_week
    }

def run_scheduled_task(task):
    run_python_file(task['filename'])

@app.route('/tasks/<int:task_id>', methods=['DELETE'])
def delete_task(task_id):
    tasks = load_tasks()
    tasks = [t for t in tasks if t['id'] != task_id]
    save_tasks(tasks)
    
    # 从调度器中移除任务
    scheduler.remove_job(str(task_id))
    
    return jsonify({'message': 'Task deleted'})

def generate_project_id():
    """生成12位随机项目ID"""
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(12))

@app.route('/api/upload', methods=['POST'])
def api_upload():
    if 'files' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    project_id = request.form.get('projectId')
    if not project_id:
        return jsonify({'error': 'No project ID'}), 400

    # 创建项目目录
    project_dir = os.path.join(app.config['UPLOAD_FOLDER'], project_id)
    os.makedirs(project_dir, exist_ok=True)

    files = request.files.getlist('files')
    uploaded_files = []
    
    for file in files:
        if file.filename:
            filename = secure_filename(file.filename)
            file_path = os.path.join(project_dir, filename)
            file.save(file_path)
            uploaded_files.append(filename)
            
            # 如果是压缩文件，解压到项目目录下
            if filename.endswith(('.zip', '.tar.gz', '.rar', '.7z')):
                try:
                    extract_dir = os.path.join(project_dir, 'extracted')
                    os.makedirs(extract_dir, exist_ok=True)
                    extract_archive(file_path, filename, extract_dir)
                except Exception as e:
                    return jsonify({'error': f'解压压失败: {str(e)}'}), 500

    return jsonify({
        'message': 'Files uploaded successfully',
        'project_id': project_id,
        'files': uploaded_files
    })

@app.route('/api/projects', methods=['GET'])
def api_list_projects():
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute('''
                SELECT id, title, description, source_type, git_url, git_branch, repo_name, created_at 
                FROM projects
                ORDER BY created_at DESC
            ''')
            projects = cursor.fetchall()
            
            # 对于Git项目，添加仓库名称显示
            for project in projects:
                if project['source_type'] == 'git' and project['repo_name']:
                    project['display_name'] = f"{project['title']} ({project['repo_name']})"
                else:
                    project['display_name'] = project['title']

        return jsonify({'projects': projects})
    finally:
        conn.close()

@app.route('/api/projects/<project_id>', methods=['DELETE'])
def api_delete_project(project_id):
    conn = get_db()
    try:
        # 首先检查项目是否存在
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM projects WHERE id = %s', (project_id,))
            project = cursor.fetchone()
            
            if not project:
                return jsonify({'error': 'Project not found'}), 404

            # 开始删除操作
            try:
                # 1. 先删除相关的运行记录和定时任务（因为它们有外键约束）
                cursor.execute('DELETE FROM run_records WHERE project_id = %s', (project_id,))
                cursor.execute('DELETE FROM scheduled_tasks WHERE project_id = %s', (project_id,))
                
                # 2. 删除项目记录
                cursor.execute('DELETE FROM projects WHERE id = %s', (project_id,))
                
                # 3. 最后删除项目目录
                project_dir = os.path.join(app.config['UPLOAD_FOLDER'], project_id)
                if os.path.exists(project_dir):
                    shutil.rmtree(project_dir)
                
                # 4. 提交事务
                conn.commit()
                
                return jsonify({'message': 'Project deleted successfully'})

            except Exception as e:
                # 如果删除过程中出现错误，回滚数据库操作
                conn.rollback()
                return jsonify({'error': f'删除失败: {str(e)}'}), 500

    except Exception as e:
        return jsonify({'error': f'操作失败: {str(e)}'}), 500
    finally:
        conn.close()

@app.route('/api/projects', methods=['POST'])
def api_create_project():
    project_id = request.form.get('projectId')
    title = request.form.get('title')
    description = request.form.get('description', '')
    source_type = request.form.get('sourceType')

    if not project_id or not title:
        return jsonify({'error': 'Missing project ID or title'}), 400

    conn = get_db()
    try:
        # 检查目ID否已存在
        with conn.cursor() as cursor:
            cursor.execute('SELECT id FROM projects WHERE id = %s', (project_id,))
            if cursor.fetchone():
                return jsonify({'error': 'Project ID already exists'}), 400

        # 创建项目目录
        project_dir = os.path.join(app.config['UPLOAD_FOLDER'], project_id)
        os.makedirs(project_dir, exist_ok=True)

        # 准备项目信息
        project_info = {
            'id': project_id,
            'title': title,
            'description': description,
            'source_type': source_type,
            'git_url': None,
            'git_branch': None,
            'repo_name': None
        }

        if source_type == 'git':
            git_url = request.form.get('gitUrl')
            git_branch = request.form.get('gitBranch', 'main')
            
            if not git_url:
                return jsonify({'error': 'Git URL is required'}), 400

            try:
                repo_name = git_url.rstrip('.git').split('/')[-1]
                repo_dir = os.path.join(project_dir, repo_name)
                
                repo = git.Repo.clone_from(
                    git_url,
                    repo_dir,
                    branch=git_branch
                )
                project_info.update({
                    'git_url': git_url,
                    'git_branch': git_branch,
                    'repo_name': repo_name
                })
            except Exception as e:
                shutil.rmtree(project_dir, ignore_errors=True)
                return jsonify({'error': f'Git clone failed: {str(e)}'}), 500

        else:  # 文件上传
            if 'files' not in request.files:
                return jsonify({'error': 'No file part'}), 400

            files = request.files.getlist('files')
            uploaded_files = []
            
            for file in files:
                if file.filename:
                    filename = secure_filename(file.filename)
                    file_path = os.path.join(project_dir, filename)
                    file.save(file_path)
                    uploaded_files.append(filename)
                    
                    # 如果是压缩文件，解压到项目目录下
                    if filename.endswith(('.zip', '.tar.gz', '.rar', '.7z')):
                        success, message = extract_archive(file_path, project_dir)
                        if not success:
                            # 清理已上传的文件
                            shutil.rmtree(project_dir, ignore_errors=True)
                            return jsonify({'error': message}), 500
                        # 解压成后删除原压缩文件
                        os.remove(file_path)
                        # 从传文件列表中移除压缩文件
                        uploaded_files.remove(filename)

            # 查找第一级目录作为repo_name
            subdirs = [d for d in os.listdir(project_dir) 
                      if os.path.isdir(os.path.join(project_dir, d))]
            
            # 如果有子目录，使用第一个作为repo_name
            if subdirs:
                project_info['repo_name'] = subdirs[0]
            else:
                # 如果没有子目录，使用项目ID作为repo_name
                project_info['repo_name'] = project_id

            project_info['uploaded_files'] = uploaded_files

        # 保存项目信息到数据库
        with conn.cursor() as cursor:
            sql = '''INSERT INTO projects 
                    (id, title, description, source_type, git_url, git_branch, repo_name)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)'''
            cursor.execute(sql, (
                project_id,
                title,
                description,
                source_type,
                project_info.get('git_url'),
                project_info.get('git_branch'),
                project_info.get('repo_name')  # 在本地项目也会有repo_name
            ))
        conn.commit()

        return jsonify({
            'message': 'Project created successfully',
            'project': project_info
        })

    except Exception as e:
        conn.rollback()
        if os.path.exists(project_dir):
            shutil.rmtree(project_dir)
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/run/<project_id>/<path:filename>', methods=['POST'])
def api_run_file(project_id, filename):
    try:
        # 构建文件路径
        project_dir = os.path.join(app.config['UPLOAD_FOLDER'], project_id)
        file_path = os.path.join(project_dir, filename)

        # 检查项目信息
        project_info_path = os.path.join(project_dir, 'project.json')
        if os.path.exists(project_info_path):
            with open(project_info_path, 'r') as f:
                project_info = json.load(f)
                if project_info.get('source_type') == 'git':
                    # 对于git项目，文件路径需要包含仓库名称
                    repo_name = project_info.get('repo_name')
                    if repo_name:
                        file_path = os.path.join(project_dir, repo_name, filename)

        if not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404

        if not file_path.endswith('.py'):
            return jsonify({'error': 'Only Python files can be executed'}), 400

        # 建输出文件
        output_filename = f"output_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        output_path = os.path.join(app.config['DOWNLOAD_FOLDER'], output_filename)

        # 获取参数
        args = request.json.get('args', '').split()

        # 运行Python文件并捕获输出
        process = subprocess.Popen(
            [sys.executable, file_path] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        try:
            stdout, stderr = process.communicate(timeout=30)
            
            # 保存输出到文件
            with open(output_path, 'w') as f:
                f.write(f"=== STDOUT ===\n{stdout}\n\n=== STDERR ===\n{stderr}")

            return jsonify({
                'output': stdout,
                'error': stderr,
                'output_file': output_filename,
                'status': 'success' if process.returncode == 0 else 'error'
            })

        except subprocess.TimeoutExpired:
            process.kill()
            return jsonify({
                'error': '程序运行超时（30秒）',
                'status': 'timeout'
            })

    except Exception as e:
        return jsonify({
            'error': str(e),
            'status': 'error'
        })

def tail_file(filename):
    """跟踪文件内容"""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            # 设置非阻塞模式
            fd = f.fileno()
            fl = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
            
            while True:
                line = f.readline()
                if line:
                    yield line
                else:
                    # 检查进程是否还在运行
                    if not os.path.exists(filename):
                        break
                    time.sleep(0.1)

    except Exception as e:
        yield f"Error reading log: {str(e)}"

@app.route('/api/run/<project_id>', methods=['POST'])
def api_run_project(project_id):
    try:
        start_time = get_current_time()
        command = request.json.get('command', '').strip()
        if not command:
            return jsonify({'error': 'Command is required'}), 400

        # 生成运行ID和目录
        run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{project_id}"
        run_base_dir = os.path.join(app.config['DOWNLOAD_FOLDER'], run_id)
        log_dir = os.path.join(run_base_dir, 'log')
        output_dir = os.path.join(os.path.abspath(run_base_dir), 'output')  # 使用绝对路径
        
        # 创建目录
        os.makedirs(log_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)

        # 获取项目信息
        conn = get_db()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT * FROM projects WHERE id = %s', (project_id,))
                project_info = cursor.fetchone()
                if not project_info:
                    return jsonify({'error': 'Project not found'}), 404
        finally:
            conn.close()

        # 确定工作目录
        project_dir = os.path.join(app.config['UPLOAD_FOLDER'], project_id)
        if not os.path.exists(project_dir):
            return jsonify({'error': 'Project directory not found'}), 404

        work_dir = os.path.join(project_dir, project_info['repo_name'])
        if not os.path.exists(work_dir):
            return jsonify({'error': 'Working directory not found'}), 404

        # 构建完整的命令
        # 分离Python文件路径和参数
        command_parts = command.split()
        
        if not command_parts:
            return jsonify({'error': 'No Python file specified'}), 400

        python_file = command_parts[1]  # 第一个部分是Python文件
        if len(command_parts) > 2:
            args = command_parts[2:]  # 剩余部分是参数
        else:
            args = []

        # 构建完整命令，使用绝对路径
        full_command = [sys.executable, python_file]
        if '--output_dir' in args:
            # 如果命令中已经有 output_dir，替换为绝对路径
            output_index = args.index('--output_dir')
            if output_index + 1 < len(args):
                args[output_index + 1] = output_dir
        else:
            # 如果没有，添加 output_dir 参数
            full_command.extend(['--output_dir', output_dir])
        
        full_command.extend(args)

        # 创建日志文件
        log_file = os.path.join(log_dir, 'execution.log')

        # 先创建运行记录，状态为 running
        conn = get_db()
        try:
            with conn.cursor() as cursor:
                # 将命令列表转换为字符串以存储
                command_str = ' '.join(str(x) for x in full_command)
                insert_run_record(cursor, project_id, project_info['title'], command_str, work_dir, run_id)
                record_id = cursor.lastrowid
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to create run record: {str(e)}")
        finally:
            conn.close()

        def generate():
            try:
                # Start the process
                process = subprocess.Popen(
                    full_command,
                    shell=False,
                    cwd=work_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )

                # Store the process in the running_processes dictionary
                running_processes[record_id] = process

                # 创建日志文件并开始写入
                with open(log_file, 'w', encoding='utf-8') as f:
                    f.write(f"=== COMMAND ===\n{full_command}\n")
                    f.write(f"=== WORKING DIRECTORY ===\n{work_dir}\n\n")
                    f.write("=== OUTPUT ===\n")
                    f.flush()

                # 设置非阻塞模式
                for pipe in [process.stdout, process.stderr]:
                    fd = pipe.fileno()
                    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
                    fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

                # 准备select的文件描述符
                read_set = [process.stdout, process.stderr]
                
                while read_set:
                    # 使用select监控输出
                    try:
                        readable, _, _ = select.select(read_set, [], [], 0.1)
                    except select.error:
                        break

                    for pipe in readable:
                        line = pipe.readline()
                        if not line:
                            read_set.remove(pipe)
                            continue

                        # 确定输出类型
                        stream_type = 'stderr' if pipe == process.stderr else 'stdout'
                        
                        # 写入日志文件
                        with open(log_file, 'a', encoding='utf-8') as f:
                            f.write(line)
                            f.flush()
                        
                        # 立即发送到客户端
                        yield f"data: {json.dumps({'type': stream_type, 'line': line})}\n\n"

                    # 检查进程是否结束
                    if process.poll() is not None and not readable:
                        break

                # Wait for the process to finish
                process.wait()
                duration = (datetime.now() - start_time).total_seconds()

                # Update the run record status
                conn = get_db()
                try:
                    with conn.cursor() as cursor:
                        cursor.execute('''
                            UPDATE run_records 
                            SET status = %s, 
                                running_status = 'completed',
                                duration = %s 
                            WHERE id = %s
                        ''', (
                            'success' if process.returncode == 0 else 'error',
                            float(duration),  # 确保是浮点数
                            record_id
                        ))
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    raise Exception(f"Failed to update run record: {str(e)}")
                finally:
                    conn.close()

                # Send completion message
                yield f"data: {json.dumps({'type': 'end', 'returncode': process.returncode, 'duration': duration})}\n\n"

            except Exception as e:
                # Handle exceptions and update the database
                # ... existing exception handling code ...

                # Update the run record status
                conn = get_db()
                try:
                    with conn.cursor() as cursor:
                        cursor.execute('''
                            UPDATE run_records 
                            SET status = 'error', 
                                running_status = 'completed',
                                duration = %s
                            WHERE id = %s
                        ''', (
                            float((datetime.now() - start_time).total_seconds()),
                            record_id
                        ))
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    raise Exception(f"Failed to update error status: {str(e)}")
                finally:
                    conn.close()

                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype='text/event-stream'
        )

    except Exception as e:
        # 如果在创建记录后发生错误，更新记录状态
        if 'record_id' in locals():
            conn = get_db()
            try:
                with conn.cursor() as cursor:
                    cursor.execute('''
                        UPDATE run_records 
                        SET status = 'error', 
                            running_status = 'completed',
                            duration = %s
                        WHERE id = %s
                    ''', (
                        float((datetime.now() - start_time).total_seconds()),
                        record_id
                    ))
                conn.commit()
            finally:
                conn.close()

        return jsonify({
            'error': str(e),
            'status': 'error'
        }), 500

@app.route('/records')
def records():
    return render_template('records.html')

@app.route('/api/records')
def api_list_records():
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute('''
                SELECT * FROM run_records
                ORDER BY created_at DESC
                LIMIT 100
            ''')
            records = cursor.fetchall()
        return jsonify({'records': records})
    finally:
        conn.close()

@app.route('/api/records/<int:record_id>', methods=['DELETE'])
def api_delete_record(record_id):
    conn = get_db()
    try:
        # 首先获取记录信息
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM run_records WHERE id = %s', (record_id,))
            record = cursor.fetchone()
            
            if not record:
                return jsonify({'error': 'Record not found'}), 404

            # 如果有运行ID，删除对应的目录
            if record['output_file'] and record['output_file'].startswith('run_'):
                run_dir = os.path.join(app.config['DOWNLOAD_FOLDER'], record['output_file'])
                if os.path.exists(run_dir):
                    shutil.rmtree(run_dir)

            # 删除数据库记录
            cursor.execute('DELETE FROM run_records WHERE id = %s', (record_id,))
            conn.commit()
            
            return jsonify({'message': 'Record deleted successfully'})

    except Exception as e:
        conn.rollback()
        return jsonify({'error': f'删除失败: {str(e)}'}), 500
    finally:
        conn.close()

@app.route('/api/records/<run_id>/download', methods=['GET'])
def api_download_run_output(run_id):
    """下载运行产物的压缩包"""
    try:
        run_dir = os.path.join(app.config['DOWNLOAD_FOLDER'], run_id)
        if not os.path.exists(run_dir):
            return jsonify({'error': 'Run directory not found'}), 404

        # 创建内存中的zip文件
        memory_file = BytesIO()
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            # 遍历目录下的所有文件
            for root, _, files in os.walk(run_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arc_name = os.path.relpath(file_path, run_dir)
                    zf.write(file_path, arc_name)

        # 将指针移到开始
        memory_file.seek(0)
        
        return send_file(
            memory_file,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f'{run_id}.zip'
        )

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/records/<int:record_id>/terminate', methods=['POST'])
def api_terminate_record(record_id):
    """Terminate a running task."""
    try:
        # Check if the process is running
        if record_id in running_processes:
            process = running_processes[record_id]
            process.terminate()  # Send termination signal
            process.wait()  # Wait for the process to terminate

            # Update the run record status
            conn = get_db()
            try:
                with conn.cursor() as cursor:
                    cursor.execute('''
                        UPDATE run_records 
                        SET status = 'terminated', 
                            running_status = 'completed'
                        WHERE id = %s
                    ''', (record_id,))
                conn.commit()
            finally:
                conn.close()

            # Remove the process from the running list
            del running_processes[record_id]

            return jsonify({'message': 'Task terminated successfully'})
        else:
            return jsonify({'error': 'Task not running or already completed'}), 400

    except Exception as e:
        return jsonify({'error': str(e)}), 500

def insert_run_record(cursor, project_id, project_title, command_str, work_dir, run_id):
    created_at = get_current_time()
    cursor.execute('''
        INSERT INTO run_records (
            project_id, project_title, command, working_directory,
            status, running_status, output_file, duration, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ''', (
        project_id,
        project_title,
        command_str,
        work_dir,
        'pending',
        'running',
        run_id,
        0.0,
        created_at
    ))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000) 