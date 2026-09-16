"""
Email Notification Service for ForwardBin
Uses Resend API to deliver immediate schedule confirmations and timely 'Slot is Up' alerts.
"""

import base64
import json
from datetime import datetime
from typing import Dict, Any, Optional
import requests
from dateutil import tz

from forwardbin.config import load_config
from forwardbin.calendar_sync import create_ics_event_content


def _format_time_display(dt: datetime) -> str:
    """Format datetime nicely for emails."""
    today = datetime.now(dt.tzinfo).date()
    target_date = dt.date()
    
    if target_date == today:
        date_str = "Today"
    elif (target_date - today).days == 1:
        date_str = "Tomorrow"
    else:
        date_str = dt.strftime("%A, %b %d")
        
    time_str = dt.strftime("%I:%M %p %Z")
    return f"{date_str} at {time_str}"


def send_booking_confirmation(item: Dict[str, Any]) -> bool:
    """
    Sends an immediate email notification when a new item is dropped and scheduled.
    Includes AI summary, Google Calendar link, and .ics calendar invite attachment.
    """
    cfg = load_config()
    api_key = cfg.get("resend_api_key")
    sender = cfg.get("resend_sender") or os.getenv("RESEND_SENDER")
    recipient = cfg.get("user_email") or os.getenv("USER_EMAIL") or os.getenv("FORWARDBIN_USER_EMAIL")

    if not api_key:
        print("[ForwardBin Emailer] Resend API key missing.")
        return False

    if not sender or not recipient:
        print("[ForwardBin Emailer] Resend sender or user recipient email not configured.")
        return False

    title = item.get("title", "Saved Item")
    url = item.get("url", "")
    content_type = item.get("content_type", "article").capitalize()
    duration = item.get("duration_minutes", 30)
    summary = item.get("summary", "Scheduled in your forward queue.")
    gcal_link = item.get("gcal_link", "")

    try:
        start_dt = datetime.fromisoformat(item["scheduled_start"])
        end_dt = datetime.fromisoformat(item["scheduled_end"])
    except Exception:
        start_dt = datetime.now()
        end_dt = datetime.now()

    time_display = _format_time_display(start_dt)
    
    # Parse key takeaways
    takeaways_html = ""
    raw_takeaways = item.get("key_takeaways", "")
    if raw_takeaways:
        try:
            if isinstance(raw_takeaways, list):
                items_list = raw_takeaways
            elif raw_takeaways.startswith("["):
                items_list = json.loads(raw_takeaways)
            else:
                items_list = [t.strip() for t in raw_takeaways.split("\n") if t.strip()]
            for point in items_list:
                takeaways_html += f"<li style='margin-bottom:6px;'>{point}</li>"
        except Exception:
            takeaways_html = f"<li>{raw_takeaways}</li>"

    if takeaways_html:
        takeaways_html = f"""
        <div style="margin-top:20px;background:#f6f8fa;padding:16px 20px;border-radius:8px;border:1px solid #d0d7de;border-left:4px solid #0969da;">
            <strong style="color:#0969da;font-size:13px;text-transform:uppercase;letter-spacing:0.5px;">Key Takeaways & Objectives:</strong>
            <ul style="margin:8px 0 0 0;padding-left:20px;color:#24292f;font-size:14px;line-height:1.6;">
                {takeaways_html}
            </ul>
        </div>
        """

    badge_bg = "#fff8c5" if content_type == "Video" else ("#fbefff" if content_type == "Paper" else ("#dafbe1" if content_type == "Event" else "#ddf4ff"))
    badge_fg = "#9a6700" if content_type == "Video" else ("#8250df" if content_type == "Paper" else ("#1a7f37" if content_type == "Event" else "#0969da"))
    badge_border = "#d4a72c" if content_type == "Video" else ("#d2a8ff" if content_type == "Paper" else ("#4ac26b" if content_type == "Event" else "#54aeff"))

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="margin:0;padding:24px;background-color:#f6f8fa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#1f2328;">
        <div style="max-width:600px;margin:0 auto;background:#ffffff;border:1px solid #d0d7de;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.06);">
            <div style="background:linear-gradient(135deg, #0969da 0%, #054da7 100%);padding:22px 24px;color:#ffffff;">
                <span style="display:inline-block;padding:4px 10px;background:rgba(255,255,255,0.22);border-radius:12px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">Jarvis ForwardBin</span>
                <h1 style="margin:0;font-size:20px;font-weight:700;line-height:1.3;">Slot Booked: {title}</h1>
            </div>

            <div style="padding:24px;">
                <div style="display:flex;align-items:center;margin-bottom:18px;">
                    <span style="display:inline-block;background:{badge_bg};color:{badge_fg};border:1px solid {badge_border};padding:4px 12px;border-radius:6px;font-size:12px;font-weight:700;text-transform:uppercase;margin-right:12px;">{content_type}</span>
                    <span style="color:#656d76;font-size:14px;">⏱️ Duration: <strong style="color:#1f2328;">{duration} mins</strong></span>
                </div>

                <div style="background:#f0f7ff;border:1px solid #b6e3ff;padding:16px;border-radius:8px;margin-bottom:20px;">
                    <div style="color:#0969da;font-size:12px;text-transform:uppercase;font-weight:700;letter-spacing:0.5px;">Scheduled Time Slot:</div>
                    <div style="color:#0969da;font-size:18px;font-weight:700;margin-top:4px;">📅 {time_display}</div>
                </div>

                <div style="margin-bottom:20px;">
                    <strong style="color:#1f2328;font-size:14px;">AI Brief:</strong>
                    <p style="margin:6px 0 0 0;color:#3c444d;font-size:14px;line-height:1.6;">{summary}</p>
                </div>

                {takeaways_html}

                <div style="margin-top:28px;padding-top:20px;border-top:1px solid #d0d7de;text-align:center;">
                    {f'<a href="{url}" style="display:inline-block;background:#1f883d;color:#ffffff;text-decoration:none;padding:12px 22px;border-radius:6px;font-weight:600;font-size:14px;margin-right:10px;margin-bottom:10px;box-shadow:0 2px 6px rgba(31,136,61,0.2);">🔗 Open Resource</a>' if url else ''}
                    {f'<a href="{gcal_link}" style="display:inline-block;background:#0969da;color:#ffffff;text-decoration:none;padding:12px 22px;border-radius:6px;font-weight:600;font-size:14px;margin-bottom:10px;box-shadow:0 2px 6px rgba(9,105,218,0.2);">📅 View in Google Calendar</a>' if gcal_link else ''}
                </div>

                <p style="text-align:center;color:#656d76;font-size:12px;margin-top:22px;">
                    Added to your local GNOME Calendar automatically. A calendar invite (.ics) is also attached.
                </p>
            </div>
        </div>
    </body>
    </html>
    """

    # Generate attached .ics file
    ics_text = create_ics_event_content(title, start_dt, end_dt, summary, url, item.get("id", 1))
    b64_ics = base64.b64encode(ics_text.encode("utf-8")).decode("utf-8")

    payload = {
        "from": f"ForwardBin Jarvis <{sender}>",
        "to": [recipient],
        "subject": f"📥 [ForwardBin] Scheduled: {title} ({time_display})",
        "html": html_content,
        "attachments": [
            {
                "filename": "forwardbin_event.ics",
                "content": b64_ics
            }
        ]
    }

    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=15
        )
        if resp.status_code in [200, 201]:
            print(f"[ForwardBin Emailer] Booking confirmation sent to {recipient}")
            return True
        else:
            print(f"[ForwardBin Emailer] Resend error {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"[ForwardBin Emailer] Failed sending email: {e}")
    return False


def send_slot_is_up_alert(item: Dict[str, Any]) -> bool:
    """
    Sends an alert when the scheduled slot arrives ('Whenever they are up').
    """
    cfg = load_config()
    api_key = cfg.get("resend_api_key")
    sender = cfg.get("resend_sender") or os.getenv("RESEND_SENDER")
    recipient = cfg.get("user_email") or os.getenv("USER_EMAIL") or os.getenv("FORWARDBIN_USER_EMAIL")

    if not api_key or not sender or not recipient:
        return False

    title = item.get("title", "Saved Item")
    url = item.get("url", "")
    content_type = item.get("content_type", "article").capitalize()
    duration = item.get("duration_minutes", 30)
    summary = item.get("summary", "")

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="margin:0;padding:24px;background-color:#f6f8fa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#1f2328;">
        <div style="max-width:600px;margin:0 auto;background:#ffffff;border:1px solid #d0d7de;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.06);">
            <div style="background:linear-gradient(135deg, #ea580c 0%, #dc2626 100%);padding:22px 24px;color:#ffffff;">
                <span style="display:inline-block;padding:4px 10px;background:rgba(255,255,255,0.22);border-radius:12px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">⏰ Slot Starting Now</span>
                <h1 style="margin:0;font-size:22px;font-weight:700;line-height:1.3;">Time to { 'Attend' if content_type == 'Event' else ('Watch' if content_type == 'Video' else 'Read') }: {title}</h1>
            </div>

            <div style="padding:24px;">
                <p style="font-size:16px;color:#1f2328;margin-top:0;">
                    Your scheduled <strong>{duration}-minute</strong> slot is starting right now!
                </p>

                <div style="background:#fff8f0;border-left:4px solid #ea580c;border:1px solid #fed7aa;padding:16px 20px;border-radius:8px;margin-bottom:24px;">
                    <strong style="color:#c2410c;font-size:14px;text-transform:uppercase;letter-spacing:0.5px;">Summary:</strong>
                    <p style="margin:6px 0 0 0;color:#374151;font-size:14px;line-height:1.6;">{summary}</p>
                </div>

                {f'''
                <div style="text-align:center;margin:30px 0 10px 0;">
                    <a href="{url}" style="display:inline-block;background:#ea580c;color:#ffffff;text-decoration:none;padding:14px 28px;border-radius:8px;font-weight:700;font-size:16px;box-shadow:0 4px 12px rgba(234,88,12,0.3);">
                        🚀 Open {content_type} Now
                    </a>
                </div>
                ''' if url else ''}

                <p style="text-align:center;color:#6b7280;font-size:12px;margin-top:24px;">
                    ForwardBin Jarvis Automation &bull; Fedora Workstation
                </p>
            </div>
        </div>
    </body>
    </html>
    """

    payload = {
        "from": f"ForwardBin Jarvis <{sender}>",
        "to": [recipient],
        "subject": f"⏰ [ForwardBin] It's Time: {title} (Your {duration}m slot is UP!)",
        "html": html_content
    }

    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=15
        )
        if resp.status_code in [200, 201]:
            print(f"[ForwardBin Emailer] Slot-is-up alert sent to {recipient}")
            return True
    except Exception as e:
        print(f"[ForwardBin Emailer] Failed sending slot alert: {e}")
    return False
