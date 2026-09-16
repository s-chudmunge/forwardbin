use chrono::{DateTime, Duration, Local, NaiveTime, Timelike};
use rusqlite::Connection;
use url::form_urlencoded;
use crate::config::Config;
use crate::db;

pub fn find_next_available_slot(
    conn: &Connection,
    cfg: &Config,
    duration_minutes: i64,
    _preferred_window: &str,
) -> (DateTime<Local>, DateTime<Local>) {
    let now = Local::now();
    let start_hour = cfg.preferred_hours.start;
    let end_hour = cfg.preferred_hours.end;

    // Fetch existing busy slots from DB
    let existing_items = db::list_items(conn, Some("scheduled")).unwrap_or_default();
    let mut busy_intervals: Vec<(DateTime<Local>, DateTime<Local>)> = Vec::new();
    for it in existing_items {
        if let (Ok(s), Ok(e)) = (
            DateTime::parse_from_rfc3339(&it.scheduled_start),
            DateTime::parse_from_rfc3339(&it.scheduled_end),
        ) {
            busy_intervals.push((s.with_timezone(&Local), e.with_timezone(&Local)));
        }
    }

    // Round current time up to the next 15-minute block
    let rem_mins = 15 - (now.minute() % 15);
    let mut cand_start = now + Duration::minutes(rem_mins as i64) - Duration::seconds(now.second() as i64);

    for _day_offset in 0..14 {
        let day_date = cand_start.date_naive();
        let day_start = day_date
            .and_time(NaiveTime::from_hms_opt(start_hour, 0, 0).unwrap())
            .and_local_timezone(Local)
            .unwrap();
        let day_end = day_date
            .and_time(NaiveTime::from_hms_opt(end_hour, 0, 0).unwrap())
            .and_local_timezone(Local)
            .unwrap();

        if cand_start < day_start {
            cand_start = day_start;
        }

        while cand_start + Duration::minutes(duration_minutes) <= day_end {
            let cand_end = cand_start + Duration::minutes(duration_minutes);
            let mut conflict = false;

            for (bs, be) in &busy_intervals {
                if cand_start < *be && cand_end > *bs {
                    cand_start = *be;
                    conflict = true;
                    break;
                }
            }

            if !conflict {
                return (cand_start, cand_end);
            }
        }

        // Advance to next day at start_hour
        cand_start = (cand_start + Duration::days(1))
            .date_naive()
            .and_time(NaiveTime::from_hms_opt(start_hour, 0, 0).unwrap())
            .and_local_timezone(Local)
            .unwrap();
    }

    let def_start = now + Duration::hours(1);
    let def_end = def_start + Duration::minutes(duration_minutes);
    (def_start, def_end)
}

pub fn generate_gcal_link(
    title: &str,
    start: &DateTime<Local>,
    end: &DateTime<Local>,
    details: &str,
    location: &str,
) -> String {
    let fmt = "%Y%m%dT%H%M%SZ";
    let dates = format!("{}/{}", start.to_utc().format(fmt), end.to_utc().format(fmt));

    let encoded_params: String = form_urlencoded::Serializer::new(String::new())
        .append_pair("action", "TEMPLATE")
        .append_pair("text", title)
        .append_pair("dates", &dates)
        .append_pair("details", details)
        .append_pair("location", location)
        .finish();

    format!("https://calendar.google.com/calendar/render?{}", encoded_params)
}

pub fn generate_ics_content(
    title: &str,
    start: &DateTime<Local>,
    end: &DateTime<Local>,
    summary: &str,
    url: &str,
) -> String {
    let fmt = "%Y%m%dT%H%M%SZ";
    let dtstamp = Local::now().to_utc().format(fmt).to_string();
    let dtstart = start.to_utc().format(fmt).to_string();
    let dtend = end.to_utc().format(fmt).to_string();
    let uid = format!("{}-forwardbin@local", start.timestamp());

    format!(
        "BEGIN:VCALENDAR\r\n\
VERSION:2.0\r\n\
PRODID:-//ForwardBin Jarvis//Linux//EN\r\n\
METHOD:REQUEST\r\n\
BEGIN:VEVENT\r\n\
UID:{uid}\r\n\
DTSTAMP:{dtstamp}\r\n\
DTSTART:{dtstart}\r\n\
DTEND:{dtend}\r\n\
SUMMARY:{title}\r\n\
DESCRIPTION:{summary}\\n\\nLink: {url}\r\n\
URL:{url}\r\n\
STATUS:CONFIRMED\r\n\
END:VEVENT\r\n\
END:VCALENDAR\r\n"
    )
}
