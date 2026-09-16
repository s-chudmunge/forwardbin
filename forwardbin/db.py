"""
Database Layer for ForwardBin
Uses SQLite to store forward bin items, their AI analysis, scheduling slots, and notification statuses.
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from forwardbin.config import DATA_DIR

DB_PATH = DATA_DIR / "forwardbin.db"


_initialized = False

def get_connection() -> sqlite3.Connection:
    global _initialized
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    if not _initialized:
        init_db()
        _initialized = True
    return conn


def init_db() -> None:
    """Initialize database tables and indexes."""
    conn = sqlite3.connect(str(DB_PATH))
    with conn:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA cache_size = -2000;")  # 2MB max memory cache
        conn.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_input TEXT NOT NULL,
                content_type TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT,
                key_takeaways TEXT,
                url TEXT,
                thumbnail_url TEXT,
                duration_minutes INTEGER DEFAULT 30,
                scheduled_start TEXT NOT NULL,
                scheduled_end TEXT NOT NULL,
                gcal_link TEXT,
                status TEXT DEFAULT 'scheduled',
                booking_email_sent INTEGER DEFAULT 0,
                slot_up_email_sent INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON items (status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_start ON items (scheduled_start)")
    conn.close()


def add_item(
    raw_input: str,
    content_type: str,
    title: str,
    summary: str,
    key_takeaways: str,
    url: str,
    thumbnail_url: str,
    duration_minutes: int,
    scheduled_start: str,
    scheduled_end: str,
    gcal_link: str
) -> int:
    """Insert a new scheduled item."""
    now_iso = datetime.now().isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO items (
                raw_input, content_type, title, summary, key_takeaways,
                url, thumbnail_url, duration_minutes, scheduled_start,
                scheduled_end, gcal_link, status, booking_email_sent,
                slot_up_email_sent, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', 0, 0, ?, ?)
        """, (
            raw_input, content_type, title, summary, key_takeaways,
            url, thumbnail_url, duration_minutes, scheduled_start,
            scheduled_end, gcal_link, now_iso, now_iso
        ))
        item_id = cursor.lastrowid
        conn.commit()
        return item_id


def get_item(item_id: int) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return dict(row) if row else None


def list_items(status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM items WHERE status = ? ORDER BY scheduled_start ASC LIMIT ?",
                (status, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM items ORDER BY scheduled_start DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


def get_upcoming_slots(window_minutes: int = 15) -> List[Dict[str, Any]]:
    """Returns items whose scheduled slot is about to start or currently active and not yet notified."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM items
            WHERE slot_up_email_sent = 0
              AND status = 'scheduled'
            ORDER BY scheduled_start ASC
        """).fetchall()
        
        matches = []
        for r in rows:
            d = dict(r)
            try:
                start_dt = datetime.fromisoformat(d["scheduled_start"])
                if start_dt.tzinfo is not None:
                    now = datetime.now(start_dt.tzinfo)
                else:
                    now = datetime.now()
                # Alert if slot is within `window_minutes` into future OR started within last 15 minutes
                diff_sec = (start_dt - now).total_seconds()
                if -900 <= diff_sec <= (window_minutes * 60):
                    matches.append(d)
            except Exception as e:
                print(f"[DB] Error checking slot: {e}")
                continue
        return matches


def mark_booking_email_sent(item_id: int) -> None:
    now_iso = datetime.now().isoformat()
    with get_connection() as conn:
        conn.execute("""
            UPDATE items SET booking_email_sent = 1, updated_at = ? WHERE id = ?
        """, (now_iso, item_id))


def mark_slot_up_email_sent(item_id: int) -> None:
    now_iso = datetime.now().isoformat()
    with get_connection() as conn:
        conn.execute("""
            UPDATE items SET slot_up_email_sent = 1, status = 'notified', updated_at = ? WHERE id = ?
        """, (now_iso, item_id))


def delete_item(item_id: int) -> bool:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM items WHERE id = ?", (item_id,))
        return cursor.rowcount > 0
