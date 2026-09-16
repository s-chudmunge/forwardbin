"""
Smart Content Extractor for ForwardBin
Extracts metadata, durations, thumbnails, and clean text from videos, papers, articles, and files.
"""

import os
import re
import urllib.parse
from pathlib import Path
from datetime import datetime, timezone, timedelta
from dateutil import tz
import requests
from bs4 import BeautifulSoup

from typing import Optional, Dict, Any, List
from forwardbin.config import load_config


def extract_youtube_video_id(url: str) -> Optional[str]:
    """Extract YouTube 11-char video ID from various URL formats."""
    patterns = [
        r"(?:v=|\/)([0-9A-Za-z_-]{11}).*",
        r"youtu\.be\/([0-9A-Za-z_-]{11})",
        r"youtube\.com\/shorts\/([0-9A-Za-z_-]{11})",
        r"youtube\.com\/embed\/([0-9A-Za-z_-]{11})"
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None


def parse_iso8601_duration(duration_str: str) -> int:
    """Parse ISO 8601 duration (e.g. PT1H23M45S or PT18M) into minutes."""
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration_str)
    if not m:
        return 20
    hours = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    seconds = int(m.group(3) or 0)
    total_minutes = hours * 60 + minutes + (1 if seconds >= 30 else 0)
    return max(total_minutes, 5)


