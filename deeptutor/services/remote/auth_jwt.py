"""
AI Guru Remote JWT Authentication and Parent PIN ('Ask Pass') Security Service.
================================================================================

Handles:
- Short-lived JWT parent access tokens (15-min TTL) and refresh tokens.
- Parent Passcode (PIN) hashing with PBKDF2-HMAC-SHA256 and salt.
- Brute-force rate limiting and lockout (5 failed attempts -> 5 min lockout).
- Token revocation and audit logging.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time
from typing import Any, Dict, Optional, Tuple
import uuid

import aiosqlite

try:
    import jwt
    _JWT_DECODE_ERRORS: tuple = (jwt.PyJWTError,)
except ImportError:
    from jose import jwt
    _JWT_DECODE_ERRORS = (jwt.JWTError,)

from deeptutor.services.path_service import get_path_service
from deeptutor.services.remote.kv_settings import ensure_kv_settings

logger = logging.getLogger(__name__)

# In-memory rate limiting tracker for PIN verification: parent_id -> (failed_count, lockout_until)
_PIN_ATTEMPT_TRACKER: Dict[str, Tuple[int, float]] = {}


class JWTAuthService:
    ALGORITHM = "HS256"
    MAX_FAILED_ATTEMPTS = 5
    LOCKOUT_DURATION_SECONDS = 300.0  # 5 minutes

    @staticmethod
    def _get_db_path():
        return get_path_service().user_dir / "chat_history.db"

    @classmethod
    async def get_secret_key(cls) -> str:
        db_path = cls._get_db_path()
        async with aiosqlite.connect(db_path) as db:
            await ensure_kv_settings(db)
            cursor = await db.execute("SELECT value FROM settings WHERE key = 'jwt_secret'")
            row = await cursor.fetchone()
            if row and row[0]:
                return row[0]
            else:
                new_secret = secrets.token_hex(32)
                await db.execute(
                    "INSERT OR REPLACE INTO settings (key, value, category, updated_at) VALUES ('jwt_secret', ?, 'security', ?)",
                    (new_secret, time.time())
                )
                await db.commit()
                return new_secret

    # --- Parent Passcode ("Ask Pass" PIN) Management ---

    @classmethod
    def _hash_pin(cls, pin: str, salt: bytes) -> str:
        h = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, 100000, 32)
        return f"{salt.hex()}${h.hex()}"

    @classmethod
    def _verify_pin_hash(cls, pin: str, stored_hash: str) -> bool:
        try:
            salt_hex, hash_hex = stored_hash.split("$")
            salt = bytes.fromhex(salt_hex)
            expected = bytes.fromhex(hash_hex)
            computed = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, 100000, 32)
            return hmac.compare_digest(expected, computed)
        except Exception:
            return False

    @classmethod
    async def set_parent_pin(cls, pin: str, parent_id: str = "default") -> bool:
        """Hash and persist Parent PIN."""
        if len(pin) < 4:
            raise ValueError("Parent PIN must be at least 4 digits.")

        salt = os.urandom(16)
        hashed = cls._hash_pin(pin, salt)
        key = f"parent_pin_{parent_id}"

        db_path = cls._get_db_path()
        async with aiosqlite.connect(db_path) as db:
            await ensure_kv_settings(db)
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value, category, updated_at) VALUES (?, ?, 'parent_security', ?)",
                (key, hashed, time.time())
            )
            await db.commit()

        # Reset any failed attempts
        _PIN_ATTEMPT_TRACKER.pop(parent_id, None)
        logger.info("Parent PIN set successfully for parent %s", parent_id)
        return True

    @classmethod
    async def has_parent_pin(cls, parent_id: str = "default") -> bool:
        """Check if a Parent PIN has been configured."""
        key = f"parent_pin_{parent_id}"
        db_path = cls._get_db_path()
        try:
            async with aiosqlite.connect(db_path) as db:
                await ensure_kv_settings(db)
                cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
                row = await cursor.fetchone()
                return bool(row and row[0])
        except Exception:
            return False

    @classmethod
    async def verify_parent_pin(
        cls,
        pin: str,
        parent_id: str = "default",
        device_info: Optional[str] = None
    ) -> Dict[str, Any]:
        """Verify Parent PIN with anti-brute-force rate limiting. Returns access token on success."""
        now = time.time()
        failed_count, lockout_until = _PIN_ATTEMPT_TRACKER.get(parent_id, (0, 0.0))

        if now < lockout_until:
            remaining = int(lockout_until - now)
            raise ValueError(f"Too many failed attempts. Try again in {remaining} seconds.")

        key = f"parent_pin_{parent_id}"
        db_path = cls._get_db_path()
        async with aiosqlite.connect(db_path) as db:
            await ensure_kv_settings(db)
            cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = await cursor.fetchone()

        if not row or not row[0]:
            # No PIN configured yet: allow first-time setup or fallback
            raise ValueError("No Parent PIN configured. Please complete parental setup first.")

        stored_hash = row[0]
        if not cls._verify_pin_hash(pin, stored_hash):
            failed_count += 1
            if failed_count >= cls.MAX_FAILED_ATTEMPTS:
                lockout_until = now + cls.LOCKOUT_DURATION_SECONDS
                _PIN_ATTEMPT_TRACKER[parent_id] = (failed_count, lockout_until)
                raise ValueError("Too many failed attempts. Locked out for 5 minutes.")
            else:
                _PIN_ATTEMPT_TRACKER[parent_id] = (failed_count, 0.0)
                remaining_tries = cls.MAX_FAILED_ATTEMPTS - failed_count
                raise ValueError(f"Invalid PIN. {remaining_tries} attempts remaining.")

        # Success: reset rate limiting and issue JWT
        _PIN_ATTEMPT_TRACKER.pop(parent_id, None)
        token = await cls.create_access_token(parent_id, device_info)
        refresh_token = await cls.create_refresh_token(parent_id)

        return {
            "success": True,
            "access_token": token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": 900,  # 15 mins
            "parent_id": parent_id,
        }

    @classmethod
    async def change_parent_pin(cls, pin: str, current_pin: str, parent_id: str = "default") -> bool:
        """Change the Parent PIN only after verifying the current one."""
        key = f"parent_pin_{parent_id}"
        db_path = cls._get_db_path()
        async with aiosqlite.connect(db_path) as db:
            await ensure_kv_settings(db)
            cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = await cursor.fetchone()

        if row and row[0]:
            attempts, lockout_until = _PIN_ATTEMPT_TRACKER.get(parent_id, (0, 0.0))
            if time.time() < lockout_until:
                raise ValueError("Too many failed attempts. Locked out temporarily.")
            if not cls._verify_pin_hash(current_pin, row[0]):
                _PIN_ATTEMPT_TRACKER[parent_id] = (attempts + 1, 0.0)
                raise ValueError("Current PIN is incorrect.")
        return await cls.set_parent_pin(pin, parent_id)

    # --- JWT Token Generation & Verification ---

    @classmethod
    async def create_access_token(cls, parent_id: str, device_info: Optional[str] = None) -> str:
        secret = await cls.get_secret_key()
        now = int(time.time())
        payload = {
            "sub": parent_id,
            "role": "parent",
            "type": "access",
            "device": device_info,
            "iat": now,
            "exp": now + 15 * 60,  # 15 mins
            "jti": uuid.uuid4().hex,
        }
        return jwt.encode(payload, secret, algorithm=cls.ALGORITHM)

    @classmethod
    async def create_refresh_token(cls, parent_id: str) -> str:
        secret = await cls.get_secret_key()
        now = int(time.time())
        payload = {
            "sub": parent_id,
            "role": "parent",
            "type": "refresh",
            "iat": now,
            "exp": now + 7 * 24 * 60 * 60,  # 7 days
            "jti": uuid.uuid4().hex,
        }
        return jwt.encode(payload, secret, algorithm=cls.ALGORITHM)

    @classmethod
    async def verify_token(cls, token: str) -> dict:
        secret = await cls.get_secret_key()
        try:
            payload = jwt.decode(token, secret, algorithms=[cls.ALGORITHM])
            # Check revocation
            async with aiosqlite.connect(cls._get_db_path()) as db:
                await ensure_kv_settings(db)
                cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (f"revoked_{payload['jti']}",))
                if await cursor.fetchone():
                    raise ValueError("Token revoked")
            return payload
        except _JWT_DECODE_ERRORS as e:
            raise ValueError(f"Invalid token: {str(e)}")

    @classmethod
    async def refresh_access_token(cls, refresh_token: str) -> str:
        payload = await cls.verify_token(refresh_token)
        if payload.get("type") != "refresh":
            raise ValueError("Not a refresh token")
        return await cls.create_access_token(payload["sub"])

    @classmethod
    async def revoke_token(cls, token_id: str):
        async with aiosqlite.connect(cls._get_db_path()) as db:
            await ensure_kv_settings(db)
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value, category, updated_at) VALUES (?, ?, 'security', ?)",
                (f"revoked_{token_id}", str(int(time.time())), time.time())
            )
            await db.commit()
