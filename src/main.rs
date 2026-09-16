mod ai;
mod calendar;
mod config;
mod daemon;
mod db;
mod emailer;
mod ui;

use clap::{Parser, Subcommand};
use std::process::Command;
use std::time::Duration;

#[derive(Parser)]
#[command(name = "forwardbin")]
#[command(about = "ForwardBin Jarvis (Rust Core) - Smart Content Drop Bin & Scheduler for Linux", long_about = None)]
struct Cli {
    #[command(subcommand)]
    command: Option<Commands>,
}

#[derive(Subcommand)]
enum Commands {
    /// Launch the lightweight floating drag-and-drop Jarvis bin widget
    Ui,
    /// Forward a video link, paper URL, article, or task
    Add { content: String },
    /// Snatch current clipboard contents and schedule immediately
    Clipboard,
    /// List scheduled items
    List {
        #[arg(short, long)]
        all: bool,
    },
    /// Run background notification and email daemon
    Daemon {
        #[arg(short, long, default_value_t = 60)]
        interval: u64,
    },
    /// View or modify configuration
    Config {
        #[arg(long)]
        show: bool,
        #[arg(long)]
        setup: bool,
    },
    /// Interactive onboarding setup wizard
    Setup,
    /// Send a test verification email via Resend
    TestEmail,
    /// Delete a scheduled item by ID
    Delete { item_id: i64 },
}

fn get_clipboard_text() -> String {
    // 1. Fast in-process clipboard snatching (<50µs latency, zero subprocess fork)
    if let Ok(mut clip) = arboard::Clipboard::new() {
        if let Ok(text) = clip.get_text() {
            let trimmed = text.trim();
            if !trimmed.is_empty() {
                return trimmed.to_string();
            }
        }
    }

    // 2. Graceful fallback for headless/remote session environments
    if let Ok(output) = Command::new("wl-paste").arg("--no-newline").output() {
        if output.status.success() {
            let s = String::from_utf8_lossy(&output.stdout).trim().to_string();
            if !s.is_empty() { return s; }
        }
    }
    if let Ok(output) = Command::new("xclip").args(["-selection", "clipboard", "-o"]).output() {
        if output.status.success() {
            let s = String::from_utf8_lossy(&output.stdout).trim().to_string();
            if !s.is_empty() { return s; }
        }
    }
    if let Ok(output) = Command::new("pbpaste").output() {
        if output.status.success() {
            let s = String::from_utf8_lossy(&output.stdout).trim().to_string();
            if !s.is_empty() { return s; }
        }
    }
    String::new()
}

async fn process_content(raw: &str) {
    println!("🤖 Jarvis (Rust) analyzing: {}", raw);
    let cfg = config::load_config();
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(20))
        .build()
        .unwrap_or_default();

    let analysis = ai::analyze_content(&client, &cfg, raw).await;
    println!("✅ AI Classification: [{}] {}", analysis.content_type.to_uppercase(), analysis.title);

    let conn = match db::get_connection() {
        Ok(c) => c,
        Err(e) => {
            eprintln!("Database error: {}", e);
            return;
        }
    };

    let (start_dt, end_dt) = if analysis.is_fixed_event {
        if let (Some(start_iso), Some(end_iso)) = (&analysis.event_start_iso, &analysis.event_end_iso) {
            match (chrono::DateTime::parse_from_rfc3339(start_iso), chrono::DateTime::parse_from_rfc3339(end_iso)) {
                (Ok(s), Ok(e)) => {
                    println!("🎯 Direct event timing confirmed! Scheduled at: {}", s.with_timezone(&chrono::Local));
                    (s.with_timezone(&chrono::Local), e.with_timezone(&chrono::Local))
                }
                _ => calendar::find_next_available_slot(
                    &conn,
                    &cfg,
                    analysis.duration_minutes,
                    &analysis.preferred_window,
                ),
            }
        } else {
            calendar::find_next_available_slot(
                &conn,
                &cfg,
                analysis.duration_minutes,
                &analysis.preferred_window,
            )
        }
    } else {
        calendar::find_next_available_slot(
            &conn,
            &cfg,
            analysis.duration_minutes,
            &analysis.preferred_window,
        )
    };

    let gcal_link = calendar::generate_gcal_link(
        &analysis.title,
        &start_dt,
        &end_dt,
        &analysis.summary,
        raw,
    );

    let start_str = start_dt.to_rfc3339();
    let end_str = end_dt.to_rfc3339();

    match db::add_item(
        &conn,
        raw,
        &analysis.content_type,
        &analysis.title,
        &analysis.summary,
        &analysis.key_takeaways,
        raw,
        analysis.duration_minutes,
        &start_str,
        &end_str,
        &gcal_link,
    ) {
        Ok(id) => {
            println!("📅 Booked Slot: {} ({} mins)", start_dt.format("%Y-%m-%d %I:%M %p"), analysis.duration_minutes);
            println!("🔗 Google Calendar URL: {}", gcal_link);

            let item = db::Item {
                id,
                raw_input: raw.to_string(),
                content_type: analysis.content_type,
                title: analysis.title,
                summary: analysis.summary,
                key_takeaways: analysis.key_takeaways,
                url: raw.to_string(),
                duration_minutes: analysis.duration_minutes,
                scheduled_start: start_str,
                scheduled_end: end_str,
                gcal_link,
                status: "scheduled".to_string(),
                booking_email_sent: false,
                slot_up_email_sent: false,
                created_at: chrono::Local::now().to_rfc3339(),
                updated_at: chrono::Local::now().to_rfc3339(),
            };

            if cfg.send_instant_booking_email {
                if emailer::send_booking_confirmation(&client, &cfg, &item).await {
                    db::mark_booking_email_sent(&conn, id).ok();
                    println!("📧 Instant confirmation brief emailed to: {}", cfg.user_email);
                }
            }

            if cfg.send_desktop_notification {
                let msg = format!("{}\nScheduled for {}", item.title, start_dt.format("%I:%M %p"));
                config::send_desktop_notification("✅ Scheduled in ForwardBin", &msg);
            }
        }
        Err(e) => eprintln!("Failed to save item: {}", e),
    }
}

