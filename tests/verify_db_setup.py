"""
Verify complete AI Guru SQLite Database setup and table presence.
"""
import sqlite3
from deeptutor.services.path_service import get_path_service
from deeptutor.services.database.migrations import apply_migrations, verify_tables_exist, CORE_TABLE_NAMES

def main():
    db_path = get_path_service().user_dir / "chat_history.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        applied = apply_migrations(conn)
        status_map = verify_tables_exist(conn)
    
    print(f"Database File: {db_path}")
    print(f"Database Migrations Newly Applied: {applied}")
    print("\nTable Verification Summary:")
    all_ok = True
    for tbl in CORE_TABLE_NAMES:
        exists = status_map.get(tbl, False)
        status_text = "OK / VERIFIED" if exists else "MISSING"
        print(f"  [{status_text}] {tbl}")
        if not exists:
            all_ok = False
            
    if all_ok:
        print("\nALL 11 CORE RELATIONAL TABLES ARE 100% INITIALIZED AND READY!")
    else:
        print("\nSome tables are missing.")

if __name__ == "__main__":
    main()