def extract_youtube(url: str, yt_key: Optional[str] = None) -> Dict[str, Any]:
    """Fetch YouTube video details using Data API v3 or yt-dlp fallback."""
    video_id = extract_youtube_video_id(url)
    clean_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else url

    if yt_key and video_id:
        try:
            api_url = (
                f"https://www.googleapis.com/youtube/v3/videos"
                f"?part=snippet,contentDetails&id={video_id}&key={yt_key}"
            )
            r = requests.get(api_url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                items = data.get("items", [])
                if items:
                    snippet = items[0]["snippet"]
                    content_details = items[0]["contentDetails"]
                    duration_min = parse_iso8601_duration(content_details.get("duration", "PT20M"))
                    thumbnails = snippet.get("thumbnails", {})
                    thumb_url = (
                        thumbnails.get("maxres", {}).get("url")
                        or thumbnails.get("high", {}).get("url")
                        or thumbnails.get("default", {}).get("url")
                        or f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
                    )
                    return {
                        "content_type": "video",
                        "title": snippet.get("title", "YouTube Video"),
                        "creator": snippet.get("channelTitle", "YouTube"),
                        "duration_minutes": duration_min,
                        "thumbnail_url": thumb_url,
                        "description": snippet.get("description", "")[:1000],
                        "url": clean_url
                    }
        except Exception as e:
            pass

    # Fallback to yt-dlp
    try:
        import yt_dlp
        ydl_opts = {
            "quiet": True,
            "skip_download": True,
            "extract_flat": False,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            dur_sec = info.get("duration") or 1200
            return {
                "content_type": "video",
                "title": info.get("title", "Online Video"),
                "creator": info.get("uploader", "Video Creator"),
                "duration_minutes": max(int(dur_sec / 60), 5),
                "thumbnail_url": info.get("thumbnail") or "",
                "description": (info.get("description") or "")[:1000],
                "url": url
            }
    except Exception:
        pass

    return {
        "content_type": "video",
        "title": "YouTube Video",
        "creator": "YouTube",
        "duration_minutes": 25,
        "thumbnail_url": f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg" if video_id else "",
        "description": "Video from YouTube",
        "url": url
    }


def extract_arxiv(url: str) -> Dict[str, Any]:
    """Extract metadata from arXiv paper URL."""
    arxiv_id_match = re.search(r"(\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Z]{2})?\/\d{7})", url)
    arxiv_id = arxiv_id_match.group(1) if arxiv_id_match else None
    
    if arxiv_id:
        try:
            api_url = f"https://export.arxiv.org/api/query?id_list={arxiv_id}"
            resp = requests.get(api_url, timeout=10)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.content, "xml")
                entry = soup.find("entry")
                if entry:
                    title = entry.find("title").text.strip().replace("\n", " ")
                    summary = entry.find("summary").text.strip().replace("\n", " ")
                    authors = [a.find("name").text for a in entry.find_all("author")]
                    return {
                        "content_type": "paper",
                        "title": title,
                        "creator": ", ".join(authors[:3]),
                        "duration_minutes": 45,  # Standard paper reading / review slot
                        "thumbnail_url": f"https://ar5iv.labs.arxiv.org/html/{arxiv_id}/assets/figures/figure_cover.png",
                        "description": summary[:1500],
                        "url": f"https://arxiv.org/abs/{arxiv_id}"
                    }
        except Exception:
            pass

    return {
        "content_type": "paper",
        "title": f"ArXiv Research Paper ({arxiv_id or 'Paper'})",
        "creator": "Academic Researchers",
        "duration_minutes": 45,
        "thumbnail_url": "",
        "description": "Scientific paper from arXiv.",
        "url": url
    }


def parse_explicit_event_timing(soup: BeautifulSoup, raw_html: str, target_tz_name: str = "Asia/Kolkata"):
    """
    Deterministically extracts exact event start/end datetime and converts to user local timezone.
    Handles Slate university registration (Georgetown, etc.), Eventbrite, Zoom, Luma, Schema.org Event, etc.
    """
    local_tz = tz.gettz(target_tz_name) or tz.tzlocal()

    # Determine source timezone offset from HTML text (e.g. UTC -04:00, EDT, etc.)
    m_utc = re.search(r"UTC\s*([+-]\d{2}):?(\d{2})?", raw_html)
    src_tz = None
    if m_utc:
        h = int(m_utc.group(1))
        m = int(m_utc.group(2) or 0)
        src_tz = timezone(timedelta(hours=h, minutes=m if h >= 0 else -m))

    if not src_tz:
        tz_abbr_map = {
            "EDT": timezone(timedelta(hours=-4)),
            "EST": timezone(timedelta(hours=-5)),
            "CDT": timezone(timedelta(hours=-5)),
            "CST": timezone(timedelta(hours=-6)),
            "MDT": timezone(timedelta(hours=-6)),
            "MST": timezone(timedelta(hours=-7)),
            "PDT": timezone(timedelta(hours=-7)),
            "PST": timezone(timedelta(hours=-8)),
            "GMT": timezone(timedelta(hours=0)),
            "UTC": timezone(timedelta(hours=0)),
            "BST": timezone(timedelta(hours=1)),
            "CET": timezone(timedelta(hours=1)),
            "CEST": timezone(timedelta(hours=2)),
            "IST": timezone(timedelta(hours=5, minutes=30)),
        }
        for abbr, tz_obj in tz_abbr_map.items():
            if re.search(r"\b" + abbr + r"\b", raw_html):
                src_tz = tz_obj
                break

    if not src_tz:
        src_tz = timezone.utc

    # Strategy 1: Hidden form_date input (Slate / Higher-Ed standard)
    form_date_input = soup.find("input", id=re.compile(r"form_date|event_date", re.I))
    form_date_val = form_date_input.get("value", "") if form_date_input else ""

    if form_date_val and re.search(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", form_date_val):
        try:
            dt_naive = datetime.fromisoformat(form_date_val)
            dt_src = dt_naive.replace(tzinfo=src_tz)
            dt_local_start = dt_src.astimezone(local_tz)

            dur_mins = 30
            m_until = re.search(r"until\s+(\d{1,2}:\d{2}\s*[AP]M)", raw_html, re.I)
            if m_until:
                try:
                    end_time_naive = datetime.strptime(m_until.group(1).strip(), "%I:%M %p").time()
                    end_dt_naive = datetime.combine(dt_naive.date(), end_time_naive)
                    end_dt_src = end_dt_naive.replace(tzinfo=src_tz)
                    diff_mins = int((end_dt_src - dt_src).total_seconds() / 60)
                    if 5 <= diff_mins <= 480:
                        dur_mins = diff_mins
                except Exception:
                    pass

            dt_local_end = dt_local_start + timedelta(minutes=dur_mins)
            return {
                "start_iso": dt_local_start.isoformat(),
                "end_iso": dt_local_end.isoformat(),
                "duration_minutes": dur_mins,
            }
        except Exception:
            pass

    # Strategy 2: Text pattern "Day, Month DD, YYYY at HH:MM AM until HH:MM PM"
    m_full = re.search(
        r"([A-Za-z]+,\s+[A-Za-z]+\s+\d{1,2},\s+\d{4})\s+at\s+(\d{1,2}:\d{2}\s*[AP]M)(?:\s+until\s+(\d{1,2}:\d{2}\s*[AP]M))?",
        raw_html,
        re.I
    )
    if m_full:
        try:
            date_str = m_full.group(1)
            start_time_str = m_full.group(2)
            end_time_str = m_full.group(3)
            dt_naive = datetime.strptime(f"{date_str} {start_time_str}", "%A, %B %d, %Y %I:%M %p")
            dt_src = dt_naive.replace(tzinfo=src_tz)
            dt_local_start = dt_src.astimezone(local_tz)

            dur_mins = 30
            if end_time_str:
                end_naive = datetime.strptime(f"{date_str} {end_time_str}", "%A, %B %d, %Y %I:%M %p")
                end_src = end_naive.replace(tzinfo=src_tz)
                diff = int((end_src - dt_src).total_seconds() / 60)
                if 5 <= diff <= 480:
                    dur_mins = diff

            dt_local_end = dt_local_start + timedelta(minutes=dur_mins)
            return {
                "start_iso": dt_local_start.isoformat(),
                "end_iso": dt_local_end.isoformat(),
                "duration_minutes": dur_mins,
            }
        except Exception:
            pass

    return None


def extract_article(url: str) -> Dict[str, Any]:
    """Extract metadata, text, and reading time estimate from web articles."""
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    cfg = load_config()
    target_tz = cfg.get("user_timezone", "Asia/Kolkata")

    try:
        resp = requests.get(url, headers=headers, timeout=12)
        resp.raise_for_status()
        raw_html = resp.text
        soup = BeautifulSoup(raw_html, "html.parser")

        # Check for explicit event timing first
        fixed_event = parse_explicit_event_timing(soup, raw_html, target_tz)

        # Extract title
        title = ""
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            title = og_title["content"].strip()
        elif soup.title and soup.title.string:
            title = soup.title.string.strip()
        elif soup.find("h1"):
            title = soup.find("h1").get_text().strip()
        if not title:
            parsed = urllib.parse.urlparse(url)
            title = parsed.path.strip("/").split("/")[-1].replace("-", " ").title() or parsed.netloc

        # Extract description / snippet
        desc = ""
        og_desc = soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            desc = og_desc["content"].replace("\xa0", " ").strip()
        if not desc:
            meta_desc = soup.find("meta", attrs={"name": "description"})
            if meta_desc and meta_desc.get("content"):
                desc = meta_desc["content"].replace("\xa0", " ").strip()

        # Extract thumbnail
        thumb_url = ""
        og_img = soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            thumb_url = og_img["content"].strip()

        # Extract explicit Event / Schedule / Date indicators BEFORE decomposing tags
        detected_dates = []
        for inp in soup.find_all("input"):
            val = inp.get("value", "")
            if re.search(r"\d{4}-\d{2}-\d{2}", val):
                detected_dates.append(f"Input date ({inp.get('id', 'field')}): {val}")

        for el in soup.find_all(attrs={"id": re.compile(r"date|time|schedule|event", re.I)}):
            t = el.get_text(separator=" ", strip=True)
            if t and len(t) < 200:
                detected_dates.append(f"#{el.get('id')}: {t}")

        for el in soup.find_all(attrs={"class": re.compile(r"event-date|session-date|event-time", re.I)}):
            t = el.get_text(separator=" ", strip=True)
            if t and len(t) < 200:
                detected_dates.append(f"Event timing: {t}")

        for t_el in soup.find_all("time"):
            dt = t_el.get("datetime") or t_el.get_text(strip=True)
            if dt:
                detected_dates.append(f"time tag: {dt}")

        # Extract body text
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        body_text = soup.get_text(separator=" ", strip=True)
        word_count = len(body_text.split())
        est_min = max(int(word_count / 220), 5)
        est_min = min(est_min, 60)

        # Detect if this represents a scheduled event/session
        is_likely_event = bool(fixed_event) or bool(detected_dates) or bool(
            re.search(r"(?:info(?:rmation)? session|webinar|workshop|conference|symposium|scheduled at|live session)", body_text[:1200], re.I)
        )
        content_type = "event" if is_likely_event else "article"
        duration = fixed_event["duration_minutes"] if fixed_event else est_min

        # Build rich description combining detected dates + main body
        desc_parts = []
        if fixed_event:
            desc_parts.append(f"CONFIRMED EVENT TIME (LOCAL): {fixed_event['start_iso']} to {fixed_event['end_iso']}")
        if detected_dates:
            desc_parts.append("TIMINGS IN PAGE:\n" + "\n".join(detected_dates[:6]))
        if desc:
            desc_parts.append(f"OVERVIEW: {desc}")
        desc_parts.append(f"PAGE TEXT:\n{body_text[:2500]}")
        combined_description = "\n\n".join(desc_parts)

        domain = urllib.parse.urlparse(url).netloc

        return {
            "content_type": content_type,
            "title": title,
            "creator": domain,
            "duration_minutes": duration,
            "thumbnail_url": thumb_url,
            "description": combined_description,
            "detected_dates": detected_dates,
            "fixed_event": fixed_event,
            "url": url
        }
    except Exception as e:
        parsed = urllib.parse.urlparse(url)
        return {
            "content_type": "article",
            "title": parsed.path.strip("/").split("/")[-1].replace("-", " ").title() or parsed.netloc or "Web Article",
            "creator": parsed.netloc,
            "duration_minutes": 20,
            "thumbnail_url": "",
            "description": f"Web resource from {parsed.netloc}",
            "url": url
        }


def extract_local_file(file_path: str) -> Dict[str, Any]:
    """Handle local files or file:// URIs."""
    if file_path.startswith("file://"):
        file_path = urllib.parse.unquote(file_path[7:])
    p = Path(file_path)
    if not p.exists():
        return {
            "content_type": "task",
            "title": "Local Item",
            "creator": "Local",
            "duration_minutes": 15,
            "thumbnail_url": "",
            "description": file_path,
            "url": file_path
        }

    suffix = p.suffix.lower()
    title = p.stem.replace("-", " ").replace("_", " ").title()

    if suffix in [".mp4", ".mkv", ".webm", ".mov", ".avi"]:
        return {
            "content_type": "video",
            "title": f"Watch: {title}",
            "creator": "Local Media",
            "duration_minutes": 30,
            "thumbnail_url": "",
            "description": f"Local video file: {p.name}",
            "url": p.as_uri()
        }
    elif suffix in [".pdf", ".djvu", ".epub"]:
        return {
            "content_type": "paper",
            "title": f"Review: {title}",
            "creator": "Document",
            "duration_minutes": 40,
            "thumbnail_url": "",
            "description": f"Local document: {p.name}",
            "url": p.as_uri()
        }
    else:
        # text / markdown / code
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(2000)
            return {
                "content_type": "article",
                "title": f"Review: {title}",
                "creator": "Local File",
                "duration_minutes": 15,
                "thumbnail_url": "",
                "description": content[:500],
                "url": p.as_uri()
            }
        except Exception:
            return {
                "content_type": "task",
                "title": title,
                "creator": "Local File",
                "duration_minutes": 15,
                "thumbnail_url": "",
                "description": f"File at {p}",
                "url": p.as_uri()
            }


def extract_content(raw_input: str) -> Dict[str, Any]:
    """Master extractor: analyzes any raw string dropped into the bin."""
    cfg = load_config()
    clean_input = raw_input.strip()

    # If input is a multi-line URI list from drag and drop, take the first non-empty line
    lines = [l.strip() for l in clean_input.splitlines() if l.strip()]
    if lines:
        clean_input = lines[0]

    # Check for file:// or local path
    if clean_input.startswith("file://") or (os.path.exists(clean_input) and not clean_input.startswith("http")):
        return extract_local_file(clean_input)

    # Check if URL
    if clean_input.startswith("http://") or clean_input.startswith("https://"):
        parsed = urllib.parse.urlparse(clean_input)
        netloc = parsed.netloc.lower()

        # YouTube
        if "youtube.com" in netloc or "youtu.be" in netloc:
            return extract_youtube(clean_input, cfg.get("youtube_api_key"))

        # ArXiv
        if "arxiv.org" in netloc:
            return extract_arxiv(clean_input)

        # Other video sites (Vimeo, Bilibili, etc.)
        if any(v in netloc for v in ["vimeo.com", "bilibili.com", "dailymotion.com", "loom.com"]):
            return extract_youtube(clean_input, None)  # yt-dlp fallback

        # Standard web article
        return extract_article(clean_input)

    # If it's plain text (e.g. a note or topic)
    return {
        "content_type": "task",
        "title": clean_input[:60] + ("..." if len(clean_input) > 60 else ""),
        "creator": "Quick Note",
        "duration_minutes": 20,
        "thumbnail_url": "",
        "description": clean_input,
        "url": ""
    }
