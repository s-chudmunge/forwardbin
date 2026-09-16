"""
Calendar Integration and Slot Finder for ForwardBin
- Reads busy periods from GNOME Calendar (Evolution Data Server), SQLite DB, and optional Google Calendar iCal feed
- Finds the next optimal free time slot matching content type and user preferences
- Syncs event to Evolution Data Server (GNOME Calendar)
- Generates 1-click Google Calendar add links and standard RFC 5545 .ics calendar files
"""

import os
import urllib.parse
from datetime import datetime, date, time, timedelta, timezone
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional
import requests
import icalendar
from dateutil import tz

from forwardbin.config import load_config, DATA_DIR
from forwardbin.db import get_connection

ICS_EXPORT_PATH = DATA_DIR / "forwardbin.ics"


def get_local_tz():
    cfg = load_config()
    tz_str = cfg.get("user_timezone", "Asia/Kolkata")
    return tz.gettz(tz_str) or tz.tzlocal()


def get_busy_intervals_from_db() -> List[Tuple[datetime, datetime]]:
    """Fetch busy intervals from scheduled ForwardBin items."""
    busy = []
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT scheduled_start, scheduled_end FROM items
            WHERE status != 'cancelled'
        """).fetchall()
        for r in rows:
            try:
                s = datetime.fromisoformat(r["scheduled_start"])
                e = datetime.fromisoformat(r["scheduled_end"])
                busy.append((s, e))
            except Exception:
                pass
    return busy


def get_busy_intervals_from_eds() -> List[Tuple[datetime, datetime]]:
    """Fetch busy intervals from GNOME Calendar / Evolution Data Server."""
    busy = []
    try:
        import gi
        gi.require_version("EDataServer", "1.2")
        gi.require_version("ECal", "2.0")
        gi.require_version("ICalGLib", "3.0")
        from gi.repository import EDataServer as EDS, ECal, ICalGLib

        registry = EDS.SourceRegistry.new_sync(None)
        source = registry.ref_default_calendar()
        if not source:
            return busy
        client = ECal.Client.connect_sync(source, ECal.ClientSourceType.EVENTS, 3, None)
        if not client:
            return busy

        now_utc = datetime.now(timezone.utc)
        start_str = now_utc.strftime("%Y%m%dT%H%M%SZ")
        end_str = (now_utc + timedelta(days=7)).strftime("%Y%m%dT%H%M%SZ")
        sexp = f'(occur-in-time-range? (make-time "{start_str}") (make-time "{end_str}"))'
        res, comps = client.get_object_list_as_comps_sync(sexp, None)
        
        local_tz = get_local_tz()
        for comp in comps:
            dt_start = comp.get_dtstart()
            dt_end = comp.get_dtend()
            if dt_start and dt_end:
                s_str = dt_start.as_ical_string()
                e_str = dt_end.as_ical_string()
                try:
                    s_dt = datetime.strptime(s_str[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc).astimezone(local_tz)
                    e_dt = datetime.strptime(e_str[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc).astimezone(local_tz)
                    busy.append((s_dt, e_dt))
                except Exception:
                    pass
    except Exception as e:
        pass
    return busy


def get_busy_intervals_from_gcal_feed(feed_url: str) -> List[Tuple[datetime, datetime]]:
    """Fetch busy intervals from Google Calendar iCal secret feed if provided."""
    busy = []
    if not feed_url or not feed_url.startswith("http"):
        return busy
    try:
        resp = requests.get(feed_url, timeout=10)
        if resp.status_code == 200:
            cal = icalendar.Calendar.from_ical(resp.content)
            local_tz = get_local_tz()
            for comp in cal.walk("vevent"):
                dtstart = comp.get("dtstart")
                dtend = comp.get("dtend")
                if dtstart:
                    s_dt = dtstart.dt
                    if isinstance(s_dt, date) and not isinstance(s_dt, datetime):
                        s_dt = datetime.combine(s_dt, time(0, 0, tzinfo=local_tz))
                    elif isinstance(s_dt, datetime) and s_dt.tzinfo is None:
                        s_dt = s_dt.replace(tzinfo=local_tz)
                    
                    if dtend:
                        e_dt = dtend.dt
                        if isinstance(e_dt, date) and not isinstance(e_dt, datetime):
                            e_dt = datetime.combine(e_dt, time(23, 59, tzinfo=local_tz))
                        elif isinstance(e_dt, datetime) and e_dt.tzinfo is None:
                            e_dt = e_dt.replace(tzinfo=local_tz)
                    else:
                        e_dt = s_dt + timedelta(minutes=30)
                    busy.append((s_dt.astimezone(local_tz), e_dt.astimezone(local_tz)))
    except Exception as e:
        print(f"[CalendarSync] Error parsing Google Calendar feed: {e}")
    return busy


def find_next_available_slot(duration_minutes: int, preferred_window: str = "anytime") -> Tuple[datetime, datetime]:
    """
    Find the next available time slot for the user.
    - Duration rounded to 15-minute blocks
    - Respects busy slots from DB, GNOME Calendar, and Google Calendar
    - Respects preferred window (morning, afternoon, evening, anytime)
    - Active daily hours default: 09:00 - 22:00
    """
    cfg = load_config()
    local_tz = get_local_tz()
    now = datetime.now(local_tz)

    # Collect all busy intervals
    busy_intervals = []
    busy_intervals.extend(get_busy_intervals_from_db())
    busy_intervals.extend(get_busy_intervals_from_eds())
    gcal_feed = cfg.get("gcal_ical_feed_url")
    if gcal_feed:
        busy_intervals.extend(get_busy_intervals_from_gcal_feed(gcal_feed))

    # Normalize busy intervals to local tz
    normalized_busy = []
    for s, e in busy_intervals:
        if s.tzinfo is None:
            s = s.replace(tzinfo=local_tz)
        else:
            s = s.astimezone(local_tz)
        if e.tzinfo is None:
            e = e.replace(tzinfo=local_tz)
        else:
            e = e.astimezone(local_tz)
        normalized_busy.append((s, e))

    # Minimum start time: 10 minutes from now, rounded up to next 15-minute mark
    min_start = now + timedelta(minutes=10)
    minute_rem = min_start.minute % 15
    if minute_rem != 0:
        min_start += timedelta(minutes=(15 - minute_rem))
    min_start = min_start.replace(second=0, microsecond=0)

    # Window definitions
    window_hours = {
        "morning": (9, 12, 30),     # 09:00 - 12:30
        "afternoon": (13, 17, 30),   # 13:00 - 17:30
        "evening": (18, 22, 0),      # 18:00 - 22:00
        "anytime": (9, 22, 0)        # 09:00 - 22:00
    }

    req_duration = timedelta(minutes=max(duration_minutes, 15))
    buffer_gap = timedelta(minutes=10)

    # Search over next 7 days
    for day_offset in range(7):
        target_day = (now + timedelta(days=day_offset)).date()
        
        # Determine candidate time ranges for this day
        candidate_ranges = []
        if preferred_window in window_hours and preferred_window != "anytime":
            sh, eh, em = window_hours[preferred_window]
            candidate_ranges.append((time(sh, 0), time(eh, em)))
            # Fallback to whole day if specific window is booked
            candidate_ranges.append((time(9, 0), time(22, 0)))
        else:
            candidate_ranges.append((time(9, 0), time(22, 0)))

        for w_start, w_end in candidate_ranges:
            slot_cursor = datetime.combine(target_day, w_start, tzinfo=local_tz)
            window_limit = datetime.combine(target_day, w_end, tzinfo=local_tz)

            if slot_cursor < min_start:
                slot_cursor = min_start

            while slot_cursor + req_duration <= window_limit:
                slot_end = slot_cursor + req_duration
                
                # Check collision with any busy interval
                collision = False
                for b_start, b_end in normalized_busy:
                    # If overlapping with buffer
                    if (slot_cursor - buffer_gap) < b_end and (slot_end + buffer_gap) > b_start:
                        collision = True
                        # Jump cursor past this busy slot
                        next_cursor = b_end + buffer_gap
                        minute_rem = next_cursor.minute % 15
                        if minute_rem != 0:
                            next_cursor += timedelta(minutes=(15 - minute_rem))
                        slot_cursor = max(slot_cursor + timedelta(minutes=15), next_cursor.replace(second=0, microsecond=0))
                        break
                
                if not collision:
                    return (slot_cursor, slot_end)

    # Absolute fallback: tomorrow morning at 09:00
    fallback_start = datetime.combine(now.date() + timedelta(days=1), time(9, 0), tzinfo=local_tz)
    return (fallback_start, fallback_start + req_duration)


def add_to_gnome_calendar(title: str, start_dt: datetime, end_dt: datetime, details: str, url: str, item_id: int) -> bool:
    """Insert event into Evolution Data Server (GNOME Calendar)."""
    cfg = load_config()
    if not cfg.get("auto_add_to_gnome_calendar", True):
        return False

    try:
        import gi
        gi.require_version("EDataServer", "1.2")
        gi.require_version("ECal", "2.0")
        gi.require_version("ICalGLib", "3.0")
        from gi.repository import EDataServer as EDS, ECal, ICalGLib

        registry = EDS.SourceRegistry.new_sync(None)
        source = registry.ref_default_calendar()
        if not source:
            return False
        client = ECal.Client.connect_sync(source, ECal.ClientSourceType.EVENTS, 3, None)
        if not client:
            return False

        s_utc = start_dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        e_utc = end_dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        uid = f"forwardbin-{item_id}-{int(start_dt.timestamp())}@jarvis"

        description_clean = f"{details}\n\nResource Link: {url}".replace("\n", "\\n")

        ical_text = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//ForwardBin Jarvis//EN
BEGIN:VEVENT
UID:{uid}
SUMMARY:[ForwardBin] {title}
DESCRIPTION:{description_clean}
LOCATION:{url}
DTSTART:{s_utc}
DTEND:{e_utc}
END:VEVENT
END:VCALENDAR"""

        comp = ICalGLib.Component.new_from_string(ical_text)
        vevent = comp.get_first_component(ICalGLib.ComponentKind.VEVENT_COMPONENT)
        client.create_object_sync(vevent, ECal.OperationFlags.NONE, None)
        return True
    except Exception as e:
        print(f"[CalendarSync] Failed to add to GNOME Calendar: {e}")
        return False


