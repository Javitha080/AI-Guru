"""Central API error envelope + helpers.

Every router should return errors in the same shape so the frontend can
render honestly without parsing free-form ``str(exc)`` internals::

    {"code": "not_found", "message": "...", "request_id": "...", "details": {...}}

Rules:
- Log the full internal exception server-side (``logger.exception``).
- Return only a safe public ``message`` to the client.
- Map DB errors centrally: locked -> 503, integrity -> 409/422.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any, Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def envelope(
    code: str,
    message: str,
    request_id: str = "",
    status: int = 500,
    details: Optional[dict[str, Any]] = None,
) -> JSONResponse:
    body: dict[str, Any] = {"code": code, "message": message}
    if request_id:
        body["request_id"] = request_id
    if details:
        body["details"] = details
    return JSONResponse(status_code=status, content=body)


def request_id_of(request: Request | None) -> str:
    if request is None:
        return ""
    return str(getattr(request.state, "request_id", "") or "")


def safe_public_message(fallback: str = "Internal error. Try again.") -> str:
    return fallback


def log_internal(action: str, exc: BaseException, request_id: str = "") -> None:
    logger.exception("%s failed [request_id=%s]: %s", action, request_id or "-", exc)


def not_found(resource: str, request: Request | None = None) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{resource} not found")


def conflict(message: str) -> HTTPException:
    return HTTPException(status_code=409, detail=message)


def map_db_error(exc: Exception, *, action: str = "database operation") -> HTTPException:
    """Map sqlite errors to safe HTTP errors (never leak SQL text)."""
    msg = str(exc).lower()
    if isinstance(exc, sqlite3.OperationalError) and "locked" in msg:
        return HTTPException(
            status_code=503, detail=f"{action} is busy (database locked). Retry shortly."
        )
    if isinstance(exc, sqlite3.IntegrityError):
        return HTTPException(status_code=409, detail=f"{action} conflicts with existing data.")
    return HTTPException(status_code=500, detail=f"{action} failed. Try again.")
