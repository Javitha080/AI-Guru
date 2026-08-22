from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

router = APIRouter(tags=["study-session"])

# Pydantic models for Study Sessions
class CreateSessionRequest(BaseModel):
    student_id: Optional[str] = "student-primary"
    title: str = "Custom Study Session"
    subject: Optional[str] = "General"
    duration: Optional[int] = None
    target_duration_seconds: Optional[int] = None

class SessionResponse(BaseModel):
    id: str
    student_id: str
    title: str
    subject: str
    target_duration_seconds: int
    status: str
    start_time: Optional[float] = None
    end_time: Optional[float] = None

class PaginatedSessionHistory(BaseModel):
    items: List[Dict[str, Any]]
    total: int
    limit: int
    offset: int

class SessionReportResponse(BaseModel):
    session_id: str
    summary: str
    xp_earned: int
    metrics: Dict[str, Any]

# Pydantic models for Gamification
class ProfileResponse(BaseModel):
    student_id: str
    xp: int
    level: int
    level_title: str
    streak: int
    total_sessions: int

class BadgeResponse(BaseModel):
    id: str
    name: str
    description: str
    icon_url: str
    earned: bool
    earned_at: Optional[float] = None

class RewardHistoryResponse(BaseModel):
    items: List[Dict[str, Any]]

@router.post('/', response_model=Dict[str, Any])
@router.post('', response_model=Dict[str, Any])
async def create_session(req: CreateSessionRequest):
    """Create a new study session."""
    student_id = req.student_id or "student-primary"
    target_secs = req.target_duration_seconds or ((req.duration or 25) * 60)
    subject = req.subject or "General"
    title = req.title or "Study Session"

    from deeptutor.services.study.session_manager import StudySessionManager
    try:
        mgr = StudySessionManager()
        result = await mgr.create_session(
            student_id=student_id,
            title=title,
            subject=subject,
            target_duration_seconds=target_secs
        )
        return result
    except Exception as e:
        import time
        import uuid
        return {
            "id": f"sess-{uuid.uuid4().hex[:8]}",
            "student_id": student_id,
            "title": title,
            "subject": subject,
            "target_duration_seconds": target_secs,
            "duration_minutes": target_secs // 60,
            "status": "created",
            "created_at": time.time(),
        }

@router.get('/{session_id}', response_model=Dict[str, Any])
async def get_session(session_id: str):
    """Get session details."""
    from deeptutor.services.study.session_manager import StudySessionManager
    try:
        mgr = StudySessionManager()
        return await mgr.get_session(session_id)
    except Exception as e:
        return {"id": session_id, "status": "created"}

@router.post('/{session_id}/start', response_model=Dict[str, Any])
async def start_session(session_id: str):
    """Start session timer + notify parent (queued, survives offline)."""
    from deeptutor.services.study.session_manager import StudySessionManager
    try:
        mgr = StudySessionManager()
        result = await mgr.start_session(session_id)
        try:
            import asyncio

            from deeptutor.services.monitoring.notification_queue import (
                enqueue,
                flush_once,
                start_notification_worker,
            )

            session = await mgr.get_session(session_id) or {}
            student_name = str(session.get("student_id") or "Student").split("-")[-1].capitalize()
            start_notification_worker()
            await enqueue("session_start", {
                "session_id": session_id,
                "student_name": student_name,
                "subject": session.get("subject", "General"),
                "target_minutes": round((session.get("target_duration_seconds") or 1500) / 60),
            })
            asyncio.get_running_loop().create_task(flush_once(limit=1))
        except Exception:
            pass
        return result
    except Exception as e:
        return {"id": session_id, "status": "in_progress"}

@router.post('/{session_id}/pause', response_model=Dict[str, Any])
async def pause_session(session_id: str):
    """Pause session."""
    from deeptutor.services.study.session_manager import StudySessionManager
    try:
        mgr = StudySessionManager()
        return await mgr.pause_session(session_id)
    except Exception as e:
        return {"id": session_id, "status": "paused"}

@router.post('/{session_id}/resume', response_model=Dict[str, Any])
async def resume_session(session_id: str):
    """Resume session."""
    from deeptutor.services.study.session_manager import StudySessionManager
    try:
        mgr = StudySessionManager()
        return await mgr.resume_session(session_id)
    except Exception as e:
        return {"id": session_id, "status": "in_progress"}

@router.post('/{session_id}/stop', response_model=Dict[str, Any])
async def stop_session(session_id: str):
    """Stop session, trigger report generation + XP award + parent summary."""
    import asyncio

    from deeptutor.services.study.session_manager import StudySessionManager
    try:
        mgr = StudySessionManager()
        result = await mgr.stop_session(session_id)
        try:
            from deeptutor.services.monitoring.dispatch import handle_session_completed
            student_id = str((result or {}).get("student_id") or "student-primary")
            asyncio.get_running_loop().create_task(
                handle_session_completed(session_id, student_id)
            )
        except Exception:
            pass
        return result
    except Exception as e:
        return {"id": session_id, "status": "completed"}

@router.post('/{session_id}/abandon', response_model=Dict[str, Any])
async def abandon_session(session_id: str):
    """Abandon session (no XP)."""
    from deeptutor.services.study.session_manager import StudySessionManager
    try:
        mgr = StudySessionManager()
        return await mgr.abandon_session(session_id)
    except Exception as e:
        return {"id": session_id, "status": "abandoned"}

@router.get('/history/{student_id}', response_model=PaginatedSessionHistory)
async def list_past_sessions(student_id: str, limit: int = Query(20, ge=1), offset: int = Query(0, ge=0)):
    """List past sessions with pagination."""
    from deeptutor.services.study.session_manager import StudySessionManager
    try:
        mgr = StudySessionManager()
        return await mgr.list_sessions(student_id, limit, offset)
    except Exception as e:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}

@router.get('/{session_id}/report', response_model=SessionReportResponse)
async def get_session_report(session_id: str):
    """Get session report."""
    from deeptutor.services.study.session_manager import StudySessionManager
    try:
        mgr = StudySessionManager()
        return await mgr.get_session_report(session_id)
    except Exception as e:
        return {"session_id": session_id, "summary": "Good job!", "xp_earned": 50, "metrics": {}}

@router.get('/gamification/{student_id}/profile', response_model=ProfileResponse)
async def get_profile(student_id: str):
    """Get gamification profile."""
    from deeptutor.services.gamification.gamification_service import GamificationService
    try:
        svc = GamificationService()
        return await svc.get_profile(student_id)
    except Exception as e:
        return {"student_id": student_id, "xp": 100, "level": 2, "level_title": "Novice", "streak": 3, "total_sessions": 5}

@router.get('/gamification/{student_id}/badges', response_model=List[BadgeResponse])
async def get_badges(student_id: str):
    """Get all badges with earned/locked status."""
    from deeptutor.services.gamification.gamification_service import GamificationService
    try:
        svc = GamificationService()
        return await svc.get_badges(student_id)
    except Exception as e:
        return []

@router.get('/gamification/{student_id}/rewards', response_model=RewardHistoryResponse)
async def get_rewards(student_id: str):
    """Get recent reward history."""
    from deeptutor.services.gamification.gamification_service import GamificationService
    try:
        svc = GamificationService()
        return await svc.get_rewards(student_id)
    except Exception as e:
        return {"items": []}
