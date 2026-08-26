import os
from pathlib import Path
from .encrpty import EncryptionTool

current_dir = Path(__file__).resolve().parent

while not (current_dir / "pyproject.toml").exists():
    current_dir = current_dir.parent
key_file_path = os.path.join(current_dir, "config/secret.key")
if not os.path.exists(key_file_path):
    with open(key_file_path, "w") as file:
        file.write("")
encrpty = EncryptionTool(key_file_path)
encrpty.generate_key()

print("秘钥已生成")
