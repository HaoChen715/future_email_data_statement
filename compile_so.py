import os
import glob
import shutil
import subprocess
import sys


def compile_all_py_to_so():
    """
    将 src/future_email_data_statement 下的全部业务模块就地编译为 .so。

    思路沿用 future_data_download_and_clean_to_statement 项目的 compile_so.py：
        - 每个 .py（含 __init__.py, 保证发布包 src 目录内不残留任何 .py）在独立
          子进程中使用 Cython 编译（-i 就地生成 .so，-3 采用 Python 3 语法，
          -X always_allow_keywords 允许关键字参数调用）；
        - 编译后清理中间产物 .c 文件与根目录 build 缓存。

    生产部署形态：main.py + config/ + src 下纯 .so 模块树（无 pyproject.toml），
    各模块内通过 ParentPath 以 config/info.ini 定位项目根目录。
    """
    # 1. 递归查找目标文件（包含 __init__.py, 全量编译后 src 内不留 .py）
    target_pattern = os.path.join("src", "future_email_data_statement", "**", "*.py")
    py_files = sorted(glob.glob(target_pattern, recursive=True))

    if not py_files:
        print("💡 未找到需要编译的 .py 文件。")
        return

    print(f"🚀 发现 {len(py_files)} 个待编译文件。开始启动「独立进程级」原生编译...\n")

    success_count = 0
    fail_files = []

    # 2. 遍历文件，启动隔离的独立进程进行编译
    for idx, f in enumerate(py_files, 1):
        print(f"[{idx}/{len(py_files)}] 正在就地编译: {f}")

        # 构建 Cython 原生 CLI 命令
        # -i : --inplace，指示在 .py 的同级目录下直接生成 .so
        # -3 : 采用 Python 3 语法解析
        # -X : 传递编译指令（允许关键字参数调用）
        cmd = [
            sys.executable,
            "-m",
            "Cython.Build.Cythonize",
            "-i",
            "-3",
            "-X",
            "always_allow_keywords=True",
            f,
        ]

        try:
            # 启动完全隔离的子进程，彻底断绝全局状态和路径错乱
            res = subprocess.run(cmd, capture_output=True, text=True)

            if res.returncode == 0:
                print(f"   ✓ 成功生成二进制文件")
                success_count += 1

                # 3. 编译成功后，顺手清理掉同级目录下生成的临时 .c 文件
                c_file = os.path.splitext(f)[0] + ".c"
                if os.path.exists(c_file):
                    os.remove(c_file)
            else:
                print(f"   ✕ 编译失败: {f}")
                print(f"   [错误日志]:\n{res.stderr}")
                fail_files.append(f)

        except Exception as e:
            print(f"   ✕ 脚本执行异常: {str(e)}")
            fail_files.append(f)

    # 4. 统一清理项目根目录下的临时 build 文件夹
    if os.path.exists("build"):
        shutil.rmtree("build")
        print("\n🧹 已自动清理根目录 build 临时缓存。")

    # 5. 打印最终可视化报告
    print("\n" + "=" * 25 + " 编译报告 " + "=" * 25)
    print(f"📊 总计文件: {len(py_files)}")
    print(f"✅ 编译成功: {success_count}")
    print(f"❌ 编译失败: {len(fail_files)}")
    if fail_files:
        print(f"\n以下为失败文件详情，可单独排查其语法兼容性:")
        for ff in fail_files:
            print(f"  - {ff}")
    print("=" * 60)


if __name__ == "__main__":
    compile_all_py_to_so()
