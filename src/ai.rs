use std::sync::LazyLock;
use chrono::{DateTime, Duration as ChronoDuration, FixedOffset, Local, NaiveDateTime, TimeZone};
use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::json;
use crate::config::Config;

static RE_OG_TITLE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r#"(?i)<meta\s+property=["']og:title["']\s+content=["']([^"']+)["']"#).unwrap()
});
static RE_TITLE_TAG: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r#"(?i)<title[^>]*>([^<]+)</title>"#).unwrap()
});
static RE_UTC_OFFSET: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r#"UTC\s*([+-]\d{2}):?(\d{2})?"#).unwrap()
});
static RE_TZ_ABBR: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r#"\b(EDT|EST|CDT|CST|MDT|MST|PDT|PST|IST|UTC|GMT)\b"#).unwrap()
});
static RE_FORM_DATE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r#"<input[^>]+(?:id|name)=["'](?:form_date|event_date)["'][^>]+value=["'](\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?)["']"#).unwrap()
});
static RE_UNTIL_TIME: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r#"(?i)until\s+(\d{1,2}:\d{2}\s*[AP]M)"#).unwrap()
});
static RE_OG_DESC: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r#"(?i)<meta\s+property=["']og:description["']\s+content=["']([^"']+)["']"#).unwrap()
});

static TZ_MAP: &[(&str, i32)] = &[
    ("EDT", -4 * 3600),
    ("EST", -5 * 3600),
    ("CDT", -5 * 3600),
    ("CST", -6 * 3600),
    ("MDT", -6 * 3600),
    ("MST", -7 * 3600),
    ("PDT", -7 * 3600),
    ("PST", -8 * 3600),
    ("IST", (5 * 3600) + (30 * 60)),
    ("UTC", 0),
    ("GMT", 0),
];

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AnalysisResult {
    pub content_type: String,
    pub title: String,
    pub summary: String,
    pub key_takeaways: Vec<String>,
    pub duration_minutes: i64,
    pub preferred_window: String,
    #[serde(default)]
    pub is_fixed_event: bool,
    #[serde(default)]
    pub event_start_iso: Option<String>,
    #[serde(default)]
    pub event_end_iso: Option<String>,
}

#[derive(Default)]
struct PageMetadata {
    title: Option<String>,
    description: Option<String>,
    fixed_start: Option<DateTime<Local>>,
    fixed_end: Option<DateTime<Local>>,
    duration_minutes: Option<i64>,
}

