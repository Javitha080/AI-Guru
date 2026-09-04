"""
AI Guru Encrypted Video & Snapshot Vault.
=========================================

AES-256-GCM *envelope-encrypted* local storage for study-session incident
snapshots and short frame clips. The local monitoring pipeline stages raw
frames only inside this user's private ``pending/`` folder; they are sealed
into ``.vault`` blobs as soon as a Parent Passcode is available. Only a
parent holding the passcode can decrypt.

Format ``GURUVAULT02`` (envelope layout, little parsing surface)::

    magic(11) | salt(16) | iterations(u32 BE) | wrap_nonce(12)
    | wrapped_len(u32 BE) | verifier(16) | wrapped_key(N)
    | data_nonce(12) | AESGCM(ciphertext)

* KEK      = PBKDF2-HMAC-SHA256(pin, salt, iterations=600_000, 32 bytes)
* verifier = HMAC-SHA256(KEK, b"aiguru-vault-v2")[:16]  -> wrong-PIN detection
  without attempting decryption
* content  = random 32-byte key per file, AES-GCM-wrapped under the KEK

Legacy ``GURUVAULT01`` blobs (direct PBKDF2-100k key) remain readable when
the ``cryptography`` package is installed.  The old XOR fallback was removed:
without ``cryptography`` the vault refuses to operate (fail closed).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import re
import struct
import time
from typing import Any, Dict, List, Optional

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    HAS_CRYPTOGRAPHY = True
except ImportError:  # pragma: no cover - exercised via guard below
    HAS_CRYPTOGRAPHY = False

from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)

_MAGIC_V2 = b"GURUVAULT02"
_VERIFIER_INFO = b"aiguru-vault-v2"
_DEFAULT_ITERATIONS = 600_000
_FRAMES_MAGIC = b"GURUFRAMES01"
# Legacy names: {session_id}_{epoch_seconds}_{EVENT_TYPE} — sid/evt may contain underscores.
_VAULT_NAME_RE = re.compile(r"^(?P<sid>.+)_(?P<ts>\d{9,})_(?P<evt>.+)$")
# Current names: {session_id}_{epoch_ms}_{rand8}_{EVENT_TYPE} (unique per item).
_VAULT_NAME_RE_V2 = re.compile(r"^(?P<sid>.+)_(?P<ts>\d{10,})_(?P<rand>[0-9a-f]{8})_(?P<evt>.+)$")


def _unique_stem(session_id: str, event_type: str) -> tuple[str, int]:
    """Collision-free pending stem + ms timestamp.

    The old ``{session}_{epoch_seconds}_{event}`` stem overwrote itself when
    two incidents shared a second and event type — silent evidence loss.
    Millis + 8 random hex digits make collisions infeasible.
    """
    ts_ms = int(time.time() * 1000)
    rand = os.urandom(4).hex()
    return f"{session_id}_{ts_ms}_{rand}_{event_type}", ts_ms


class VideoVaultManager:
    """Manages encrypted on-device storage of session incident snapshots and clips."""

    VAULT_DIR_NAME = "video_vault"
    PENDING_DIR_NAME = "pending"
    MAGIC_HEADER = _MAGIC_V2

    # ------------------------------------------------------------------ dirs

    @classmethod
    def get_vault_dir(cls) -> Path:
        vault_dir = get_path_service().user_dir / cls.VAULT_DIR_NAME
        vault_dir.mkdir(parents=True, exist_ok=True)
        return vault_dir

    @classmethod
    def get_pending_dir(cls) -> Path:
        pending_dir = cls.get_vault_dir() / cls.PENDING_DIR_NAME
        pending_dir.mkdir(parents=True, exist_ok=True)
        return pending_dir

    @classmethod
    def count_pending(cls) -> int:
        """Staged-but-unsealed items awaiting a parent PIN.

        Only counts metas that still have their sibling payload (`.jpg` or
        `.framesbin`) — orphan metas from interrupted writes are ignored
        (and cleaned on the next seal pass).
        """
        try:
            pending_dir = cls.get_pending_dir()
            count = 0
            for meta_path in pending_dir.glob("*.meta.json"):
                stem = meta_path.name[: -len(".meta.json")]
                if ((pending_dir / f"{stem}.jpg").exists()
                        or (pending_dir / f"{stem}.framesbin").exists()):
                    count += 1
            return count
        except OSError:
            return 0

    # ----------------------------------------------------------------- crypto

    @staticmethod
    def _require_crypto() -> None:
        if not HAS_CRYPTOGRAPHY:
            raise RuntimeError(
                "The 'cryptography' package is required for the encrypted vault. "
                "Install it with: pip install cryptography"
            )

    @staticmethod
    def _derive_kek(parent_pin: str, salt: bytes, iterations: int) -> bytes:
        return hashlib.pbkdf2_hmac("sha256", parent_pin.encode("utf-8"), salt, iterations, 32)

    @staticmethod
    def _verifier_for_kek(kek: bytes) -> bytes:
        return hmac.new(kek, _VERIFIER_INFO, hashlib.sha256).digest()[:16]

    @classmethod
    def _seal_payload(cls, payload: bytes, parent_pin: str) -> bytes:
        """Envelope-encrypt an arbitrary payload under the parent PIN (v2 format)."""
        cls._require_crypto()
        salt = os.urandom(16)
        wrap_nonce = os.urandom(12)
        data_nonce = os.urandom(12)
        kek = cls._derive_kek(parent_pin, salt, _DEFAULT_ITERATIONS)

        content_key = os.urandom(32)
        aesgcm_wrap = AESGCM(kek)
        wrapped_key = aesgcm_wrap.encrypt(wrap_nonce, content_key, None)

        aesgcm_data = AESGCM(content_key)
        ciphertext = aesgcm_data.encrypt(data_nonce, payload, None)

        blob = (
            _MAGIC_V2
            + salt
            + struct.pack(">I", _DEFAULT_ITERATIONS)
            + wrap_nonce
            + struct.pack(">I", len(wrapped_key))
            + cls._verifier_for_kek(kek)
            + wrapped_key
            + data_nonce
            + ciphertext
        )
        return blob

    # ------------------------------------------------------- sealed writers

    @classmethod
    async def save_encrypted_snapshot(
        cls,
        session_id: str,
        student_id: str,
        parent_pin: str,
        image_bytes: bytes,
        event_type: str = "INCIDENT_SNAPSHOT",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Encrypt (v2 envelope) and store one incident snapshot on local disk."""
        meta = dict(metadata or {})
        meta.setdefault("kind", "snapshot")
        meta.setdefault("student_id", student_id)
        meta_json = json.dumps(meta).encode("utf-8")
        payload = len(meta_json).to_bytes(4, "big") + meta_json + image_bytes

        blob = cls._seal_payload(payload, parent_pin)
        clip_id = f"{session_id}_{int(time.time())}_{event_type}.vault"
        (cls.get_vault_dir() / clip_id).write_bytes(blob)
        logger.info("Encrypted snapshot sealed into local vault: %s", clip_id)
        return clip_id

    # ------------------------------------------------------- pending staging

    @classmethod
    async def save_pending_snapshot(
        cls,
        session_id: str,
        event_type: str,
        jpeg_bytes: bytes,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Stage a raw JPEG in the private pending folder until a PIN seals it."""
        stem, ts_ms = _unique_stem(session_id, event_type)
        base = cls.get_pending_dir() / stem
        base.with_suffix(".jpg").write_bytes(jpeg_bytes)
        base.with_suffix(".meta.json").write_text(
            json.dumps({"kind": "snapshot", "session_id": session_id,
                        "event_type": event_type, "created_at": ts_ms / 1000.0,
                        "metadata": metadata or {}}),
            encoding="utf-8",
        )
        return stem

    @classmethod
    async def save_pending_clip(
        cls,
        session_id: str,
        event_type: str,
        frames: List[bytes],
        fps: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Stage a short frame sequence (length-prefixed blob) pending sealing."""
        if not frames:
            raise ValueError("No frames provided for clip")
        buf = bytearray(_FRAMES_MAGIC)
        buf += struct.pack(">I", len(frames))
        for frame in frames:
            buf += struct.pack(">I", len(frame)) + frame

        stem, ts_ms = _unique_stem(session_id, event_type)
        base = cls.get_pending_dir() / stem
        base.with_suffix(".framesbin").write_bytes(bytes(buf))
        base.with_suffix(".meta.json").write_text(
            json.dumps({"kind": "clip", "session_id": session_id,
                        "event_type": event_type, "created_at": ts_ms / 1000.0,
                        "fps": fps, "frame_count": len(frames),
                        "metadata": metadata or {}}),
            encoding="utf-8",
        )
        return stem

    @classmethod
    async def seal_pending(cls, parent_pin: str) -> int:
        """Encrypt every pending item with the parent PIN and delete raw copies.

        Sealed names carry millis + random segments so two pendings from the
        same second can never overwrite each other. Orphan metas (payload
        missing after an interrupted write) are removed and counted
        separately. Returns the sealed count (failed count goes to the log
        and the audit trail via the router).
        """
        cls._require_crypto()
        pending_dir = cls.get_pending_dir()
        sealed = 0
        failed = 0
        for meta_path in sorted(pending_dir.glob("*.meta.json")):
            stem = meta_path.name[: -len(".meta.json")]
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                kind = meta.get("kind", "snapshot")
                if kind == "clip":
                    raw_path = pending_dir / f"{stem}.framesbin"
                else:
                    kind = "snapshot"
                    raw_path = pending_dir / f"{stem}.jpg"
                if not raw_path.exists():
                    # Orphan meta from an interrupted staging write: drop it
                    # so pending_count stops reporting phantom captures.
                    logger.warning("Dropping orphan vault meta %s (no payload)", stem)
                    meta_path.unlink(missing_ok=True)
                    failed += 1
                    continue
                raw = raw_path.read_bytes()
                if kind == "clip":
                    inner_meta = {
                        "kind": "clip",
                        "fps": meta.get("fps", 5.0),
                        "frame_count": meta.get("frame_count"),
                        **(meta.get("metadata") or {}),
                    }
                else:
                    inner_meta = {"kind": "snapshot", **(meta.get("metadata") or {})}

                meta_json = json.dumps(inner_meta).encode("utf-8")
                payload = len(meta_json).to_bytes(4, "big") + meta_json + raw
                blob = cls._seal_payload(payload, parent_pin)

                out_stem, _ = _unique_stem(
                    str(meta.get("session_id", "session")),
                    str(meta.get("event_type", "INCIDENT")),
                )
                (cls.get_vault_dir() / f"{out_stem}.vault").write_bytes(blob)

                meta_path.unlink(missing_ok=True)
                raw_path.unlink(missing_ok=True)
                sealed += 1
            except Exception as exc:  # noqa: BLE001 - keep sealing remaining items
                logger.warning("Failed to seal pending vault item %s: %s", stem, exc)
                failed += 1
        if sealed or failed:
            logger.info("Vault seal pass: %d sealed, %d failed/orphaned.", sealed, failed)
        return sealed

    # ---------------------------------------------------------------- reading

    @classmethod
    async def decrypt_snapshot(
        cls,
        clip_id: str,
        parent_pin: str,
    ) -> Optional[Dict[str, Any]]:
        """Decrypt a sealed snapshot/clip using the parent PIN."""
        file_path = cls.get_vault_dir() / clip_id
        if not file_path.exists():
            return None
        blob = file_path.read_bytes()

        try:
            if blob.startswith(_MAGIC_V2):
                parsed = cls._decrypt_v2(blob, parent_pin)
            elif blob.startswith(b"GURUVAULT01"):
                parsed = cls._decrypt_v1(blob, parent_pin)
            else:
                return None
        except PermissionError:
            raise  # wrong-PIN signal surfaced to the router as 403
        except Exception as exc:  # noqa: BLE001
            logger.warning("Decryption failed for %s: %s", clip_id, exc)
            return None

        if parsed is None:
            return None
        payload, kind = parsed
        try:
            meta_len = int.from_bytes(payload[:4], "big")
            meta = json.loads(payload[4:4 + meta_len].decode("utf-8"))
            body = payload[4 + meta_len:]
            if not isinstance(meta, dict):
                raise ValueError("inner metadata is not an object")
        except Exception as exc:  # noqa: BLE001 - corrupt payload reads as missing
            logger.warning("Corrupt vault payload for %s: %s", clip_id, exc)
            return None

        result: Dict[str, Any] = {
            "clip_id": clip_id,
            "metadata": meta,
            "kind": kind,
            "decrypted_at": time.time(),
        }
        if kind == "clip":
            result["frames_base64"] = cls._unpack_frames(body)
            result["fps"] = meta.get("fps", 5.0)
        else:
            result["image_base64"] = base64.b64encode(body).decode("utf-8")
        return result

    @classmethod
    def _decrypt_v2(cls, blob: bytes, parent_pin: str):
        cls._require_crypto()
        header_len = len(_MAGIC_V2) + 16 + 4 + 12 + 4 + 16
        if len(blob) < header_len + 12 + 16:
            return None
        offset = len(_MAGIC_V2)
        salt = blob[offset:offset + 16]
        offset += 16
        iterations = struct.unpack(">I", blob[offset:offset + 4])[0]
        offset += 4
        wrap_nonce = blob[offset:offset + 12]
        offset += 12
        wrapped_len = struct.unpack(">I", blob[offset:offset + 4])[0]
        offset += 4
        stored_verifier = blob[offset:offset + 16]
        offset += 16
        wrapped_key = blob[offset:offset + wrapped_len]
        offset += wrapped_len
        data_nonce = blob[offset:offset + 12]
        offset += 12
        ciphertext = blob[offset:]

        kek = cls._derive_kek(parent_pin, salt, iterations)
        if not hmac.compare_digest(stored_verifier, cls._verifier_for_kek(kek)):
            raise PermissionError("Invalid parent PIN")
        content_key = AESGCM(kek).decrypt(wrap_nonce, wrapped_key, None)
        payload = AESGCM(content_key).decrypt(data_nonce, ciphertext, None)
        # Kind comes from the length-prefixed inner metadata — never from a
        # byte-substring sniff (spacing/ordering variants broke that).
        kind = "snapshot"
        try:
            meta_len = int.from_bytes(payload[:4], "big")
            inner = json.loads(payload[4:4 + meta_len].decode("utf-8"))
            if isinstance(inner, dict) and inner.get("kind") == "clip":
                kind = "clip"
        except Exception:  # noqa: BLE001 - undecodable meta defaults to snapshot
            pass
        return payload, kind

    @classmethod
    def _decrypt_v1(cls, blob: bytes, parent_pin: str):
        cls._require_crypto()
        offset = len(b"GURUVAULT01")
        salt = blob[offset:offset + 16]
        nonce = blob[offset + 16:offset + 28]
        ciphertext = blob[offset + 28:]
        key = hashlib.pbkdf2_hmac("sha256", parent_pin.encode("utf-8"), salt, 100_000, 32)
        payload = AESGCM(key).decrypt(nonce, ciphertext, None)
        return payload, "snapshot"

    @staticmethod
    def _unpack_frames(body: bytes) -> List[str]:
        """Split a length-prefixed frames blob; fail soft on corruption.

        A truncated/corrupt clip must surface as a 404-style "missing or
        corrupted" (handled by the caller), never as an unhandled 500.
        """
        frames: List[str] = []
        if body[:len(_FRAMES_MAGIC)] != _FRAMES_MAGIC:
            # single legacy image payload inside a clip container
            return [base64.b64encode(body).decode("utf-8")]
        try:
            offset = len(_FRAMES_MAGIC)
            count = struct.unpack(">I", body[offset:offset + 4])[0]
            offset += 4
            if count > 10_000:
                raise ValueError(f"implausible frame count {count}")
            for _ in range(count):
                flen = struct.unpack(">I", body[offset:offset + 4])[0]
                offset += 4
                if flen > len(body) - offset:
                    raise ValueError("frame length overruns blob")
                frames.append(base64.b64encode(body[offset:offset + flen]).decode("utf-8"))
                offset += flen
        except Exception as exc:  # noqa: BLE001 - corrupt container, not a crash
            logger.warning("Corrupt frames container (%d bytes): %s", len(body), exc)
            return []
        return frames

    # ---------------------------------------------------------------- listing

    @classmethod
    async def list_encrypted_snapshots(cls, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List sealed snapshots/clips (metadata only, never decrypted here).

        Both name generations are understood — current
        ``{sid}_{epoch_ms}_{rand8}_{evt}`` (ms timestamps) and legacy
        ``{sid}_{epoch_s}_{evt}``. Session filtering compares the parsed
        session id exactly: the old ``startswith`` prefix match leaked
        ``"abc123"`` items into a query for ``"abc"``.
        """
        snapshots: List[Dict[str, Any]] = []
        for file in cls.get_vault_dir().glob("*.vault"):
            name = file.name
            stem = name[: -len(".vault")]
            # Current format first (its rand segment would otherwise parse
            # as part of a legacy event type with a far-future timestamp).
            m2 = _VAULT_NAME_RE_V2.match(stem)
            if m2:
                sess = m2.group("sid")
                ts = float(m2.group("ts")) / 1000.0
                evt = m2.group("evt")
            else:
                m = _VAULT_NAME_RE.match(stem)
                if m:
                    sess = m.group("sid")
                    ts = float(m.group("ts"))
                    evt = m.group("evt")
                else:
                    sess = "unknown"
                    ts = file.stat().st_mtime
                    evt = "INCIDENT"
            if session_id and sess != session_id:
                continue
            try:
                magic = file.open("rb").read(len(_MAGIC_V2))
            except OSError:
                magic = b""
            snapshots.append({
                "clip_id": name,
                "session_id": sess,
                "timestamp": ts,
                "event_type": evt,
                "size_bytes": file.stat().st_size,
                "is_encrypted": True,
                "format": "v2" if magic == _MAGIC_V2 else ("v1" if magic.startswith(b"GURUVAULT01") else "unknown"),
            })
        snapshots.sort(key=lambda s: s["timestamp"], reverse=True)
        return snapshots
