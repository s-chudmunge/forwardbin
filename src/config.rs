use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PreferredHours {
    pub start: u32,
    pub end: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FloatingWindowConfig {
    pub x: i32,
    pub y: i32,
    pub opacity: f32,
    pub theme: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Config {
    pub openrouter_api_key: String,
    pub openrouter_model: String,
    pub resend_api_key: String,
    pub resend_sender: String,
    pub user_email: String,
    pub youtube_api_key: String,
    pub gcal_ical_feed_url: String,
    pub user_timezone: String,
    pub preferred_hours: PreferredHours,
    pub notify_minutes_before: u32,
    pub send_instant_booking_email: bool,
    pub send_slot_up_email: bool,
    pub send_desktop_notification: bool,
    pub auto_add_to_gnome_calendar: bool,
    pub floating_window: FloatingWindowConfig,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            openrouter_api_key: String::new(),
            openrouter_model: "meta-llama/llama-3.3-70b-instruct".to_string(),
            resend_api_key: String::new(),
            resend_sender: String::new(),
            user_email: String::new(),
            youtube_api_key: String::new(),
            gcal_ical_feed_url: String::new(),
            user_timezone: "Asia/Kolkata".to_string(),
            preferred_hours: PreferredHours { start: 9, end: 22 },
            notify_minutes_before: 15,
            send_instant_booking_email: true,
            send_slot_up_email: true,
            send_desktop_notification: true,
            auto_add_to_gnome_calendar: true,
            floating_window: FloatingWindowConfig {
                x: -1,
                y: -1,
                opacity: 0.95,
                theme: "jarvis-dark".to_string(),
            },
        }
    }
}

pub fn get_config_dir() -> PathBuf {
    let mut path = dirs::home_dir().unwrap_or_else(|| PathBuf::from("/tmp"));
    path.push(".config");
    path.push("forwardbin");
    fs::create_dir_all(&path).ok();
    path
}

pub fn get_data_dir() -> PathBuf {
    let mut path = dirs::home_dir().unwrap_or_else(|| PathBuf::from("/tmp"));
    path.push(".local");
    path.push("share");
    path.push("forwardbin");
    fs::create_dir_all(&path).ok();
    path
}

pub fn get_config_file() -> PathBuf {
    let mut path = get_config_dir();
    path.push("config.json");
    path
}

fn auto_discover_local_keys() -> HashMap<String, String> {
    let home = dirs::home_dir().unwrap_or_default();
    let candidates = [
        home.join("Documents/projects/eulerfold/backend/.env"),
        home.join("eulerfold/backend/.env"),
        home.join(".env"),
    ];
    let mut map = HashMap::new();
    for file in &candidates {
        if file.exists() {
            if let Ok(content) = fs::read_to_string(file) {
                for line in content.lines() {
                    let line = line.trim();
                    if line.starts_with('#') || !line.contains('=') {
                        continue;
                    }
                    let parts: Vec<&str> = line.splitn(2, '=').collect();
                    if parts.len() == 2 {
                        let k = parts[0].trim();
                        let v = parts[1].trim().trim_matches('"').trim_matches('\'').to_string();
                        if (k == "OPENROUTER_PAID_KEY" || k == "OPENROUTER_API_KEY") && !map.contains_key("openrouter_api_key") {
                            map.insert("openrouter_api_key".to_string(), v);
                        } else if k == "RESEND_API_KEY" && !map.contains_key("resend_api_key") {
                            map.insert("resend_api_key".to_string(), v);
                        } else if k == "RESEND_SENDER" && !map.contains_key("resend_sender") {
                            map.insert("resend_sender".to_string(), v);
                        } else if k == "YOUTUBE_API_KEY" && !map.contains_key("youtube_api_key") {
                            map.insert("youtube_api_key".to_string(), v);
                        }
                    }
                }
            }
        }
    }
    map
}

pub fn load_config() -> Config {
    let mut cfg = Config::default();
    let file = get_config_file();
    if file.exists() {
        if let Ok(data) = fs::read_to_string(&file) {
            if let Ok(parsed) = serde_json::from_str::<Config>(&data) {
                cfg = parsed;
            }
        }
    }

    let discovered = auto_discover_local_keys();
    if cfg.openrouter_api_key.is_empty() {
        if let Some(v) = discovered.get("openrouter_api_key") {
            cfg.openrouter_api_key = v.clone();
        }
    }
    if cfg.resend_api_key.is_empty() {
        if let Some(v) = discovered.get("resend_api_key") {
            cfg.resend_api_key = v.clone();
        }
    }
    if cfg.resend_sender.is_empty() {
        if let Some(v) = discovered.get("resend_sender") {
            cfg.resend_sender = v.clone();
        }
    }
    if cfg.youtube_api_key.is_empty() {
        if let Some(v) = discovered.get("youtube_api_key") {
            cfg.youtube_api_key = v.clone();
        }
    }

    // Layer 3: Environment variables override everything (12-Factor App)
    if let Ok(v) = std::env::var("OPENROUTER_API_KEY") {
        if !v.trim().is_empty() { cfg.openrouter_api_key = v.trim().to_string(); }
    }
    if let Ok(v) = std::env::var("RESEND_API_KEY") {
        if !v.trim().is_empty() { cfg.resend_api_key = v.trim().to_string(); }
    }
    if let Ok(v) = std::env::var("RESEND_SENDER") {
        if !v.trim().is_empty() { cfg.resend_sender = v.trim().to_string(); }
    }
    if let Ok(v) = std::env::var("USER_EMAIL") {
        if !v.trim().is_empty() { cfg.user_email = v.trim().to_string(); }
    }
    if let Ok(v) = std::env::var("FORWARDBIN_USER_EMAIL") {
        if !v.trim().is_empty() { cfg.user_email = v.trim().to_string(); }
    }
    if let Ok(v) = std::env::var("YOUTUBE_API_KEY") {
        if !v.trim().is_empty() { cfg.youtube_api_key = v.trim().to_string(); }
    }

    cfg
}

pub fn save_config(cfg: &Config) -> std::io::Result<()> {
    let file = get_config_file();
    let data = serde_json::to_string_pretty(cfg)?;
    fs::write(file, data)
}

pub fn send_desktop_notification(title: &str, body: &str) {
    if cfg!(target_os = "macos") {
        let script = format!(
            r#"display notification "{}" with title "ForwardBin Jarvis" subtitle "{}""#,
            body.replace('"', "\\\""),
            title.replace('"', "\\\"")
        );
        let _ = std::process::Command::new("osascript")
            .args(["-e", &script])
            .spawn();
    } else {
        let _ = std::process::Command::new("notify-send")
            .args(["-a", "ForwardBin Jarvis", "-i", "calendar", title, body])
            .spawn();
    }
}
