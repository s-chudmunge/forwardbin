"""
AI Brain for ForwardBin
Uses OpenRouter LLM to analyze dropped content, categorize it, extract key takeaways,
and determine the optimal scheduling slot duration and time window.
"""

import json
import re
from typing import Dict, Any, List
from datetime import datetime
import requests

from forwardbin.config import load_config


SYSTEM_PROMPT = """You are ForwardBin Jarvis, an intelligent executive scheduling assistant operating on Linux.
Your job is to analyze content (events, videos, papers, articles, tasks) dropped by the user, and prepare it for time scheduling.

CRITICAL LIVE EVENT RULE:
If the content represents a LIVE event, webinar, information session, class, conference, meeting, or broadcast that occurs at a SPECIFIC DATE AND TIME:
- Set "content_type": "event"
- Set "is_fixed_event": true
- Calculate and set "event_start_iso": Exact ISO 8601 string converted to the user's local timezone (e.g. "2026-09-16T19:30:00+05:30").
- Calculate and set "event_end_iso": Exact ISO 8601 string converted to the user's local timezone (e.g. "2026-09-16T20:00:00+05:30").
- Set "estimated_minutes": duration in minutes.
If it is NOT a live event with a fixed time (e.g. general article, YouTube video, reading paper):
- Set "is_fixed_event": false
- Set "event_start_iso": null
- Set "event_end_iso": null

Output strictly valid JSON:
{
  "clean_title": "Concise, readable title (max 80 chars)",
  "content_type": "event | video | paper | article | task",
  "is_fixed_event": true,
  "event_start_iso": "YYYY-MM-DDTHH:MM:SS+HH:MM",
  "event_end_iso": "YYYY-MM-DDTHH:MM:SS+HH:MM",
  "estimated_minutes": 30,
  "preferred_window": "morning | afternoon | evening | anytime",
  "one_line_summary": "Crisp 1-2 sentence overview of what this is about",
  "key_takeaways": [
    "Key takeaway or concept 1",
    "Key takeaway or concept 2",
    "Key takeaway or concept 3"
  ],
  "why_it_matters": "One punchy sentence explaining the value of this"
}

Do NOT include any extra markdown formatting or backticks outside the JSON. Return only the raw JSON.
"""


def _heuristic_fallback(content_info: Dict[str, Any]) -> Dict[str, Any]:
    """Fallback if AI API call fails or is unavailable."""
    title = content_info.get("title", "Saved Item")
    ctype = content_info.get("content_type", "article")
    raw_dur = content_info.get("duration_minutes", 25)
    
    fixed = content_info.get("fixed_event")
    is_fixed = bool(fixed and fixed.get("start_iso"))
    start_iso = fixed.get("start_iso") if is_fixed else None
    end_iso = fixed.get("end_iso") if is_fixed else None
    
    if is_fixed:
        ctype = "event"
        est_min = fixed.get("duration_minutes", 30)
    else:
        est_min = max(((raw_dur + 14) // 15) * 15, 15)

    window = "evening" if ctype == "video" else ("morning" if ctype == "paper" else "anytime")
    desc = content_info.get("description", "").strip()
    summary = desc[:180] + "..." if len(desc) > 180 else (desc or f"Scheduled {ctype} for your queue.")

    return {
        "clean_title": title[:80],
        "content_type": ctype,
        "is_fixed_event": is_fixed,
        "event_start_iso": start_iso,
        "event_end_iso": end_iso,
        "estimated_minutes": est_min,
        "preferred_window": window,
        "one_line_summary": summary,
        "key_takeaways": [
            f"Review content from {content_info.get('creator', 'source')}",
            "Focus on high-value points and implementation ideas",
            f"Allocated {est_min} minute focus block"
        ],
        "why_it_matters": f"Valuable {ctype} curated for deep focus.",
        "ai_powered": False
    }


def analyze_with_ai(content_info: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze content using OpenRouter LLM with fallback."""
    cfg = load_config()
    api_key = cfg.get("openrouter_api_key")
    model = cfg.get("openrouter_model", "meta-llama/llama-3.3-70b-instruct")

    if not api_key:
        return _heuristic_fallback(content_info)

    now_local = datetime.now().astimezone().isoformat()
    tz_str = cfg.get("user_timezone", "Asia/Kolkata")

    user_prompt = f"""User Context:
Current Local Time: {now_local} ({tz_str})

Content Information:
Title: {content_info.get('title')}
Creator/Source: {content_info.get('creator')}
Type Hint: {content_info.get('content_type')}
Raw Duration: {content_info.get('duration_minutes')} minutes
URL: {content_info.get('url')}
Content Details & Timings:
{content_info.get('description', '')[:3000]}
"""

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://forwardbin.local",
        "X-Title": "ForwardBin Jarvis"
    }

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": 600,
        "temperature": 0.2
    }

    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=20
        )
        if resp.status_code == 200:
            raw_text = resp.json()["choices"][0]["message"]["content"].strip()
            # Clean possible markdown fences
            if raw_text.startswith("```"):
                raw_text = re.sub(r"^```(?:json)?\n?", "", raw_text)
                raw_text = re.sub(r"\n?```$", "", raw_text)
            
            data = json.loads(raw_text)
            data["ai_powered"] = True
            
            # Ensure estimated_minutes is reasonable
            dur = data.get("estimated_minutes", content_info.get("duration_minutes", 30))
            data["estimated_minutes"] = max(int(dur), 15)
            return data
    except Exception as e:
        print(f"[ForwardBin AI Brain] API warning: {e}, using heuristic fallback")

    return _heuristic_fallback(content_info)
