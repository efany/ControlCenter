import os
import sys
import time
from datetime import datetime

def write_timestamp():
    # 确保cache目录存在
    cache_dir = "cache"
    os.makedirs(cache_dir, exist_ok=True)
    
    # 生成时间戳文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(cache_dir, f"timestamp_{timestamp}.txt")
    
    # 写入当前时间
    with open(filename, "w") as f:
        f.write(str(datetime.now()))

def start_timer():
    count = 0
    while count < 5:
        write_timestamp()
        time.sleep(2)
        count += 1

def main():
    output_dir = ""  # 默认输出目录
    if len(sys.argv) > 1:
        try:
            dir_index = sys.argv.index("--output_dir") 
            output_dir = sys.argv[dir_index + 1]
            # 更新cache_dir为用户指定的目录
            global cache_dir
            cache_dir = output_dir
            print(f"输出目录设置为: {output_dir}")
        except (ValueError, IndexError):
            pass
    print("Hello, World!")
    print("这是一个示例Python项目")
    print("您可以：")
    print("1. 直接运行这个文件")
    print("2. 设置定时任务")
    print("3. 查看运行结果")
    start_timer()

if __name__ == "__main__":
    main() 