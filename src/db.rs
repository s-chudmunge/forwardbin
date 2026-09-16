use rusqlite::{params, Connection, Result};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use crate::config::get_data_dir;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Item {
    pub id: i64,
    pub raw_input: String,
    pub content_type: String,
    pub title: String,
    pub summary: String,
    pub key_takeaways: Vec<String>,
    pub url: String,
    pub duration_minutes: i64,
    pub scheduled_start: String,
    pub scheduled_end: String,
    pub gcal_link: String,
    pub status: String,
    pub booking_email_sent: bool,
    pub slot_up_email_sent: bool,
    pub created_at: String,
    pub updated_at: String,
}

pub fn get_db_path() -> PathBuf {
    let mut p = get_data_dir();
    p.push("forwardbin.db");
    p
}

pub fn get_connection() -> Result<Connection> {
    let conn = Connection::open(get_db_path())?;
    conn.execute_batch(
        "PRAGMA journal_mode = WAL;
         PRAGMA synchronous = NORMAL;
         PRAGMA cache_size = -2000;"
    )?;
    init_db(&conn)?;
    Ok(conn)
}

pub fn init_db(conn: &Connection) -> Result<()> {
    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS items (
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
        );
        CREATE INDEX IF NOT EXISTS idx_status ON items (status);
        CREATE INDEX IF NOT EXISTS idx_scheduled_start ON items (scheduled_start);"
    )?;
    Ok(())
}

pub fn add_item(
    conn: &Connection,
    raw_input: &str,
    content_type: &str,
    title: &str,
    summary: &str,
    key_takeaways: &[String],
    url: &str,
    duration_minutes: i64,
    scheduled_start: &str,
    scheduled_end: &str,
    gcal_link: &str,
) -> Result<i64> {
    let now = chrono::Local::now().to_rfc3339();
    let takeaways_json = serde_json::to_string(key_takeaways).unwrap_or_else(|_| "[]".to_string());

    conn.execute(
        "INSERT INTO items (
            raw_input, content_type, title, summary, key_takeaways,
            url, duration_minutes, scheduled_start, scheduled_end,
            gcal_link, status, created_at, updated_at
        ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, 'scheduled', ?11, ?12)",
        params![
            raw_input, content_type, title, summary, takeaways_json,
            url, duration_minutes, scheduled_start, scheduled_end,
            gcal_link, now, now
        ],
    )?;

    Ok(conn.last_insert_rowid())
}

pub fn list_items(conn: &Connection, status: Option<&str>) -> Result<Vec<Item>> {
    let mut query = "SELECT id, raw_input, content_type, title, summary, key_takeaways, url, duration_minutes, scheduled_start, scheduled_end, gcal_link, status, booking_email_sent, slot_up_email_sent, created_at, updated_at FROM items".to_string();
    if let Some(s) = status {
        query.push_str(&format!(" WHERE status = '{}'", s));
    }
    query.push_str(" ORDER BY scheduled_start ASC");

    let mut stmt = conn.prepare(&query)?;
    let rows = stmt.query_map([], |row| {
        let takeaways_raw: String = row.get(5).unwrap_or_default();
        let takeaways: Vec<String> = serde_json::from_str(&takeaways_raw).unwrap_or_default();
        let b_sent: i64 = row.get(12).unwrap_or(0);
        let s_sent: i64 = row.get(13).unwrap_or(0);

        Ok(Item {
            id: row.get(0)?,
            raw_input: row.get(1)?,
            content_type: row.get(2)?,
            title: row.get(3)?,
            summary: row.get(4)?,
            key_takeaways: takeaways,
            url: row.get(6)?,
            duration_minutes: row.get(7)?,
            scheduled_start: row.get(8)?,
            scheduled_end: row.get(9)?,
            gcal_link: row.get(10)?,
            status: row.get(11)?,
            booking_email_sent: b_sent == 1,
            slot_up_email_sent: s_sent == 1,
            created_at: row.get(14)?,
            updated_at: row.get(15)?,
        })
    })?;

    let mut list = Vec::new();
    for r in rows {
        if let Ok(item) = r {
            list.push(item);
        }
    }
    Ok(list)
}

pub fn delete_item(conn: &Connection, id: i64) -> Result<bool> {
    let affected = conn.execute("DELETE FROM items WHERE id = ?1", params![id])?;
    Ok(affected > 0)
}

pub fn mark_booking_email_sent(conn: &Connection, id: i64) -> Result<()> {
    conn.execute("UPDATE items SET booking_email_sent = 1 WHERE id = ?1", params![id])?;
    Ok(())
}

pub fn mark_slot_up_email_sent(conn: &Connection, id: i64) -> Result<()> {
    let now = chrono::Local::now().to_rfc3339();
    conn.execute(
        "UPDATE items SET slot_up_email_sent = 1, status = 'completed', updated_at = ?1 WHERE id = ?2",
        params![now, id],
    )?;
    Ok(())
}

pub fn get_upcoming_slots(conn: &Connection, window_minutes: i64) -> Result<Vec<Item>> {
    let now = chrono::Local::now();
    let window_end = now + chrono::Duration::minutes(window_minutes);
    let now_str = now.to_rfc3339();
    let window_str = window_end.to_rfc3339();

    let mut stmt = conn.prepare(
        "SELECT id, raw_input, content_type, title, summary, key_takeaways, url, duration_minutes, scheduled_start, scheduled_end, gcal_link, status, booking_email_sent, slot_up_email_sent, created_at, updated_at
         FROM items
         WHERE status = 'scheduled'
           AND slot_up_email_sent = 0
           AND scheduled_start <= ?1
           AND scheduled_start >= datetime(?2, '-1 day')
         ORDER BY scheduled_start ASC"
    )?;

    let rows = stmt.query_map(params![window_str, now_str], |row| {
        let takeaways_raw: String = row.get(5).unwrap_or_default();
        let takeaways: Vec<String> = serde_json::from_str(&takeaways_raw).unwrap_or_default();
        let b_sent: i64 = row.get(12).unwrap_or(0);
        let s_sent: i64 = row.get(13).unwrap_or(0);

        Ok(Item {
            id: row.get(0)?,
            raw_input: row.get(1)?,
            content_type: row.get(2)?,
            title: row.get(3)?,
            summary: row.get(4)?,
            key_takeaways: takeaways,
            url: row.get(6)?,
            duration_minutes: row.get(7)?,
            scheduled_start: row.get(8)?,
            scheduled_end: row.get(9)?,
            gcal_link: row.get(10)?,
            status: row.get(11)?,
            booking_email_sent: b_sent == 1,
            slot_up_email_sent: s_sent == 1,
            created_at: row.get(14)?,
            updated_at: row.get(15)?,
        })
    })?;

    let mut list = Vec::new();
    for r in rows {
        if let Ok(item) = r {
            list.push(item);
        }
    }
    Ok(list)
}