#[tokio::main]
async fn main() {
    let cli = Cli::parse();

    match cli.command {
        None | Some(Commands::Ui) => {
            if let Err(e) = ui::run_ui() {
                eprintln!("UI error: {}", e);
            }
        }
        Some(Commands::Add { content }) => {
            process_content(&content).await;
        }
        Some(Commands::Clipboard) => {
            let text = get_clipboard_text();
            if text.is_empty() {
                eprintln!("⚠️ Clipboard is empty or contains non-text content.");
                std::process::exit(1);
            }
            println!("📋 Snatched from clipboard: {}...", &text[..text.len().min(70)]);
            process_content(&text).await;
        }
        Some(Commands::List { all }) => {
            if let Ok(conn) = db::get_connection() {
                let status_filter = if all { None } else { Some("scheduled") };
                if let Ok(items) = db::list_items(&conn, status_filter) {
                    if items.is_empty() {
                        println!("No items found.");
                        return;
                    }
                    println!("\n{:<4} {:<8} {:<24} {:<9} {}", "ID", "Type", "Scheduled Slot", "Duration", "Title");
                    println!("{}", "-".repeat(80));
                    for it in items {
                        let disp_time = match chrono::DateTime::parse_from_rfc3339(&it.scheduled_start) {
                            Ok(dt) => dt.format("%Y-%m-%d %I:%M %p").to_string(),
                            Err(_) => it.scheduled_start.clone(),
                        };
                        let dur = format!("{}m", it.duration_minutes);
                        let title = if it.title.len() > 35 { format!("{}...", &it.title[..32]) } else { it.title.clone() };
                        println!("{:<4} {:<8} {:<24} {:<9} {}", it.id, it.content_type.to_uppercase(), disp_time, dur, title);
                    }
                    println!();
                }
            }
        }
        Some(Commands::Daemon { interval }) => {
            daemon::run_daemon_loop(interval).await;
        }
        Some(Commands::Setup) => {
            run_setup_wizard();
        }
        Some(Commands::Config { show: _, setup }) => {
            if setup {
                run_setup_wizard();
                return;
            }
            let cfg = config::load_config();
            let mut disp = serde_json::to_value(&cfg).unwrap_or_default();
            if let Some(obj) = disp.as_object_mut() {
                for k in ["openrouter_api_key", "resend_api_key", "youtube_api_key"] {
                    if let Some(val) = obj.get_mut(k) {
                        if let Some(s) = val.as_str() {
                            if s.len() > 8 {
                                *val = serde_json::Value::String(format!("{}...", &s[..8]));
                            }
                        }
                    }
                }
            }
            println!("\nForwardBin Configuration (Rust Core):");
            println!("{}", serde_json::to_string_pretty(&disp).unwrap());
        }
        Some(Commands::TestEmail) => {
            let cfg = config::load_config();
            let client = reqwest::Client::new();
            let sample = db::Item {
                id: 999,
                raw_input: "https://en.wikipedia.org/wiki/Rust_(programming_language)".to_string(),
                content_type: "article".to_string(),
                title: "Rust Core Test Verification".to_string(),
                summary: "This is a test notification confirming your Rust ForwardBin email pipeline is operational.".to_string(),
                key_takeaways: vec![
                    "Zero-overhead compiled native Rust binary".to_string(),
                    "Instant sub-millisecond execution".to_string(),
                    "Under 10MB memory footprint".to_string(),
                ],
                url: "https://rust-lang.org".to_string(),
                duration_minutes: 20,
                scheduled_start: chrono::Local::now().to_rfc3339(),
                scheduled_end: chrono::Local::now().to_rfc3339(),
                gcal_link: "https://calendar.google.com".to_string(),
                status: "scheduled".to_string(),
                booking_email_sent: false,
                slot_up_email_sent: false,
                created_at: chrono::Local::now().to_rfc3339(),
                updated_at: chrono::Local::now().to_rfc3339(),
            };
            println!("Sending test verification email to {}...", cfg.user_email);
            if emailer::send_booking_confirmation(&client, &cfg, &sample).await {
                println!("✅ Success! Verification email sent from Rust binary.");
            } else {
                eprintln!("❌ Failed to send email. Check API key and sender configuration.");
            }
        }
        Some(Commands::Delete { item_id }) => {
            if let Ok(conn) = db::get_connection() {
                if let Ok(true) = db::delete_item(&conn, item_id) {
                    println!("✅ Deleted item {}", item_id);
                } else {
                    println!("⚠️ Item {} not found", item_id);
                }
            }
        }
    }
}