async fn fetch_page_metadata(client: &reqwest::Client, url: &str) -> Option<PageMetadata> {
    if !url.starts_with("http://") && !url.starts_with("https://") {
        return None;
    }

    let resp = client
        .get(url)
        .header("User-Agent", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        .send()
        .await
        .ok()?;

    if !resp.status().is_success() {
        return None;
    }

    let html = resp.text().await.ok()?;
    let mut meta = PageMetadata::default();

    // 1. Zero-heap Title extraction using static DFA
    if let Some(cap) = RE_OG_TITLE.captures(&html) {
        meta.title = Some(cap[1].trim().to_string());
    } else if let Some(cap) = RE_TITLE_TAG.captures(&html) {
        meta.title = Some(cap[1].trim().to_string());
    }

    // 2. Timezone offset extraction using static precompiled patterns
    let mut src_offset_secs: i32 = 0;
    let mut found_tz = false;

    if let Some(cap) = RE_UTC_OFFSET.captures(&html) {
        if let Ok(h) = cap[1].parse::<i32>() {
            let m = cap.get(2).and_then(|v| v.as_str().parse::<i32>().ok()).unwrap_or(0);
            src_offset_secs = h * 3600 + (if h >= 0 { m } else { -m }) * 60;
            found_tz = true;
        }
    }

    if !found_tz {
        if let Some(cap) = RE_TZ_ABBR.captures(&html) {
            if let Some(m) = cap.get(1) {
                if let Some(&(_, offset)) = TZ_MAP.iter().find(|(abbr, _)| *abbr == m.as_str()) {
                    src_offset_secs = offset;
                }
            }
        }
    }

    let src_tz = FixedOffset::east_opt(src_offset_secs).unwrap_or_else(|| FixedOffset::east_opt(0).unwrap());

    // 3. Check for form_date value="2026-09-16T10:00:00"
    if let Some(cap) = RE_FORM_DATE.captures(&html) {
        let raw_val = &cap[1];
        let parse_format = if raw_val.len() == 16 { "%Y-%m-%dT%H:%M" } else { "%Y-%m-%dT%H:%M:%S" };
        if let Ok(naive) = NaiveDateTime::parse_from_str(raw_val, parse_format) {
            if let Some(src_dt) = src_tz.from_local_datetime(&naive).single() {
                let local_start = src_dt.with_timezone(&Local);
                let mut dur_mins = 30;

                if let Some(ucap) = RE_UNTIL_TIME.captures(&html) {
                    let end_str = ucap[1].trim();
                    if let Ok(end_time) = chrono::NaiveTime::parse_from_str(end_str, "%I:%M %p") {
                        let end_naive = naive.date().and_time(end_time);
                        if let Some(end_src) = src_tz.from_local_datetime(&end_naive).single() {
                            let diff = (end_src - src_dt).num_minutes();
                            if (5..=480).contains(&diff) {
                                dur_mins = diff;
                            }
                        }
                    }
                }

                let local_end = local_start + ChronoDuration::minutes(dur_mins);
                meta.fixed_start = Some(local_start);
                meta.fixed_end = Some(local_end);
                meta.duration_minutes = Some(dur_mins);
            }
        }
    }

    // 4. Extract description/snippet using static regex
    if let Some(cap) = RE_OG_DESC.captures(&html) {
        let desc = cap[1].replace("&nbsp;", " ").replace("&#xA0;", " ").trim().to_string();
        if !desc.is_empty() {
            meta.description = Some(desc);
        }
    }

    Some(meta)
}

pub async fn analyze_content(client: &reqwest::Client, cfg: &Config, raw_input: &str) -> AnalysisResult {
    let page_meta = fetch_page_metadata(client, raw_input).await;

    // If YouTube URL, probe duration or classify
    let is_yt = raw_input.contains("youtube.com") || raw_input.contains("youtu.be");
    let is_arxiv = raw_input.contains("arxiv.org");

    let api_key = &cfg.openrouter_api_key;
    if api_key.is_empty() {
        return fallback_analysis(raw_input, is_yt, is_arxiv, page_meta);
    }

    let context_title = page_meta.as_ref().and_then(|m| m.title.clone()).unwrap_or_else(|| raw_input.to_string());
    let context_desc = page_meta.as_ref().and_then(|m| m.description.clone()).unwrap_or_default();
    let is_fixed = page_meta.as_ref().map(|m| m.fixed_start.is_some()).unwrap_or(false);

    let prompt = format!(
        r#"You are Jarvis, an ultra-smart executive scheduling assistant on Linux.
Analyze this input dropped into the user's ForwardBin queue:
Input: "{}"
Page Title: "{}"
Details/Description: "{}"
Fixed Event Detected: {}

Return ONLY a valid, raw JSON object with this exact schema (no markdown, no code blocks):
{{
  "content_type": "event" | "video" | "paper" | "article" | "task",
  "title": "Clean concise title",
  "summary": "1-2 punchy sentences describing what this is",
  "key_takeaways": ["takeaway 1", "takeaway 2", "takeaway 3"],
  "duration_minutes": 30,
  "preferred_window": "morning" | "afternoon" | "evening" | "anytime"
}}"#,
        raw_input, context_title, context_desc, is_fixed
    );

    let body = json!({
        "model": cfg.openrouter_model,
        "messages": [
            { "role": "system", "content": "You are a concise AI analyzer that responds only in JSON." },
            { "role": "user", "content": prompt }
        ],
        "temperature": 0.2
    });

    let res = client.post("https://openrouter.ai/api/v1/chat/completions")
        .header("Authorization", format!("Bearer {}", api_key))
        .header("HTTP-Referer", "https://forwardbin.local")
        .header("X-Title", "ForwardBin Jarvis")
        .header("Content-Type", "application/json")
        .json(&body)
        .send()
        .await;

    if let Ok(resp) = res {
        if resp.status().is_success() {
            if let Ok(val) = resp.json::<serde_json::Value>().await {
                if let Some(content) = val["choices"][0]["message"]["content"].as_str() {
                    let cleaned = content.trim().trim_start_matches("```json").trim_start_matches("```").trim_end_matches("```").trim();
                    if let Ok(mut parsed) = serde_json::from_str::<AnalysisResult>(cleaned) {
                        if let Some(pm) = page_meta {
                            if let (Some(s), Some(e)) = (pm.fixed_start, pm.fixed_end) {
                                parsed.is_fixed_event = true;
                                parsed.event_start_iso = Some(s.to_rfc3339());
                                parsed.event_end_iso = Some(e.to_rfc3339());
                                parsed.duration_minutes = pm.duration_minutes.unwrap_or(parsed.duration_minutes);
                                parsed.content_type = "event".to_string();
                            }
                        }
                        return parsed;
                    }
                }
            }
        }
    }

    fallback_analysis(raw_input, is_yt, is_arxiv, page_meta)
}

fn fallback_analysis(raw_input: &str, is_yt: bool, is_arxiv: bool, page_meta: Option<PageMetadata>) -> AnalysisResult {
    if let Some(pm) = page_meta {
        if let (Some(s), Some(e)) = (pm.fixed_start, pm.fixed_end) {
            let title = pm.title.unwrap_or_else(|| "Scheduled Event".to_string());
            let dur = pm.duration_minutes.unwrap_or(30);
            return AnalysisResult {
                content_type: "event".to_string(),
                title,
                summary: pm.description.unwrap_or_else(|| "Live scheduled session.".to_string()),
                key_takeaways: vec![
                    "Attend live scheduled session".to_string(),
                    "Review materials and agenda".to_string(),
                ],
                duration_minutes: dur,
                preferred_window: "anytime".to_string(),
                is_fixed_event: true,
                event_start_iso: Some(s.to_rfc3339()),
                event_end_iso: Some(e.to_rfc3339()),
            };
        } else if let Some(t) = pm.title {
            return AnalysisResult {
                content_type: "article".to_string(),
                title: t,
                summary: pm.description.unwrap_or_else(|| "Scheduled reading in your forward queue.".to_string()),
                key_takeaways: vec!["Review reading list item".to_string()],
                duration_minutes: 25,
                preferred_window: "anytime".to_string(),
                is_fixed_event: false,
                event_start_iso: None,
                event_end_iso: None,
            };
        }
    }

    if is_yt {
        AnalysisResult {
            content_type: "video".to_string(),
            title: "YouTube Video".to_string(),
            summary: format!("Saved video: {}", raw_input),
            key_takeaways: vec!["Watch and take notes".to_string()],
            duration_minutes: 30,
            preferred_window: "evening".to_string(),
            is_fixed_event: false,
            event_start_iso: None,
            event_end_iso: None,
        }
    } else if is_arxiv {
        AnalysisResult {
            content_type: "paper".to_string(),
            title: "Research Paper (arXiv)".to_string(),
            summary: format!("Scientific paper: {}", raw_input),
            key_takeaways: vec!["Deep focus study session".to_string()],
            duration_minutes: 45,
            preferred_window: "morning".to_string(),
            is_fixed_event: false,
            event_start_iso: None,
            event_end_iso: None,
        }
    } else {
        let title = if raw_input.len() > 40 {
            format!("{}...", &raw_input[..37])
        } else {
            raw_input.to_string()
        };
        AnalysisResult {
            content_type: "article".to_string(),
            title,
            summary: "Scheduled reading in your forward queue.".to_string(),
            key_takeaways: vec!["Review reading list item".to_string()],
            duration_minutes: 20,
            preferred_window: "anytime".to_string(),
            is_fixed_event: false,
            event_start_iso: None,
            event_end_iso: None,
        }
    }
}
