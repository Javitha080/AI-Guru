import hashlib
import os
from pathlib import Path
import shutil
import time
from typing import Dict, List, Optional

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False

from deeptutor.services.path_service import get_path_service


class BackupManager:
    """AES-GCM encrypted local backup and restore for AI Guru databases."""

    BACKUP_EXTENSION = ".aiguru-backup"
    MAGIC_BYTES = b"AIGURU01"

    def _derive_key(self, password: str, salt: bytes) -> bytes:
        return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000, 32)

    def _simple_xor(self, data: bytes, key: bytes) -> bytes:
        """Fallback simple XOR encryption/decryption if cryptography isn't installed."""
        result = bytearray()
        key_len = len(key)
        for i, b in enumerate(data):
            result.append(b ^ key[i % key_len])
        return bytes(result)

    async def create_backup(self, password: str, backup_dir: Optional[Path] = None) -> Path:
        """Create an encrypted backup of the database."""
        path_service = get_path_service()
        db_path = path_service.user_dir / "chat_history.db"

        if not backup_dir:
            backup_dir = path_service.user_dir

        backup_dir.mkdir(parents=True, exist_ok=True)

        # 1. Read db file
        if not db_path.exists():
            raise FileNotFoundError(f"Database not found at {db_path}")

        with open(db_path, "rb") as f:
            db_data = f.read()

        # 2. Derive key
        salt = os.urandom(16)
        key = self._derive_key(password, salt)

        # 3. Generate nonce
        nonce = os.urandom(12)

        # 4 & 5. Encrypt and write
        if HAS_CRYPTOGRAPHY:
            aesgcm = AESGCM(key)
            ciphertext = aesgcm.encrypt(nonce, db_data, None)
            final_data = self.MAGIC_BYTES + salt + nonce + ciphertext
        else:
            # Fallback (no tag generated, but we append a fake 16-byte tag for size compatibility)
            ciphertext = self._simple_xor(db_data, key)
            fake_tag = b"\x00" * 16
            final_data = self.MAGIC_BYTES + salt + nonce + ciphertext + fake_tag

        # 6. Save with timestamp
        timestamp = int(time.time())
        backup_path = backup_dir / f"backup_{timestamp}{self.BACKUP_EXTENSION}"

        with open(backup_path, "wb") as f:
            f.write(final_data)

        return backup_path

    async def restore_backup(self, backup_path: Path, password: str) -> bool:
        """Restore from an encrypted backup."""
        if not backup_path.exists():
            raise FileNotFoundError("Backup file not found.")

        with open(backup_path, "rb") as f:
            data = f.read()

        # 1. Read and parse
        magic = data[:8]
        if magic != self.MAGIC_BYTES:
            raise ValueError("Invalid backup file: Incorrect magic bytes.")

        salt = data[8:24]
        nonce = data[24:36]

        # 2. Derive key
        key = self._derive_key(password, salt)

        # 3. Decrypt
        if HAS_CRYPTOGRAPHY:
            aesgcm = AESGCM(key)
            ciphertext_with_tag = data[36:]
            try:
                decrypted_data = aesgcm.decrypt(nonce, ciphertext_with_tag, None)
            except Exception as e:
                raise ValueError("Decryption failed. Incorrect password or corrupted file.") from e
        else:
            # Fallback
            ciphertext = data[36:-16]  # exclude fake tag
            decrypted_data = self._simple_xor(ciphertext, key)

        # 4. Backup current DB
        path_service = get_path_service()
        db_path = path_service.user_dir / "chat_history.db"
        if db_path.exists():
            bak_path = db_path.with_suffix(".db.bak")
            shutil.copy2(db_path, bak_path)

        # 5. Write decrypted data
        with open(db_path, "wb") as f:
            f.write(decrypted_data)

        return True

    async def list_backups(self, backup_dir: Optional[Path] = None) -> List[Dict]:
        """List available backup files with metadata."""
        if not backup_dir:
            backup_dir = get_path_service().user_dir

        if not backup_dir.exists():
            return []

        backups = []
        for file in backup_dir.glob(f"*{self.BACKUP_EXTENSION}"):
            stat = file.stat()
            backups.append(
                {"filename": file.name, "size": stat.st_size, "created_at": stat.st_ctime}
            )

        return sorted(backups, key=lambda x: x["created_at"], reverse=True)

    async def delete_backup(self, backup_path: Path) -> bool:
        """Delete a specific backup file."""
        if backup_path.exists() and backup_path.suffix == self.BACKUP_EXTENSION:
            backup_path.unlink()
            return True
        return False
