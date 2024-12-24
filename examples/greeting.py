import sys

def greet(name="World"):
    print(f"Hello, {name}!")
    print("这是一个带参数的示例")
    print("您可以在运行时传入名字参数")
    print("例如: --name 张三")

if __name__ == "__main__":
    name = "World"
    if len(sys.argv) > 1:
        try:
            name_index = sys.argv.index("--name")
            name = sys.argv[name_index + 1]
        except (ValueError, IndexError):
            pass
    greet(name) 