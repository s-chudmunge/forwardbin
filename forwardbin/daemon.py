"""
Background Daemon for ForwardBin Jarvis
Monitors scheduled items and fires timely 'Slot is Up!' emails and desktop notifications.
"""

import time
import sys
from datetime import datetime
from forwardbin.config import load_config
from forwardbin.db import get_upcoming_slots, mark_slot_up_email_sent
from forwardbin.emailer import send_slot_is_up_alert
from forwardbin.core import send_desktop_notification


def run_check_cycle() -> int:
    """Check for slots that are up and trigger notifications. Returns number of alerts sent."""
    cfg = load_config()
    window = cfg.get("notify_minutes_before", 5)
    upcoming = get_upcoming_slots(window_minutes=window)
    count = 0

    for item in upcoming:
        title = item.get("title", "Saved Item")
        print(f"[Daemon] Slot is UP for: {title} (ID {item['id']})")

        # Send Email
        if cfg.get("send_slot_up_email", True):
            try:
                send_slot_is_up_alert(item)
            except Exception as e:
                print(f"[Daemon] Failed to send slot-up email: {e}")

        # Send Desktop Notification
        if cfg.get("send_desktop_notification", True):
            ctype = item.get("content_type", "Item").capitalize()
            dur = item.get("duration_minutes", 30)
            url = item.get("url", "")
            send_desktop_notification(
                f"⏰ Time to { 'Watch' if ctype == 'Video' else 'Read' } ({dur}m)",
                f"{title}\nReady in your queue!",
                icon="alarm"
            )

        mark_slot_up_email_sent(item["id"])
        count += 1

    return count


def start_daemon_loop(poll_interval_seconds: int = 60) -> None:
    """Run continuous monitoring loop."""
    print(f"[Daemon] ForwardBin Jarvis background daemon started (polling every {poll_interval_seconds}s)")
    while True:
        try:
            run_check_cycle()
        except Exception as e:
            print(f"[Daemon] Cycle error: {e}", file=sys.stderr)
        time.sleep(poll_interval_seconds)
