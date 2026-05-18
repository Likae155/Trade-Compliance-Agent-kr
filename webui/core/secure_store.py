# core/secure_store.py
from cryptography.fernet import Fernet
import os

class LocalSecureStore:
    def __init__(self, key_file="secret.key", storage_dir="user_data"):
        self.storage_dir = storage_dir
        if not os.path.exists(storage_dir):
            os.makedirs(storage_dir)
        
        # 키 파일이 없으면 생성
        if not os.path.exists(key_file):
            key = Fernet.generate_key()
            with open(key_file, "wb") as f:
                f.write(key)
        else:
            with open(key_file, "rb") as f:
                key = f.read()
        
        self.cipher = Fernet(key)

    def save(self, filename, data, category="docs"):
        """category: 'docs' 또는 'reports'"""
        target_dir = os.path.join(self.storage_dir, category)
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)
            
        encrypted_data = self.cipher.encrypt(data.encode())
        with open(os.path.join(target_dir, f"{filename}.enc"), "wb") as f:
            f.write(encrypted_data)

    def load(self, filename, category="docs"):
        path = os.path.join(self.storage_dir, category, f"{filename}.enc")
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            encrypted_data = f.read()
        return self.cipher.decrypt(encrypted_data).decode()

    def wipe(self, filename, category="docs"):
        path = os.path.join(self.storage_dir, category, f"{filename}.enc")
        if os.path.exists(path):
            os.remove(path)
        
        # 문서 삭제 시 관련 리포트도 함께 삭제 시도
        if category == "docs":
            report_path = os.path.join(self.storage_dir, "reports", f"{filename}.enc")
            if os.path.exists(report_path):
                os.remove(report_path)

    def list_files(self, category="docs"):
        target_dir = os.path.join(self.storage_dir, category)
        if not os.path.exists(target_dir):
            return []
        return [f.replace(".enc", "") for f in os.listdir(target_dir) if f.endswith(".enc")]
