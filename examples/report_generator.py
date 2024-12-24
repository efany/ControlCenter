import time
from datetime import datetime

def generate_report():
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    print("=== 示例报告 ===")
    print(f"生成时间: {current_time}")
    print("\n系统状态:")
    print("- CPU: 正常")
    print("- 内存: 正常")
    print("- 磁盘: 正常")
    
    print("\n模拟任务进度:")
    for i in range(5):
        print(f"处理任务 {i+1}/5...")
        time.sleep(1)
    
    print("\n完成报告生成！")

if __name__ == "__main__":
    generate_report() 