def generate_gcal_link(title: str, start_dt: datetime, end_dt: datetime, details: str, url: str) -> str:
    """Generate 1-click Google Calendar web event creation link."""
    start_utc = start_dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    end_utc = end_dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    params = {
        "action": "TEMPLATE",
        "text": f"[ForwardBin] {title}",
        "dates": f"{start_utc}/{end_utc}",
        "details": f"{details}\n\nResource: {url}",
        "location": url
    }
    return "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(params)


def create_ics_event_content(title: str, start_dt: datetime, end_dt: datetime, details: str, url: str, item_id: int) -> str:
    """Generate standard RFC 5545 .ics string for email attachment."""
    cal = icalendar.Calendar()
    cal.add("prodid", "-//ForwardBin Jarvis//EN")
    cal.add("version", "2.0")
    cal.add("method", "REQUEST")

    event = icalendar.Event()
    event.add("summary", f"[ForwardBin] {title}")
    event.add("description", f"{details}\n\nResource: {url}")
    event.add("location", url)
    event.add("dtstart", start_dt.astimezone(timezone.utc))
    event.add("dtend", end_dt.astimezone(timezone.utc))
    event.add("dtstamp", datetime.now(timezone.utc))
    event.add("uid", f"forwardbin-{item_id}-{int(start_dt.timestamp())}@jarvis")
    event.add("status", "CONFIRMED")
    
    cal.add_component(event)
    return cal.to_ical().decode("utf-8")


def export_all_to_ics() -> None:
    """Regenerate the master forwardbin.ics file."""
    cal = icalendar.Calendar()
    cal.add("prodid", "-//ForwardBin Jarvis Calendar//EN")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", "ForwardBin Jarvis Schedule")

    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM items WHERE status != 'cancelled'").fetchall()
        for r in rows:
            try:
                s_dt = datetime.fromisoformat(r["scheduled_start"])
                e_dt = datetime.fromisoformat(r["scheduled_end"])
                ev = icalendar.Event()
                ev.add("summary", f"[ForwardBin] {r['title']}")
                ev.add("description", f"{r['summary']}\n\n{r['key_takeaways']}\n\nLink: {r['url']}")
                ev.add("location", r["url"] or "")
                ev.add("dtstart", s_dt)
                ev.add("dtend", e_dt)
                ev.add("uid", f"forwardbin-{r['id']}@jarvis")
                cal.add_component(ev)
            except Exception:
                pass

    with open(ICS_EXPORT_PATH, "wb") as f:
        f.write(cal.to_ical())
