import os
from .encrpty import EncryptionTool
from .get_parent_path import ParentPath


def generate_password(plain_text: str = "") -> bytes:
    """
    使用 config/secret.key 加密明文密码/邮箱口令，输出密文。
    部署时运行本工具生成密文后填入 info.ini / email.json。

    Args:
        plain_text (str): 需要加密的明文，默认空串。

    Returns:
        bytes: 加密后的密文。
    """
    current_dir = ParentPath().get_current_dir()
    key_file_path = os.path.join(current_dir, "config/secret.key")

    encrpty = EncryptionTool(key_file_path)
    encrypted_message = encrpty.encrypt_message(message=plain_text)
    print("加密后信息: %s" % encrypted_message.decode())
    return encrypted_message


if __name__ == "__main__":
    import sys

    plain = sys.argv[1] if len(sys.argv) > 1 else ""
    generate_password(plain)
