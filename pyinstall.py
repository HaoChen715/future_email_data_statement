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
#     1. 调用 compile_so.py 将 src/future_email_data_statement 下全部业务模块
#        （含 __init__.py 与 generate_key / generate_password 等工具）就地编译为 .so;
#     2. 扫描当前 PDM 虚拟环境的第三方依赖, 生成 PyInstaller --collect-all 参数;
#     3. PyInstaller -D 打包 main.py（--exclude-module src, 业务模块以外部
#        .so 模块树形式随发布包部署, 不打入可执行程序）;
#     4. 组装发布目录: PyInstaller 产物 + 外部 src(纯 .so 模块树, 不含任何 .py)
#        + config 模板, 并打出 tar.gz 发布包。
#
# 【限制】发布包 src 目录内只允许存在 .so 文件:
#        - .so 编译失败或任一 .py 未编译出同名 .so 时, 打包直接中止;
#        - 组装后再次校验发布目录, 发现 .py 残留同样中止。
#
# 用法:
#     pdm run python pyinstall.py            # 完整流程(编译 .so -> 打包 -> 组装)
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
    """调用 compile_so.py 将业务模块就地编译为 .so（失败即中止打包）。"""
    print("🔧 1. 开始编译 src 下业务模块为 .so ...")
    result = subprocess.run(
        [sys.executable, os.path.join(BASE_DIR, "compile_so.py")],
        cwd=BASE_DIR,
    )
    if result.returncode != 0:
        print("❌ [限制] .so 编译失败, 发布包禁止携带 .py 源码, 打包中止。")
        print("   请确认编译机已安装 gcc 与 cython (pdm install -G dev)")
        sys.exit(1)
    print("✅ .so 编译完成")


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


def _has_so_sibling(dir_path, module_base):
    """判断目录中是否存在 module_base 模块编译出的 .so（含平台后缀版本）。"""
    prefix = f"{module_base}."
    for file in os.listdir(dir_path):
        if file == f"{module_base}.so":
            return True
        if file.startswith(prefix) and file.endswith(".so"):
            return True
    return False


def verify_so_complete():
    """校验 src 下每个 .py 均已编译出同名 .so, 返回缺失模块清单。"""
    missing = []
    for root, dirs, files in os.walk(SRC_PKG):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for file in files:
            if not file.endswith(".py"):
                continue
            if not _has_so_sibling(root, os.path.splitext(file)[0]):
                missing.append(os.path.relpath(os.path.join(root, file), SRC_PKG))
    return missing


def copy_src_tree(dest_root):
    """复制外部 src 模块树: 只允许携带 .so, 发布目录内不残留任何 .py。"""
    missing = verify_so_complete()
    if missing:
        print("❌ [限制] 以下 .py 模块未编译出 .so, 发布包禁止携带源码, 打包中止:")
        for mod in missing:
            print(f"   - {mod}")
        sys.exit(1)

    src_dest = os.path.join(dest_root, "src", "future_email_data_statement")
    os.makedirs(src_dest, exist_ok=True)

    so_count = 0
    for root, dirs, files in os.walk(SRC_PKG):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        rel_dir = os.path.relpath(root, SRC_PKG)
        target_dir = os.path.join(src_dest, rel_dir) if rel_dir != "." else src_dest
        os.makedirs(target_dir, exist_ok=True)
        for file in files:
            if file.endswith(".so"):
                shutil.copy2(os.path.join(root, file), os.path.join(target_dir, file))
                so_count += 1

    # 组装后二次校验: 发布目录 src 内不允许出现任何 .py
    py_left = [
        os.path.join(root, file)
        for root, _, files in os.walk(src_dest)
        for file in files
        if file.endswith(".py")
    ]
    if py_left:
        print("❌ [限制] 发布目录 src 内检出 .py 文件, 打包中止:")
        for f in py_left:
            print(f"   - {f}")
        sys.exit(1)

    print(f"✅ 外部 src 模块树组装完成: 共 {so_count} 个 .so, 0 个 .py")
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

    # 1. PyInstaller 产物(可执行程序 + _internal 运行库)
    for item in os.listdir(pyinstaller_output):
        src_item = os.path.join(pyinstaller_output, item)
        dst_item = os.path.join(DEPLOY_DIR, item)
        if os.path.isdir(src_item):
            shutil.copytree(src_item, dst_item)
        else:
            shutil.copy2(src_item, dst_item)

    # 1.1 certifi 证书复制到发布根目录: PyInstaller 6 的 --add-data 数据落在
    #     _internal 内, 而 main.py _setup_builtin_cert 优先读取程序根目录的
    #     cacert.pem(与 auto_down_email 项目一致), 此处显式补齐
    try:
        import certifi

        shutil.copy2(certifi.where(), os.path.join(DEPLOY_DIR, "cacert.pem"))
        print("✅ certifi cacert.pem 已复制到发布根目录")
    except Exception as e:
        print(f"⚠️ 未找到 certifi 或无法复制 cacert.pem: {e}")

    # 2. 外部 src 模块树(编译好的 .so 工具随包发布)
    copy_src_tree(DEPLOY_DIR)

    # 3. config 模板(真实凭据不入包, 部署时填写并生成 secret.key)
    deploy_config = os.path.join(DEPLOY_DIR, "config")
    shutil.copytree(CONFIG_TEMPLATE_DIR, deploy_config)

    print(f"✅ 发布目录组装完成: {DEPLOY_DIR}")


def main():
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
