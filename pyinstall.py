import os
import shutil
import subprocess
import sys
import tarfile
from importlib.metadata import distributions

# ============================================================
# 自动化打包程序（参考 future_data_download_and_clean_to_statement 项目的 pyinstall.py）
#
# 整体流程:
#     1. 调用 compile_so.py 将 src/future_email_data_statement 下业务模块
#        （含 generate_key / generate_password 等工具）就地编译为 .so;
#     2. 扫描当前 PDM 虚拟环境的第三方依赖, 生成 PyInstaller --collect-all 参数;
#     3. PyInstaller -D 打包 main.py（--exclude-module src, 业务模块以外部
#        .so 模块树形式随发布包部署, 不打入可执行程序）;
#     4. 组装发布目录: PyInstaller 产物 + 外部 src(.so 模块树, 去除 .py 源码)
#        + config 模板, 并打出 tar.gz 发布包。
#
# 用法:
#     pdm run python pyinstall.py            # 完整流程(先编译 .so 再打包)
#     pdm run python pyinstall.py --skip-compile  # 跳过 .so 编译(开发机无 gcc 时调试用,
#                                                  # 发布包将以 .py 源码形式携带, 仅限内部使用)
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_NAME = "future_email_data_statement"
SRC_PKG = os.path.join(BASE_DIR, "src", "future_email_data_statement")
CONFIG_TEMPLATE_DIR = os.path.join(BASE_DIR, "config_template")
DIST_DIR = os.path.join(BASE_DIR, "dist")
DEPLOY_DIR = os.path.join(BASE_DIR, f"{APP_NAME}_deploy")
TREE_TAR = os.path.join(BASE_DIR, "future_email_data_statement_tree.tar.gz")
CONFIG_TEMPLATE_TAR = os.path.join(
    BASE_DIR, "future_email_data_statement_config_template.tar.gz"
)

# 打包工具自身与系统基础包, 排除后防止体积无意义膨胀
EXCLUDE_PKGS = {
    "pyinstaller",
    "pyinstaller-hooks-contrib",
    "pdm",
    "setuptools",
    "pip",
    "wheel",
    "cython",
}

# PyInstaller 遗漏的标准库子模块补丁
MANUAL_HIDDEN_IMPORTS = [
    "logging.handlers",
]


def compile_so():
    """调用 compile_so.py 将业务模块就地编译为 .so。"""
    print("🔧 1. 开始编译 src 下业务模块为 .so ...")
    result = subprocess.run(
        [sys.executable, os.path.join(BASE_DIR, "compile_so.py")],
        cwd=BASE_DIR,
    )
    if result.returncode != 0:
        print("⚠️ .so 编译失败: 发布包将回退携带 .py 源码(请确认生产编译机已安装 gcc)")
        return False
    print("✅ .so 编译完成")
    return True


def collect_third_party_args():
    """扫描当前虚拟环境第三方包, 生成 PyInstaller --collect-all 参数。"""
    print("🔍 2. 开始全量扫描 PDM 虚拟环境中的第三方库核心资产...")

    collect_commands = []
    for dist in distributions():
        pkg_name = dist.metadata["Name"].lower()
        if pkg_name in EXCLUDE_PKGS:
            continue
        # 读取元数据中的顶级导入目录
        top_level = dist.read_text("top_level.txt")
        if top_level:
            for line in top_level.splitlines():
                import_name = line.strip()
                if import_name and not import_name.startswith("_"):
                    collect_commands.append(f"--collect-all={import_name}")
        else:
            import_name = dist.metadata["Name"].replace("-", "_")
            collect_commands.append(f"--collect-all={import_name}")

    collect_commands = list(sorted(set(collect_commands)))
    print(f"📦 成功提取到 {len(collect_commands)} 个第三方依赖。")
    return collect_commands


def build_pyinstaller(collect_commands):
    """执行 PyInstaller 打包 main.py（排除 src, 业务模块外部部署）。"""
    print("🚀 3. 开始执行 PyInstaller 打包...")

    base_cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "-D",
        "--clean",
        "-y",
        "--exclude-module",
        "src",
        "-n",
        APP_NAME,
        "main.py",
    ]

    # certifi 证书内置: 保证 SSL 请求(IMAP/数据库)不受服务器证书配置影响
    try:
        import certifi

        cert_path = certifi.where()
        base_cmd.append(f"--add-data={cert_path}:.")
    except Exception as e:
        print(f"⚠️ [警告] 未找到 certifi 包或无法定位 cacert.pem: {e}")

    full_cmd = (
        base_cmd
        + collect_commands
        + [f"--hidden-import={mod}" for mod in MANUAL_HIDDEN_IMPORTS]
    )

    result = subprocess.run(full_cmd, cwd=BASE_DIR)
    if result.returncode != 0:
        print(f"\n❌ [失败] PyInstaller 运行中途出错, 退出码: {result.returncode}")
        sys.exit(1)
    print("✅ PyInstaller 打包完成")


