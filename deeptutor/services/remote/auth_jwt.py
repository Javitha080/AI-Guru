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
import json
import logging
import os
import re
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

# PIN hashing iterations. New hashes use OWASP-recommended 600k rounds and are
# self-describing ("v2$<iter>$<salt>$<hash>"); legacy hashes (bare "<salt>$<hash>")
# verify at 100k so existing PINs keep working until next change.
_PIN_ITERATIONS_LEGACY = 100_000
_PIN_ITERATIONS = 600_000

# Revocation rows older than this are purged lazily on the next revocation
# (refresh tokens cap out at 7 days, so anything older can never be checked).
_REVOKED_TTL_SECONDS = 8 * 24 * 3600


class JWTAuthService:
    ALGORITHM = "HS256"
    MAX_FAILED_ATTEMPTS = 5
    LOCKOUT_DURATION_SECONDS = 300.0  # 5 minutes

    _PIN_DIGITS_RE = re.compile(r"^\d{4,8}$")

    # Trivially guessable codes rejected at setup: pure runs, repeated digits,
    # and a small blocklist of the most common real-world PINs.
    _COMMON_PINS = {
        "1234", "4321", "0000", "2580", "1212", "1122", "1004", "2000",
        "6969", "1010", "12345", "123456", "654321", "111111", "123123",
    }

    @classmethod
    def validate_pin_format(cls, pin: str) -> None:
        """Reject non-digit or trivially weak Parent PINs (setup/change only)."""
        if not cls._PIN_DIGITS_RE.match(pin or ""):
            raise ValueError("Parent PIN must be 4-8 digits (numbers only).")
        if len(set(pin)) == 1:
            raise ValueError("PIN is too predictable: avoid repeating the same digit.")
        ascending = "".join(str((int(pin[0]) + i) % 10) for i in range(len(pin)))
        descending = "".join(str((int(pin[0]) - i) % 10) for i in range(len(pin)))
        if pin in (ascending, descending):
            raise ValueError("PIN is too predictable: avoid sequential digits.")
        if pin in cls._COMMON_PINS:
            raise ValueError("PIN is too common: choose something less obvious.")


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
            new_secret = secrets.token_hex(32)
            # ON CONFLICT DO NOTHING + re-select: two concurrent callers may
            # race here; both must converge on the SAME stored secret, or the
            # loser's freshly issued tokens would be signed by a dead key.
            await db.execute(
                "INSERT INTO settings (key, value, category, updated_at) VALUES ('jwt_secret', ?, 'security', ?)"
                " ON CONFLICT(key) DO NOTHING",
                (new_secret, time.time())
            )
            await db.commit()
            cursor = await db.execute("SELECT value FROM settings WHERE key = 'jwt_secret'")
            row = await cursor.fetchone()
            if row and row[0]:
                return str(row[0])
            return new_secret

    # --- Parent Passcode ("Ask Pass" PIN) Management ---

    @classmethod
    def _hash_pin(cls, pin: str, salt: bytes, iterations: int = _PIN_ITERATIONS) -> str:
        h = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, iterations, 32)
        return f"v2${iterations}${salt.hex()}${h.hex()}"

    @classmethod
    def _verify_pin_hash(cls, pin: str, stored_hash: str) -> bool:
        try:
            if stored_hash.startswith("v2$"):
                _, iter_hex, salt_hex, hash_hex = stored_hash.split("$")
                iterations = int(iter_hex)
            else:
                # Legacy format: "<salt>$<hash>" at 100k rounds.
                salt_hex, hash_hex = stored_hash.split("$")
                iterations = _PIN_ITERATIONS_LEGACY
            salt = bytes.fromhex(salt_hex)
            expected = bytes.fromhex(hash_hex)
            computed = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, iterations, 32)
            return hmac.compare_digest(expected, computed)
        except Exception:
            return False

    # --- PIN epoch (generation counter for token invalidation) ---------------

    @classmethod
    async def _get_pin_epoch(cls, db: aiosqlite.Connection, parent_id: str) -> int:
        cursor = await db.execute(
            "SELECT value FROM settings WHERE key = ?", (f"pin_epoch_{parent_id}",)
        )
        row = await cursor.fetchone()
        try:
            return int(row[0]) if row and row[0] else 0
        except (TypeError, ValueError):
            return 0

    @classmethod
    async def _current_pin_epoch(cls, parent_id: str) -> int:
        db_path = cls._get_db_path()
        try:
            async with aiosqlite.connect(db_path) as db:
                await ensure_kv_settings(db)
                return await cls._get_pin_epoch(db, parent_id)
        except Exception:  # noqa: BLE001 - epoch is an optimization, not a gate
            return 0

    # --- Lockout persistence (survives process restarts) ---------------------

    @classmethod
    async def _persist_lockout(cls, parent_id: str, failed_count: int, until: float) -> None:
        try:
            db_path = cls._get_db_path()
            payload = json.dumps({"failed": int(failed_count), "until": float(until)})
            async with aiosqlite.connect(db_path) as db:
                await ensure_kv_settings(db)
                await db.execute(
                    "INSERT OR REPLACE INTO settings (key, value, category, updated_at) VALUES (?, ?, 'security', ?)",
                    (f"lockout_{parent_id}", payload, time.time()),
                )
                await db.commit()
        except Exception as exc:  # noqa: BLE001 - best-effort durability
            logger.debug("Lockout persistence skipped for %s: %s", parent_id, exc)

    @classmethod
    async def _load_persisted_lockout(cls, parent_id: str) -> Optional[Tuple[int, float]]:
        try:
            db_path = cls._get_db_path()
            async with aiosqlite.connect(db_path) as db:
                await ensure_kv_settings(db)
                cursor = await db.execute(
                    "SELECT value FROM settings WHERE key = ?", (f"lockout_{parent_id}",)
                )
                row = await cursor.fetchone()
            if not row or not row[0]:
                return None
            data = json.loads(row[0])
            failed = max(0, int(data.get("failed", 0)))
            until = max(0.0, float(data.get("until", 0.0)))
            if until and until < time.time():
                # Expired lockout: keep the failure count only.
                return (failed % cls.MAX_FAILED_ATTEMPTS, 0.0)
            return (failed, until)
        except Exception:  # noqa: BLE001
            return None

    @classmethod
    async def _clear_persisted_lockout(cls, parent_id: str) -> None:
        try:
            db_path = cls._get_db_path()
            async with aiosqlite.connect(db_path) as db:
                await ensure_kv_settings(db)
                await db.execute("DELETE FROM settings WHERE key = ?", (f"lockout_{parent_id}",))
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Lockout clear skipped for %s: %s", parent_id, exc)

    @classmethod
    async def set_parent_pin(cls, pin: str, parent_id: str = "default") -> bool:
        """Hash and persist Parent PIN."""
        cls.validate_pin_format(pin)

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
            # Bump the PIN epoch: every outstanding access/refresh token for
            # this parent was minted under the old secret and is now invalid
            # (verify_token rejects epoch mismatches).
            epoch = await cls._get_pin_epoch(db, parent_id)
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value, category, updated_at) VALUES (?, ?, 'security', ?)",
                (f"pin_epoch_{parent_id}", str(epoch + 1), time.time())
            )
            await db.execute(
                "DELETE FROM settings WHERE key = ?", (f"lockout_{parent_id}",)
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
    async def _load_lockout_state(cls, parent_id: str) -> Tuple[int, float]:
        """In-memory lockout state, hydrated from the persisted row.

        Shared by the verify-PIN and change-PIN flows so brute-force state
        survives process restarts on both paths (previously only verify-PIN
        consulted the persisted row — restarting the app reset the
        change-PIN attempt counter).
        """
        failed_count, lockout_until = _PIN_ATTEMPT_TRACKER.get(parent_id, (0, 0.0))
        if lockout_until <= 0:
            # Memory tracker empty (e.g. after a restart): fall back to the
            # persisted lockout so brute-force state survives process cycles.
            persisted = await cls._load_persisted_lockout(parent_id)
            if persisted is not None:
                failed_count, lockout_until = persisted
                _PIN_ATTEMPT_TRACKER[parent_id] = persisted
        return failed_count, lockout_until

    @classmethod
    async def verify_parent_pin(
        cls,
        pin: str,
        parent_id: str = "default",
        device_info: Optional[str] = None
    ) -> Dict[str, Any]:
        """Verify Parent PIN with anti-brute-force rate limiting. Returns access token on success."""
        now = time.time()
        failed_count, lockout_until = await cls._load_lockout_state(parent_id)

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
                await cls._persist_lockout(parent_id, failed_count, lockout_until)
                raise ValueError("Too many failed attempts. Locked out for 5 minutes.")
            else:
                _PIN_ATTEMPT_TRACKER[parent_id] = (failed_count, 0.0)
                await cls._persist_lockout(parent_id, failed_count, 0.0)
                remaining_tries = cls.MAX_FAILED_ATTEMPTS - failed_count
                raise ValueError(f"Invalid PIN. {remaining_tries} attempts remaining.")

        # Success: reset rate limiting and issue JWT
        _PIN_ATTEMPT_TRACKER.pop(parent_id, None)
        await cls._clear_persisted_lockout(parent_id)
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
        """Change the Parent PIN only after verifying the current one.

        Wrong-current-PIN attempts count toward the same brute-force budget
        as verify-PIN attempts (5 strikes → 5-minute lockout, persisted
        across restarts).
        """
        key = f"parent_pin_{parent_id}"
        db_path = cls._get_db_path()
        async with aiosqlite.connect(db_path) as db:
            await ensure_kv_settings(db)
            cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = await cursor.fetchone()

        if row and row[0]:
            now = time.time()
            attempts, lockout_until = await cls._load_lockout_state(parent_id)
            if now < lockout_until:
                remaining = int(lockout_until - now)
                raise ValueError(f"Too many failed attempts. Try again in {remaining} seconds.")
            if not cls._verify_pin_hash(current_pin, row[0]):
                attempts += 1
                if attempts >= cls.MAX_FAILED_ATTEMPTS:
                    lockout_until = now + cls.LOCKOUT_DURATION_SECONDS
                    _PIN_ATTEMPT_TRACKER[parent_id] = (attempts, lockout_until)
                    await cls._persist_lockout(parent_id, attempts, lockout_until)
                    raise ValueError("Too many failed attempts. Locked out for 5 minutes.")
                _PIN_ATTEMPT_TRACKER[parent_id] = (attempts, 0.0)
                await cls._persist_lockout(parent_id, attempts, 0.0)
                remaining_tries = cls.MAX_FAILED_ATTEMPTS - attempts
                raise ValueError(f"Current PIN is incorrect. {remaining_tries} attempts remaining.")
        return await cls.set_parent_pin(pin, parent_id)

    # --- JWT Token Generation & Verification ---

    @classmethod
    async def create_access_token(cls, parent_id: str, device_info: Optional[str] = None) -> str:
        secret = await cls.get_secret_key()
        epoch = await cls._current_pin_epoch(parent_id)
        now = int(time.time())
        payload = {
            "sub": parent_id,
            "role": "parent",
            "type": "access",
            "device": device_info,
            "epoch": epoch,
            "iat": now,
            "exp": now + 15 * 60,  # 15 mins
            "jti": uuid.uuid4().hex,
        }
        return jwt.encode(payload, secret, algorithm=cls.ALGORITHM)

    @classmethod
    async def create_refresh_token(cls, parent_id: str) -> str:
        secret = await cls.get_secret_key()
        epoch = await cls._current_pin_epoch(parent_id)
        now = int(time.time())
        payload = {
            "sub": parent_id,
            "role": "parent",
            "type": "refresh",
            "epoch": epoch,
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
        except _JWT_DECODE_ERRORS as e:
            raise ValueError(f"Invalid token: {str(e)}")
        if payload.get("role") == "parent":
            # Tokens minted before a PIN set/change carry an older epoch and
            # are rejected even though their signature is still valid.
            current_epoch = await cls._current_pin_epoch(str(payload.get("sub", "default")))
            if int(payload.get("epoch", 0)) != current_epoch:
                raise ValueError("Token superseded by a PIN change")
        # Check revocation
        db_path = cls._get_db_path()
        async with aiosqlite.connect(db_path) as db:
            await ensure_kv_settings(db)
            cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (f"revoked_{payload['jti']}",))
            if await cursor.fetchone():
                raise ValueError("Token revoked")
        return payload

    @classmethod
    async def verify_parent_access_token(cls, token: str) -> dict:
        """Verify a parent *access* token for live-supervision entry points.

        Stricter than :meth:`verify_token`: refresh tokens are rejected even
        though their signature/epoch are valid, so a leaked long-lived
        refresh token can never open a live video stream or snapshot poll.
        Raises ``ValueError`` on any failure (callers map to 401/4001).
        """
        if not token:
            raise ValueError("Missing parent access token")
        payload = await cls.verify_token(token)
        if payload.get("role") != "parent" or payload.get("type") != "access":
            raise ValueError("Not a parent access token")
        return payload

    @classmethod
    async def refresh_access_token(cls, refresh_token: str) -> str:
        payload = await cls.verify_token(refresh_token)
        if payload.get("type") != "refresh":
            raise ValueError("Not a refresh token")
        return await cls.create_access_token(payload["sub"])

    @classmethod
    async def rotate_refresh_token(cls, refresh_token: str) -> Dict[str, Any]:
        """Exchange a refresh token for a NEW pair, revoking the presented one.

        Rotation limits the blast radius of a leaked refresh token: a replayed
        token fails revocation-check and forces a fresh PIN login.
        """
        payload = await cls.verify_token(refresh_token)
        if payload.get("type") != "refresh":
            raise ValueError("Not a refresh token")
        parent_id = str(payload.get("sub", "default"))
        new_access = await cls.create_access_token(parent_id)
        new_refresh = await cls.create_refresh_token(parent_id)
        await cls.revoke_token(payload["jti"])
        return {
            "access_token": new_access,
            "refresh_token": new_refresh,
            "token_type": "bearer",
            "expires_in": 900,
        }

    @classmethod
    async def revoke_refresh_token(cls, refresh_token: str) -> bool:
        """Best-effort revoke of a presented refresh token (logout)."""
        try:
            payload = await cls.verify_token(refresh_token)
        except ValueError:
            return False
        if payload.get("type") != "refresh":
            return False
        await cls.revoke_token(payload["jti"])
        return True

    @classmethod
    async def revoke_token(cls, token_id: str):
        db_path = cls._get_db_path()
        async with aiosqlite.connect(db_path) as db:
            await ensure_kv_settings(db)
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value, category, updated_at) VALUES (?, ?, 'security', ?)",
                (f"revoked_{token_id}", str(int(time.time())), time.time())
            )
            # Lazy purge: revocation rows past any possible token lifetime are
            # dead weight — without this the settings table grows forever.
            cutoff = time.time() - _REVOKED_TTL_SECONDS
            await db.execute(
                "DELETE FROM settings WHERE key LIKE 'revoked\\_%' ESCAPE '\\'"
                " AND length(value) <= 12 AND CAST(value AS REAL) < ?",
                (cutoff,),
            )
            await db.commit()