fn run_setup_wizard() {
    use std::io::{self, Write};
    let mut cfg = config::load_config();

    println!("\n╔══════════════════════════════════════════════════════════════════╗");
    println!("║       ⚡ Welcome to ForwardBin Jarvis - Quick Setup Wizard       ║");
    println!("╚══════════════════════════════════════════════════════════════════╝\n");
    println!("Configure your scheduling assistant in 30 seconds:\n");

    let curr_email = if cfg.user_email.is_empty() { "none" } else { &cfg.user_email };
    print!("1. Recipient Email for reminders & bookings [{}]: ", curr_email);
    io::stdout().flush().ok();
    let mut email = String::new();
    io::stdin().read_line(&mut email).ok();
    let email = email.trim();
    if !email.is_empty() {
        cfg.user_email = email.to_string();
    }

    let curr_resend = if cfg.resend_api_key.is_empty() { "none" } else { "configured" };
    print!("2. Resend API Key (optional, press Enter to skip) [{}]: ", curr_resend);
    io::stdout().flush().ok();
    let mut resend_key = String::new();
    io::stdin().read_line(&mut resend_key).ok();
    let resend_key = resend_key.trim();
    if !resend_key.is_empty() {
        cfg.resend_api_key = resend_key.to_string();
    }

    if !cfg.resend_api_key.is_empty() {
        let curr_sender = if cfg.resend_sender.is_empty() { "onboarding@resend.dev" } else { &cfg.resend_sender };
        print!("3. Resend Sender Address [{}]: ", curr_sender);
        io::stdout().flush().ok();
        let mut sender = String::new();
        io::stdin().read_line(&mut sender).ok();
        let sender = sender.trim();
        if !sender.is_empty() {
            cfg.resend_sender = sender.to_string();
        } else if cfg.resend_sender.is_empty() {
            cfg.resend_sender = "onboarding@resend.dev".to_string();
        }
    }

    let curr_or = if cfg.openrouter_api_key.is_empty() { "none" } else { "configured" };
    print!("4. OpenRouter API Key (optional, for LLaMA 3.3 analysis) [{}]: ", curr_or);
    io::stdout().flush().ok();
    let mut or_key = String::new();
    io::stdin().read_line(&mut or_key).ok();
    let or_key = or_key.trim();
    if !or_key.is_empty() {
        cfg.openrouter_api_key = or_key.to_string();
    }

    print!("5. Local Timezone [{}]: ", cfg.user_timezone);
    io::stdout().flush().ok();
    let mut tz_input = String::new();
    io::stdin().read_line(&mut tz_input).ok();
    let tz_input = tz_input.trim();
    if !tz_input.is_empty() {
        cfg.user_timezone = tz_input.to_string();
    }

    match config::save_config(&cfg) {
        Ok(_) => {
            println!("\n✅ Configuration successfully saved to: ~/.config/forwardbin/config.json");
            println!("💡 Run 'forwardbin test-email' to verify email delivery.");
            println!("💡 Run 'forwardbin ui' to launch your floating desktop bin!\n");
        }
        Err(e) => eprintln!("❌ Failed to save config: {}", e),
    }
}

