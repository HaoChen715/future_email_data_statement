from cryptography.fernet import Fernet


class EncryptionTool:
    def __init__(self, key_file):
        self.key_file = key_file
        self.key = self.load_key()

    def generate_key(self):
        """生成并保存一个新的密钥。"""
        self.key = Fernet.generate_key()
        with open(self.key_file, "wb") as key_file:
            key_file.write(self.key)
        return self.key

    def load_key(self):
        """从文件加载密钥。"""
        return open(self.key_file, "rb").read()

    def encrypt_message(self, message: str) -> bytes:
        """加密消息。"""
        f = Fernet(self.key)
        encrypted_message = f.encrypt(message.encode())
        return encrypted_message

    def decrypt_message(self, encrypted_message) -> str:
        """解密消息。"""
        if isinstance(encrypted_message, str):
            encrypted_message = encrypted_message.encode("utf-8")
        f = Fernet(self.key)
        decrypted_message = f.decrypt(encrypted_message).decode("utf-8")
        return decrypted_message
