from pathlib import Path


class ParentPath:
    def __init__(self):
        pass

    def get_current_dir(self) -> Path:
        """向上查找包含 pyproject.toml 的目录，作为项目根目录。"""
        current_dir = Path(__file__).resolve().parent
        while not (current_dir / "pyproject.toml").exists():
            current_dir = current_dir.parent
        return current_dir
