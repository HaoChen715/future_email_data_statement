import os
from src.future_email_data_statement.common.encrpty import EncryptionTool
from src.future_email_data_statement.common.get_parent_path import ParentPath

current_dir = ParentPath().get_current_dir()
key_file_path = os.path.join(current_dir, "config/secret.key")
if not os.path.exists(key_file_path):
    with open(key_file_path, "w") as file:
        file.write("")
encrpty = EncryptionTool(key_file_path)
encrpty.generate_key()

print("秘钥已生成")