def copy_src_tree(dest_root):
    """复制外部 src 模块树: 优先携带 .so（去除 .py 源码）, 未编译成功则保留 .py。"""
    src_dest = os.path.join(dest_root, "src", "future_email_data_statement")
    os.makedirs(src_dest, exist_ok=True)

    so_count = 0
    py_count = 0
    for root, dirs, files in os.walk(SRC_PKG):
        # 跳过字节码缓存
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        rel_dir = os.path.relpath(root, SRC_PKG)
        target_dir = os.path.join(src_dest, rel_dir) if rel_dir != "." else src_dest
        os.makedirs(target_dir, exist_ok=True)

        for file in files:
            if file.endswith(".c"):
                continue
            src_file = os.path.join(root, file)
            if file == "__init__.py":
                shutil.copy2(src_file, os.path.join(target_dir, file))
                continue
            if file.endswith(".so"):
                shutil.copy2(src_file, os.path.join(target_dir, file))
                so_count += 1
            elif file.endswith(".py"):
                # .so 存在时丢弃同名 .py(源码保护); 编译失败时才携带 .py
                so_sibling = os.path.splitext(src_file)[0] + ".so"
                if not os.path.exists(so_sibling):
                    shutil.copy2(src_file, os.path.join(target_dir, file))
                    py_count += 1

    if py_count:
        print(
            f"⚠️ 发布包携带了 {py_count} 个 .py 源码文件(未编译成功), 仅限内部测试使用"
        )
    else:
        print(f"✅ 外部 src 模块树组装完成: {so_count} 个 .so, 无 .py 源码")
    return src_dest


def make_tar(output_path, source_dir):
    """将目录打成 tar.gz 发布包。"""
    if os.path.exists(output_path):
        os.remove(output_path)
    with tarfile.open(output_path, "w:gz") as tar:
        tar.add(source_dir, arcname=os.path.basename(source_dir))
    print(f"📦 已生成发布包: {output_path} ({os.path.getsize(output_path) / 1024 / 1024:.1f} MB)")


def assemble_deploy_dir():
    """组装最终发布目录: PyInstaller 产物 + 外部 src + config 模板。"""
    print("🧩 4. 组装发布目录...")
    if os.path.exists(DEPLOY_DIR):
        shutil.rmtree(DEPLOY_DIR)
    os.makedirs(DEPLOY_DIR)

    pyinstaller_output = os.path.join(DIST_DIR, APP_NAME)
    if not os.path.exists(pyinstaller_output):
        print(f"❌ [失败] 未找到 PyInstaller 产物: {pyinstaller_output}")
        sys.exit(1)

    # 1. PyInstaller 产物(可执行程序 + _internal 运行库 + cacert.pem)
    for item in os.listdir(pyinstaller_output):
        src_item = os.path.join(pyinstaller_output, item)
        dst_item = os.path.join(DEPLOY_DIR, item)
        if os.path.isdir(src_item):
            shutil.copytree(src_item, dst_item)
        else:
            shutil.copy2(src_item, dst_item)

    # 2. 外部 src 模块树(编译好的 .so 工具随包发布)
    copy_src_tree(DEPLOY_DIR)

    # 3. config 模板(真实凭据不入包, 部署时填写并生成 secret.key)
    deploy_config = os.path.join(DEPLOY_DIR, "config")
    shutil.copytree(CONFIG_TEMPLATE_DIR, deploy_config)

    print(f"✅ 发布目录组装完成: {DEPLOY_DIR}")


def main():
    skip_compile = "--skip-compile" in sys.argv

    if skip_compile:
        print("⚠️ 已跳过 .so 编译(仅限开发调试, 生产发布必须携带 --skip-compile 之外的完整流程)")
    else:
        compile_so()

    collect_commands = collect_third_party_args()
    build_pyinstaller(collect_commands)
    assemble_deploy_dir()

    # 发布包: 完整部署目录 + 独立 config 模板包
    make_tar(TREE_TAR, DEPLOY_DIR)
    make_tar(CONFIG_TEMPLATE_TAR, CONFIG_TEMPLATE_DIR)

    print("\n" + "=" * 25 + " 打包报告 " + "=" * 25)
    print(f"📦 发布包: {TREE_TAR}")
    print(f"📦 配置模板包: {CONFIG_TEMPLATE_TAR}")
    print("部署形态: 可执行程序 + _internal + 外部 src(.so) + config 模板")
    print("部署后运行方式: ./future_email_data_statement yyyymmdd [today|last] [steps...]")
    print("=" * 60)


if __name__ == "__main__":
    main()
