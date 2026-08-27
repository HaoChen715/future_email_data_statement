from pathlib import Path


class ParentPath:
    """项目根目录定位工具。

    同时兼容两种部署形态（模块被 Cython 编译为 .so 后 __file__ 仍指向
    .so 文件所在目录，定位逻辑不变）：

        - 源码运行   : 根目录含 pyproject.toml（开发环境）
        - .so 生产部署: 根目录含 config/info.ini（打包环境无 pyproject.toml）
    """

    def __init__(self):
        pass

    def get_current_dir(self) -> Path:
        """向上查找项目根目录（含 pyproject.toml 或 config/info.ini）。"""
        current_dir = Path(__file__).resolve().parent
        while True:
            if (current_dir / "pyproject.toml").exists():
                return current_dir
            if (current_dir / "config" / "info.ini").is_file():
                return current_dir
            parent = current_dir.parent
            if parent == current_dir:
                # 已到文件系统根目录仍未找到，返回当前位置兜底
                return current_dir
            current_dir = parent
