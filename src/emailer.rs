use chrono::{DateTime, Local};
use serde_json::json;
use crate::config::Config;
use crate::db::Item;

pub async fn send_booking_confirmation(
    client: &reqwest::Client,
    cfg: &Config,
    item: &Item,
) -> bool {
    let api_key = &cfg.resend_api_key;
    let sender = &cfg.resend_sender;
    let recipient = &cfg.user_email;

    if api_key.is_empty() || sender.is_empty() || recipient.is_empty() {
        return false;
    }

    let start_disp = match DateTime::parse_from_rfc3339(&item.scheduled_start) {
        Ok(dt) => dt.with_timezone(&Local).format("%A, %B %d at %I:%M %p").to_string(),
        Err(_) => item.scheduled_start.clone(),
    };

    let mut takeaways_html = String::new();
    for t in &item.key_takeaways {
        takeaways_html.push_str(&format!(
            r#"<li style="margin-bottom:6px;">{}</li>"#,
            t
        ));
    }

    let ctype = item.content_type.to_lowercase();
    let (badge_bg, badge_fg, badge_border) = if ctype == "video" {
        ("#fff8c5", "#9a6700", "#d4a72c")
    } else if ctype == "paper" {
        ("#fbefff", "#8250df", "#d2a8ff")
    } else if ctype == "event" {
        ("#dafbe1", "#1a7f37", "#4ac26b")
    } else {
        ("#ddf4ff", "#0969da", "#54aeff")
    };

    let takeaways_block = if !takeaways_html.is_empty() {
        format!(
            r#"<div style="margin-top:20px;background:#f6f8fa;padding:16px 20px;border-radius:8px;border:1px solid #d0d7de;border-left:4px solid #0969da;">
                <strong style="color:#0969da;font-size:13px;text-transform:uppercase;letter-spacing:0.5px;">Key Takeaways:</strong>
                <ul style="margin:8px 0 0 0;padding-left:20px;color:#24292f;font-size:14px;line-height:1.6;">
                    {}
                </ul>
            </div>"#,
            takeaways_html
        )
    } else {
        String::new()
    };

    let html_content = format!(
        r#"<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:24px;background-color:#f6f8fa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#1f2328;">
  <div style="max-width:600px;margin:0 auto;background:#ffffff;border:1px solid #d0d7de;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.06);">
    <div style="background:linear-gradient(135deg, #0969da 0%, #054da7 100%);padding:22px 24px;color:#ffffff;">
      <span style="display:inline-block;padding:4px 10px;background:rgba(255,255,255,0.22);border-radius:12px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">Jarvis ForwardBin</span>
      <h1 style="margin:0;font-size:20px;font-weight:700;line-height:1.3;">Slot Booked: {}</h1>
    </div>
    <div style="padding:24px;">
      <div style="display:flex;align-items:center;margin-bottom:18px;">
        <span style="display:inline-block;background:{};color:{};border:1px solid {};padding:4px 12px;border-radius:6px;font-size:12px;font-weight:700;text-transform:uppercase;margin-right:12px;">{}</span>
        <span style="color:#656d76;font-size:14px;">⏱️ Duration: <strong style="color:#1f2328;">{} mins</strong></span>
      </div>
      <div style="background:#f0f7ff;border:1px solid #b6e3ff;padding:16px;border-radius:8px;margin-bottom:20px;">
        <div style="color:#0969da;font-size:12px;text-transform:uppercase;font-weight:700;letter-spacing:0.5px;">Scheduled Time Slot:</div>
        <div style="color:#0969da;font-size:18px;font-weight:700;margin-top:4px;">📅 {}</div>
      </div>
      <div style="margin-bottom:20px;">
        <strong style="color:#1f2328;font-size:14px;">AI Brief:</strong>
        <p style="margin:6px 0 0 0;color:#3c444d;font-size:14px;line-height:1.6;">{}</p>
      </div>
      {}
      <div style="margin-top:28px;padding-top:20px;border-top:1px solid #d0d7de;text-align:center;">
        <a href="{}" style="display:inline-block;background:#1f883d;color:#ffffff;text-decoration:none;padding:12px 22px;border-radius:6px;font-weight:600;font-size:14px;margin-right:10px;margin-bottom:10px;">🔗 Open Resource</a>
        <a href="{}" style="display:inline-block;background:#0969da;color:#ffffff;text-decoration:none;padding:12px 22px;border-radius:6px;font-weight:600;font-size:14px;margin-bottom:10px;">📅 View in Google Calendar</a>
      </div>
      <p style="text-align:center;color:#656d76;font-size:12px;margin-top:22px;">
        Added to your local GNOME Calendar automatically.
      </p>
    </div>
  </div>
</body>
</html>"#,
        item.title,
        badge_bg, badge_fg, badge_border, item.content_type,
        item.duration_minutes,
        start_disp,
        item.summary,
        takeaways_block,
        item.url,
        item.gcal_link
    );

    let body = json!({
        "from": format!("ForwardBin Jarvis <{}>", sender),
        "to": [recipient],
        "subject": format!("📥 [ForwardBin] Scheduled: {} ({})", item.title, start_disp),
        "html": html_content
    });

    let res = client.post("https://api.resend.com/emails")
        .header("Authorization", format!("Bearer {}", api_key))
        .header("Content-Type", "application/json")
        .json(&body)
        .send()
        .await;

    matches!(res, Ok(r) if r.status().is_success())
}

