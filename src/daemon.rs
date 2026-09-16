use std::process::Command;
use std::time::Duration;
use tokio::time::sleep;
use crate::config::load_config;
use crate::db;
use crate::emailer;

pub async fn run_daemon_loop(poll_interval_secs: u64) {
    println!("[Daemon] ForwardBin Jarvis (Rust) background daemon started (polling every {}s)", poll_interval_secs);
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(15))
        .build()
        .unwrap_or_default();

    loop {
        let cfg = load_config();
        if let Ok(conn) = db::get_connection() {
            let window = cfg.notify_minutes_before as i64;
            if let Ok(upcoming) = db::get_upcoming_slots(&conn, window) {
                for item in upcoming {
                    println!("[Daemon] Slot is UP for: {} (ID {})", item.title, item.id);

                    if cfg.send_slot_up_email {
                        emailer::send_slot_up_alert(&client, &cfg, &item).await;
                    }

                    if cfg.send_desktop_notification {
                        let msg = format!("{}\nReady in your queue!", item.title);
                        Command::new("notify-send")
                            .args(["-a", "ForwardBin Jarvis", "-i", "alarm", "⏰ Time to Focus", &msg])
                            .spawn()
                            .ok();
                    }

                    db::mark_slot_up_email_sent(&conn, item.id).ok();
                }
            }
        }

        sleep(Duration::from_secs(poll_interval_secs)).await;
    }
}
