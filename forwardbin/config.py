"""
ForwardBin Configuration Manager
Handles loading, saving, and auto-detecting credentials and preferences.
"""

import os
import json
from pathlib import Path
from typing import Dict, Any, Optional

CONFIG_DIR = Path.home() / ".config" / "forwardbin"
CONFIG_FILE = CONFIG_DIR / "config.json"
DATA_DIR = Path.home() / ".local" / "share" / "forwardbin"
DATA_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_CONFIG = {
    "openrouter_api_key": "",
    "openrouter_model": "meta-llama/llama-3.3-70b-instruct",
    "resend_api_key": "",
    "resend_sender": "",
    "user_email": "",
    "youtube_api_key": "",
    "gcal_ical_feed_url": "",
    "user_timezone": "Asia/Kolkata",
    "preferred_hours": {
        "start": 9,
        "end": 22,
    },
    "preferred_categories": {
        "video": {"preferred_window": "evening", "default_duration_min": 30},
        "paper": {"preferred_window": "morning", "default_duration_min": 45},
        "article": {"preferred_window": "anytime", "default_duration_min": 20},
        "task": {"preferred_window": "anytime", "default_duration_min": 15}
    },
    "notify_minutes_before": 15,
    "send_instant_booking_email": True,
    "send_slot_up_email": True,
    "send_desktop_notification": True,
    "auto_add_to_gnome_calendar": True,
    "floating_window": {
        "x": -1,
        "y": -1,
        "opacity": 0.9,
        "theme": "jarvis-dark"
    }
}


def _auto_discover_eulerfold_keys() -> Dict[str, str]:
    """Auto-detect keys from known local environment files if not already set."""
    candidates = [
        Path.home() / "Documents" / "projects" / "eulerfold" / "backend" / ".env",
        Path.home() / "eulerfold" / "backend" / ".env",
        Path.home() / "Documents" / "projects" / "eulerfold" / "frontend" / ".env",
    ]
    discovered = {}
    for env_file in candidates:
        if env_file.exists():
            try:
                with open(env_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if "=" in line and not line.startswith("#"):
                            k, v = line.split("=", 1)
                            val = v.strip("\"' ")
                            if k == "OPENROUTER_PAID_KEY" and not discovered.get("openrouter_api_key"):
                                discovered["openrouter_api_key"] = val
                            elif k == "OPENROUTER_API_KEY" and not discovered.get("openrouter_api_key"):
                                discovered["openrouter_api_key"] = val
                            elif k == "RESEND_API_KEY" and not discovered.get("resend_api_key"):
                                discovered["resend_api_key"] = val
                            elif k == "RESEND_SENDER" and not discovered.get("resend_sender"):
                                discovered["resend_sender"] = val
                            elif k == "YOUTUBE_API_KEY" and not discovered.get("youtube_api_key"):
                                discovered["youtube_api_key"] = val
            except Exception:
                pass
    return discovered


def load_config() -> Dict[str, Any]:
    """
    Loads configuration with 12-factor priority:
    1. Environment variables (ideal for CI/CD & containers)
    2. Local user config file (~/.config/forwardbin/config.json)
    3. Auto-discovered local keys
    4. Default fallbacks
    """
    config = DEFAULT_CONFIG.copy()

    # Layer 1: Read local config file if exists
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                config.update(saved)
        except Exception:
            pass

    # Layer 2: Auto-discover from local projects if not present in config file
    discovered = _auto_discover_eulerfold_keys()
    for k, v in discovered.items():
        if not config.get(k) and v:
            config[k] = v

    # Layer 3: Environment variables override everything (12-factor CI/CD compliance)
    env_mapping = {
        "OPENROUTER_API_KEY": "openrouter_api_key",
        "OPENROUTER_MODEL": "openrouter_model",
        "RESEND_API_KEY": "resend_api_key",
        "RESEND_SENDER": "resend_sender",
        "USER_EMAIL": "user_email",
        "FORWARDBIN_USER_EMAIL": "user_email",
        "YOUTUBE_API_KEY": "youtube_api_key",
        "GCAL_ICAL_FEED_URL": "gcal_ical_feed_url",
    }
    for env_var, config_key in env_mapping.items():
        val = os.getenv(env_var)
        if val:
            config[config_key] = val.strip()

    return config


def save_config(config: Dict[str, Any]) -> None:
    """Saves configuration to JSON."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
