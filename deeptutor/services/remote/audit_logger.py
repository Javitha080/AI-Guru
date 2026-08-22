import json
import time
from typing import Any, Dict, List, Optional
import uuid

import aiosqlite

from deeptutor.services.path_service import get_path_service


class AuditLogger:
    @staticmethod
    def _get_db_path():
        return get_path_service().user_dir / 'chat_history.db'

    @classmethod
    async def _ensure_table(cls):
        async with aiosqlite.connect(cls._get_db_path()) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id TEXT PRIMARY KEY,
                    timestamp INTEGER NOT NULL,
                    actor_id TEXT,
                    actor_role TEXT,
                    action TEXT NOT NULL,
                    resource_type TEXT,
                    resource_id TEXT,
                    details TEXT,
                    ip_address TEXT
                )
                """
            )
            await db.commit()

    @classmethod
    async def log_event(
        cls, 
        actor_id: str, 
        actor_role: str, 
        action: str, 
        resource_type: str, 
        resource_id: str, 
        details: Dict[str, Any], 
        ip_address: str
    ):
        await cls._ensure_table()
        log_id = uuid.uuid4().hex
        timestamp = int(time.time())
        details_json = json.dumps(details)
        
        async with aiosqlite.connect(cls._get_db_path()) as db:
            await db.execute(
                """
                INSERT INTO audit_logs (id, timestamp, actor_id, actor_role, action, resource_type, resource_id, details, ip_address)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (log_id, timestamp, actor_id, actor_role, action, resource_type, resource_id, details_json, ip_address)
            )
            await db.commit()

    @classmethod
    async def get_events(
        cls, 
        actor_id: Optional[str] = None, 
        action: Optional[str] = None, 
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        await cls._ensure_table()
        
        query = "SELECT * FROM audit_logs"
        params = []
        conditions = []
        
        if actor_id:
            conditions.append("actor_id = ?")
            params.append(actor_id)
        if action:
            conditions.append("action = ?")
            params.append(action)
            
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
            
        query += f" ORDER BY timestamp DESC LIMIT {limit}"
        
        async with aiosqlite.connect(cls._get_db_path()) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            
            result = []
            for row in rows:
                r = dict(row)
                if r['details']:
                    r['details'] = json.loads(r['details'])
                result.append(r)
            return result

    @classmethod
    async def get_parent_access_log(cls, parent_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        return await cls.get_events(actor_id=parent_id, limit=limit)
