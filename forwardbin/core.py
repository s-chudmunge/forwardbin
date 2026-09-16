"""
Core Processing Pipeline for ForwardBin Jarvis
Orchestrates: Content Extraction -> AI Analysis -> Calendar Slot Scheduling -> Storage -> Email -> GNOME Notification
"""

import os
import json
import subprocess
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from forwardbin.config import load_config
from forwardbin.content_extractor import extract_content
from forwardbin.ai_brain import analyze_with_ai
from forwardbin.calendar_sync import (
    find_next_available_slot,
    generate_gcal_link,
    add_to_gnome_calendar,
    export_all_to_ics
)
from forwardbin.db import add_item, mark_booking_email_sent, get_item
from forwardbin.emailer import send_booking_confirmation


def send_desktop_notification(title: str, message: str, icon: str = "calendar") -> None:
    """Send native Fedora GNOME desktop notification using notify-send."""
    try:
        subprocess.run([
            "notify-send",
            "-a", "ForwardBin Jarvis",
            "-i", icon,
            title,
            message
        ], check=False)
    except Exception:
        pass


def process_dropped_content(raw_input: str) -> Dict[str, Any]:
    """
    Main entry point when a link, file, or text is dropped into ForwardBin.
    """
    cfg = load_config()
    raw_input = raw_input.strip()
    if not raw_input:
        return {"error": "Empty input"}

    print(f"[ForwardBin Core] Processing input: {raw_input[:100]}...")

    # Step 1: Content Extraction
    extracted = extract_content(raw_input)
    print(f"[ForwardBin Core] Extracted: {extracted.get('title')} ({extracted.get('content_type')})")

    # Step 2: AI Brain Analysis
    ai_result = analyze_with_ai(extracted)
    clean_title = ai_result.get("clean_title") or extracted.get("title", "Saved Item")
    duration = ai_result.get("estimated_minutes") or extracted.get("duration_minutes", 30)
    pref_window = ai_result.get("preferred_window", "anytime")
    summary = ai_result.get("one_line_summary") or extracted.get("description", "")[:200]
    takeaways = json.dumps(ai_result.get("key_takeaways", []))

    # Step 3: Calendar Scheduling & Slot Finding
    fixed_ev = extracted.get("fixed_event")
    is_fixed = ai_result.get("is_fixed_event", False)
    event_start = ai_result.get("event_start_iso")
    event_end = ai_result.get("event_end_iso")

    start_dt = None
    end_dt = None

    # Priority 1: Deterministically extracted event time from page metadata
    if fixed_ev and fixed_ev.get("start_iso"):
        try:
            start_dt = datetime.fromisoformat(fixed_ev["start_iso"])
            end_dt = datetime.fromisoformat(fixed_ev["end_iso"])
            duration = fixed_ev.get("duration_minutes", duration)
            print(f"[ForwardBin Core] 🎯 Direct page event timing confirmed! Scheduled at: {start_dt}")
        except Exception as e:
            print(f"[ForwardBin Core] Error parsing page event timing: {e}")

    # Priority 2: AI-extracted event timing
    if not start_dt and is_fixed and event_start:
        try:
            start_dt = datetime.fromisoformat(event_start)
            if event_end:
                end_dt = datetime.fromisoformat(event_end)
            else:
                end_dt = start_dt + timedelta(minutes=duration)
            print(f"[ForwardBin Core] 🎯 AI Live Event detected! Scheduling at: {start_dt}")
        except Exception as e:
            print(f"[ForwardBin Core] Warning parsing AI event time ({e}), falling back to slot finder")

    # Priority 3: Conflict-free slot finder for flexible articles/videos
    if not start_dt or not end_dt:
        start_dt, end_dt = find_next_available_slot(duration, pref_window)

    gcal_link = generate_gcal_link(clean_title, start_dt, end_dt, summary, extracted.get("url", ""))

    # Step 4: Record in Database
    item_id = add_item(
        raw_input=raw_input,
        content_type=ai_result.get("content_type", extracted.get("content_type", "article")),
        title=clean_title,
        summary=summary,
        key_takeaways=takeaways,
        url=extracted.get("url", ""),
        thumbnail_url=extracted.get("thumbnail_url", ""),
        duration_minutes=duration,
        scheduled_start=start_dt.isoformat(),
        scheduled_end=end_dt.isoformat(),
        gcal_link=gcal_link
    )

    # Step 5: Sync with GNOME Calendar & Master ICS
    add_to_gnome_calendar(clean_title, start_dt, end_dt, summary, extracted.get("url", ""), item_id)
    export_all_to_ics()

    item = get_item(item_id)

    # Step 6: Dispatch Email Confirmation (if enabled)
    if cfg.get("send_instant_booking_email", True) and item:
        try:
            if send_booking_confirmation(item):
                mark_booking_email_sent(item_id)
                item = get_item(item_id)
        except Exception as e:
            print(f"[ForwardBin Core] Error sending confirmation email: {e}")

    # Step 7: Desktop Notification
    time_display = start_dt.strftime("%b %d at %I:%M %p")
    send_desktop_notification(
        "✅ Scheduled in ForwardBin",
        f"'{clean_title}' scheduled for {time_display} ({duration} mins)\n📧 Email sent to {cfg.get('user_email')}"
    )

    return item or {}
