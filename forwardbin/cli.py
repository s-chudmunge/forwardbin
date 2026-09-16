"""
ForwardBin CLI Tool
Manage, schedule, and configure ForwardBin Jarvis from terminal or system hotkeys.
"""

import sys
import argparse
import subprocess
import json
from datetime import datetime
from typing import Optional

from forwardbin.config import load_config, save_config, CONFIG_FILE
from forwardbin.core import process_dropped_content
from forwardbin.db import list_items, delete_item
from forwardbin.daemon import start_daemon_loop
from forwardbin.emailer import send_booking_confirmation, send_slot_is_up_alert


def get_clipboard_text() -> str:
    """Read current clipboard text using wl-paste or xclip or tkinter."""
    try:
        res = subprocess.run(["wl-paste", "--no-newline"], capture_output=True, text=True, timeout=2)
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass

    try:
        res = subprocess.run(["xclip", "-selection", "clipboard", "-o"], capture_output=True, text=True, timeout=2)
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass

    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        content = root.clipboard_get()
        root.destroy()
        return content.strip()
    except Exception:
        pass

    return ""


def main():
    parser = argparse.ArgumentParser(
        prog="forwardbin",
        description="ForwardBin Jarvis - Smart Content Drop Bin & Time Slot Scheduler for Fedora Linux"
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # forwardbin ui
    subparsers.add_parser("ui", help="Launch the floating drag-and-drop Jarvis bin widget")

    # forwardbin add <input>
    add_parser = subparsers.add_parser("add", help="Forward a video link, paper URL, article, or file")
    add_parser.add_argument("content", help="URL, file path, or text snippet to schedule")

    # forwardbin clipboard
    subparsers.add_parser("clipboard", help="Snatch current clipboard contents and schedule immediately")

    # forwardbin list
    list_parser = subparsers.add_parser("list", help="List scheduled items")
    list_parser.add_argument("--all", action="store_true", help="Show all items including completed/notified")

    # forwardbin daemon
    daemon_parser = subparsers.add_parser("daemon", help="Run background notification and email daemon")
    daemon_parser.add_argument("--interval", type=int, default=60, help="Polling interval in seconds (default: 60)")

    # forwardbin config
    cfg_parser = subparsers.add_parser("config", help="View or update configuration")
    cfg_parser.add_argument("--set-email", help="Set recipient email address")
    cfg_parser.add_argument("--set-gcal-feed", help="Set secret Google Calendar iCal feed URL")
    cfg_parser.add_argument("--show", action="store_true", help="Display full current configuration")

    # forwardbin test-email
    subparsers.add_parser("test-email", help="Send a test verification email via Resend")

    # forwardbin delete <id>
    del_parser = subparsers.add_parser("delete", help="Delete a scheduled item by ID")
    del_parser.add_argument("item_id", type=int, help="Item ID to remove")

    args = parser.parse_args()

    # Default action if no subcommand is given: launch UI
    if not args.subcommand or args.subcommand == "ui":
        from forwardbin.ui.animated_bin import launch_animated_ui
        launch_animated_ui()

    elif args.subcommand == "add":
        print(f"🤖 Jarvis analyzing: {args.content}")
        res = process_dropped_content(args.content)
        if "error" in res:
            print(f"❌ Error: {res['error']}")
            sys.exit(1)
        print(f"✅ Successfully Scheduled: '{res.get('title')}'")
        s_dt = res.get("scheduled_start", "")
        dur = res.get("duration_minutes", 30)
        print(f"📅 Slot: {s_dt} ({dur} mins)")
        if res.get("booking_email_sent"):
            print(f"📧 Confirmation email dispatched to {load_config().get('user_email')}")
        if res.get("gcal_link"):
            print(f"🔗 Google Calendar URL: {res['gcal_link']}")

    elif args.subcommand == "clipboard":
        text = get_clipboard_text()
        if not text:
            print("⚠️ Clipboard is empty or contains non-text content.")
            sys.exit(1)
        print(f"📋 Snatched from clipboard: {text[:80]}...")
        res = process_dropped_content(text)
        print(f"✅ Scheduled: '{res.get('title')}' for {res.get('scheduled_start')}")

    elif args.subcommand == "list":
        items = list_items(status=None if args.all else "scheduled")
        if not items:
            print("No items found.")
            return
        print(f"\n{'ID':<4} {'Type':<8} {'Scheduled Slot':<24} {'Duration':<9} {'Title'}")
        print("-" * 80)
        for it in items:
            try:
                dt = datetime.fromisoformat(it["scheduled_start"])
                time_disp = dt.strftime("%Y-%m-%d %I:%M %p")
            except Exception:
                time_disp = it["scheduled_start"][:16]
            ctype = it.get("content_type", "").upper()
            dur = f"{it.get('duration_minutes', 0)}m"
            print(f"{it['id']:<4} {ctype:<8} {time_disp:<24} {dur:<9} {it.get('title', '')[:35]}")
        print()

    elif args.subcommand == "daemon":
        start_daemon_loop(poll_interval_seconds=args.interval)

    elif args.subcommand == "config":
        cfg = load_config()
        if args.set_email:
            cfg["user_email"] = args.set_email.strip()
            save_config(cfg)
            print(f"✅ Updated recipient email to: {cfg['user_email']}")
        if args.set_gcal_feed:
            cfg["gcal_ical_feed_url"] = args.set_gcal_feed.strip()
            save_config(cfg)
            print(f"✅ Updated Google Calendar iCal feed URL")
        if args.show or (not args.set_email and not args.set_gcal_feed):
            # Mask sensitive tokens
            disp = dict(cfg)
            if disp.get("openrouter_api_key"):
                disp["openrouter_api_key"] = disp["openrouter_api_key"][:8] + "..."
            if disp.get("resend_api_key"):
                disp["resend_api_key"] = disp["resend_api_key"][:8] + "..."
            if disp.get("youtube_api_key"):
                disp["youtube_api_key"] = disp["youtube_api_key"][:8] + "..."
            print(f"\nForwardBin Configuration ({CONFIG_FILE}):")
            print(json.dumps(disp, indent=2))

    elif args.subcommand == "test-email":
        cfg = load_config()
        sample_item = {
            "id": 999,
            "title": "Jarvis Test Verification Event",
            "url": "https://en.wikipedia.org/wiki/Artificial_intelligence",
            "content_type": "article",
            "duration_minutes": 25,
            "scheduled_start": datetime.now().isoformat(),
            "scheduled_end": datetime.now().isoformat(),
            "summary": "This is a test notification confirming your Resend email connection works flawlessly.",
            "key_takeaways": ["ForwardBin Email Integration is Active", "Resend API connection confirmed", "Slots will be emailed to you"],
            "gcal_link": "https://calendar.google.com"
        }
        print(f"Sending test email to {cfg.get('user_email')}...")
        if send_booking_confirmation(sample_item):
            print(f"✅ Success! Check inbox at {cfg.get('user_email')}")
        else:
            print("❌ Failed to send test email. Check logs.")

    elif args.subcommand == "delete":
        if delete_item(args.item_id):
            print(f"✅ Deleted item {args.item_id}")
        else:
            print(f"⚠️ Item {args.item_id} not found")


if __name__ == "__main__":
    main()