pub async fn send_slot_up_alert(
    client: &reqwest::Client,
    cfg: &Config,
    item: &Item,
) -> bool {
    let api_key = &cfg.resend_api_key;
    let sender = &cfg.resend_sender;
    let recipient = &cfg.user_email;

    if api_key.is_empty() || sender.is_empty() || recipient.is_empty() {
        return false;
    }

    let html_content = format!(
        r#"<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:24px;background-color:#f6f8fa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#1f2328;">
  <div style="max-width:600px;margin:0 auto;background:#ffffff;border:1px solid #d0d7de;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.06);">
    <div style="background:linear-gradient(135deg, #ea580c 0%, #dc2626 100%);padding:22px 24px;color:#ffffff;">
      <span style="display:inline-block;padding:4px 10px;background:rgba(255,255,255,0.22);border-radius:12px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">⏰ Slot Starting Now</span>
      <h1 style="margin:0;font-size:22px;font-weight:700;line-height:1.3;">Time to Focus: {}</h1>
    </div>
    <div style="padding:24px;">
      <p style="font-size:16px;color:#1f2328;margin-top:0;">
        Your scheduled <strong>{}-minute</strong> slot is starting right now!
      </p>
      <div style="background:#fff8f0;border-left:4px solid #ea580c;border:1px solid #fed7aa;padding:16px 20px;border-radius:8px;margin-bottom:24px;">
        <strong style="color:#c2410c;font-size:14px;text-transform:uppercase;letter-spacing:0.5px;">Summary:</strong>
        <p style="margin:6px 0 0 0;color:#374151;font-size:14px;line-height:1.6;">{}</p>
      </div>
      <div style="text-align:center;margin:30px 0 10px 0;">
        <a href="{}" style="display:inline-block;background:#ea580c;color:#ffffff;text-decoration:none;padding:14px 28px;border-radius:8px;font-weight:700;font-size:16px;box-shadow:0 4px 12px rgba(234,88,12,0.3);">
          🚀 Open Content Now
        </a>
      </div>
    </div>
  </div>
</body>
</html>"#,
        item.title, item.duration_minutes, item.summary, item.url
    );

    let body = json!({
        "from": format!("ForwardBin Jarvis <{}>", sender),
        "to": [recipient],
        "subject": format!("⏰ Starting Now: {}", item.title),
        "html": html_content
    });

    let res = client.post("https://api.resend.com/emails")
        .header("Authorization", format!("Bearer {}", api_key))
        .header("Content-Type", "application/json")
        .json(&body)
        .send()
        .await;

    matches!(res, Ok(r) if r.status().is_success())
}
