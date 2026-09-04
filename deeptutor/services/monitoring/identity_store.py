"""Encrypted persistence for the enrolled student identity baseline.

The baseline used to live only in ``FaceEngine._enrolled_embedding`` (process
memory): any backend restart silently dropped every browser-path session into
un-enrolled mode — ``verify_identity`` returned ``(True, 1.0)`` forever while
the client's localStorage still claimed "enrolled".

The vector is stored AES-encrypted (Fernet) in the kv ``settings`` table,
keyed from the app's own ``jwt_secret`` (never at rest in plaintext next to
the ciphertext). ``cryptography`` ships with the auth dependency
(python-jose[cryptography]); without it the store degrades to base64 with a
loud warning rather than silently pretending to be encrypted.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from typing import List, Optional, Tuple

import aiosqlite

logger = logging.getLogger(__name__)

IDENTITY_BASELINE_KEY = "identity_baseline_enrolled"
BASELINE_CATEGORY = "security"


def _fernet_from_secret(secret: str):
    try:
        from cryptography.fernet import Fernet

        key = hashlib.sha256(secret.encode("utf-8")).digest()
        return Fernet(base64.urlsafe_b64encode(key))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "cryptography unavailable (%s) — identity baseline stored WITHOUT encryption", exc
        )
        return None


async def _app_secret(db: aiosqlite.Connection) -> str:
    """Reuse the app's jwt_secret row (creating it when missing)."""
    from deeptutor.services.remote.auth_jwt import JWTAuthService

    return await JWTAuthService.get_secret_key()


async def save_baseline(
    db_path: str,
    embedding: List[float],
    identity_mode: str,
) -> bool:
    """Persist the enrolled vector (encrypted). Returns success."""
    import json
    import time

    try:
        payload = json.dumps({"embedding": list(embedding), "mode": identity_mode})
        encrypted = False
        async with aiosqlite.connect(db_path) as db:
            fernet = _fernet_from_secret(await _app_secret(db))
            if fernet is not None:
                stored = fernet.encrypt(payload.encode("utf-8")).decode("ascii")
                encrypted = True
            else:
                stored = base64.b64encode(payload.encode("utf-8")).decode("ascii")
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value, category, updated_at)"
                " VALUES (?, ?, ?, ?)",
                (
                    IDENTITY_BASELINE_KEY,
                    ("enc1:" if encrypted else "b64:") + stored,
                    BASELINE_CATEGORY,
                    time.time(),
                ),
            )
            await db.commit()
        return True
    except Exception as exc:  # noqa: BLE001 - persistence is best-effort
        logger.warning("Identity baseline persistence failed: %s", exc)
        return False


async def load_baseline(db_path: str) -> Optional[Tuple[List[float], str]]:
    """Return (embedding, identity_mode) or None when nothing is stored."""
    import json

    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "SELECT value FROM settings WHERE key = ?", (IDENTITY_BASELINE_KEY,)
            )
            row = await cursor.fetchone()
        if not row or not row[0]:
            return None
        raw = str(row[0])
        fernet = None
        if raw.startswith("enc1:"):
            fernet = _fernet_from_secret(await _app_secret_for_load(db_path))
            if fernet is None:
                logger.error("Encrypted identity baseline present but undecryptable")
                return None
            payload = fernet.decrypt(raw[5:].encode("ascii")).decode("utf-8")
        elif raw.startswith("b64:"):
            payload = base64.b64decode(raw[4:]).decode("utf-8")
        else:
            payload = raw
        data = json.loads(payload)
        embedding = [float(v) for v in data.get("embedding", [])]
        if not embedding:
            return None
        return embedding, str(data.get("mode", "geometric"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Identity baseline load failed: %s", exc)
        return None


async def _app_secret_for_load(db_path: str) -> str:
    import aiosqlite as _aio

    async with _aio.connect(db_path) as db:
        return await _app_secret(db)


async def clear_baseline(db_path: str) -> None:
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute("DELETE FROM settings WHERE key = ?", (IDENTITY_BASELINE_KEY,))
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Identity baseline clear failed: %s", exc)


async def has_baseline(db_path: str) -> bool:
    return (await load_baseline(db_path)) is not None


__all__ = [
    "IDENTITY_BASELINE_KEY",
    "save_baseline",
    "load_baseline",
    "clear_baseline",
    "has_baseline",
]
