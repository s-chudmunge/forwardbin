"""
Floating Jarvis ForwardBin UI for Fedora Linux (GNOME Wayland / X11)
Features:
- Sleek, always-on-top floating drop target
- Draggable anywhere on screen, remembers position
- Accepts drag-and-drop of URLs, browser tabs, text, PDFs, files from any app
- Animated status feedback (analyzing, scheduled)
- Expandable mini-dashboard with queue, manual paste, calendar links
"""

import sys
import os
import threading
from datetime import datetime
from typing import Optional

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib, Pango

from forwardbin.config import load_config, save_config
from forwardbin.core import process_dropped_content
from forwardbin.db import list_items
from forwardbin.daemon import run_check_cycle

CSS_STYLE = b"""
window.floating-bin {
    background-color: rgba(13, 17, 23, 0.88);
    border: 2px solid rgba(88, 166, 255, 0.7);
    border-radius: 24px;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.6), 0 0 16px rgba(88, 166, 255, 0.3);
}

window.floating-bin.drag-hover {
    background-color: rgba(22, 27, 34, 0.96);
    border: 2px solid #58a6ff;
    box-shadow: 0 0 24px rgba(88, 166, 255, 0.8);
}

.pill-container {
    padding: 8px 16px;
}

.jarvis-title {
    color: #58a6ff;
    font-weight: 800;
    font-size: 13px;
    letter-spacing: 0.5px;
}

.jarvis-sub {
    color: #8b949e;
    font-size: 11px;
}

.status-label {
    color: #f0f6fc;
    font-size: 12px;
}

.card-item {
    background-color: rgba(33, 38, 45, 0.8);
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 8px 12px;
    margin-bottom: 6px;
}

.badge-video {
    background-color: rgba(240, 136, 62, 0.25);
    color: #f0883e;
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 10px;
    font-weight: 700;
}

.badge-paper {
    background-color: rgba(163, 113, 247, 0.25);
    color: #a371f7;
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 10px;
    font-weight: 700;
}

.badge-article {
    background-color: rgba(88, 166, 255, 0.25);
    color: #58a6ff;
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 10px;
    font-weight: 700;
}

button.jarvis-btn {
    background: #238636;
    color: white;
    font-weight: 600;
    border-radius: 6px;
    padding: 4px 12px;
    border: none;
}

button.jarvis-btn:hover {
    background: #2ea043;
}
"""


class FloatingBinWindow(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_title("ForwardBin Jarvis")
        self.set_keep_above(True)
        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.stick()

        # Transparency support
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)

        self.get_style_context().add_class("floating-bin")

        # Load CSS
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(CSS_STYLE)
        Gtk.StyleContext.add_provider_for_screen(
            screen, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # Drag-and-Drop Destination Setup
        self.drag_dest_set(
            Gtk.DestDefaults.ALL,
            [],
            Gdk.DragAction.COPY | Gdk.DragAction.MOVE
        )
        self.drag_dest_add_uri_targets()
        self.drag_dest_add_text_targets()

        self.connect("drag-motion", self.on_drag_motion)
        self.connect("drag-leave", self.on_drag_leave)
        self.connect("drag-data-received", self.on_drag_data_received)

        # Window Dragging state
        self._dragging_window = False
        self._drag_start_x = 0
        self._drag_start_y = 0
        self.connect("button-press-event", self.on_button_press)
        self.connect("button-release-event", self.on_button_release)
        self.connect("motion-notify-event", self.on_motion_notify)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK |
                        Gdk.EventMask.BUTTON_RELEASE_MASK |
                        Gdk.EventMask.POINTER_MOTION_MASK)

        # UI Layout
        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.main_box.set_name("main-container")
        self.add(self.main_box)

        # Compact Header Pill
        self.pill_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.pill_box.get_style_context().add_class("pill-container")

        # Icon / Status Dot
        self.icon_label = Gtk.Label(label="⚡")
        self.icon_label.set_use_markup(True)
        self.pill_box.pack_start(self.icon_label, False, False, 0)

        # Title & Subtitle in compact layout
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.title_label = Gtk.Label(label="ForwardBin")
        self.title_label.get_style_context().add_class("jarvis-title")
        self.title_label.set_xalign(0)

        self.sub_label = Gtk.Label(label="Drop any link or file")
        self.sub_label.get_style_context().add_class("jarvis-sub")
        self.sub_label.set_xalign(0)

        text_box.pack_start(self.title_label, False, False, 0)
        text_box.pack_start(self.sub_label, False, False, 0)
        self.pill_box.pack_start(text_box, True, True, 0)

        # Expand / Dashboard toggle button
        self.expand_btn = Gtk.Button(label="📋")
        self.expand_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.expand_btn.set_tooltip_text("Open Jarvis Queue & Manual Input")
        self.expand_btn.connect("clicked", self.toggle_dashboard)
        self.pill_box.pack_end(self.expand_btn, False, False, 0)

        self.main_box.pack_start(self.pill_box, False, False, 0)

        # Expanded Dashboard Container (initially hidden)
        self.dashboard_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.dashboard_box.set_margin_start(14)
        self.dashboard_box.set_margin_end(14)
        self.dashboard_box.set_margin_bottom(14)
        self.dashboard_box.set_no_show_all(True)
        self.dashboard_box.hide()

        # Quick Add Input Bar
        entry_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("Paste link, arXiv, or video URL...")
        self.entry.set_hexpand(True)
        self.entry.connect("activate", self.on_manual_submit)
        entry_box.pack_start(self.entry, True, True, 0)

        self.add_btn = Gtk.Button(label="Schedule")
        self.add_btn.get_style_context().add_class("jarvis-btn")
        self.add_btn.connect("clicked", self.on_manual_submit)
        entry_box.pack_start(self.add_btn, False, False, 0)
        self.dashboard_box.pack_start(entry_box, False, False, 0)

        # Upcoming List Label
        q_label = Gtk.Label(label="<b>Scheduled Content Queue</b>")
        q_label.set_use_markup(True)
        q_label.set_xalign(0)
        self.dashboard_box.pack_start(q_label, False, False, 4)

        # Scrolled queue
        self.scrolled = Gtk.ScrolledWindow()
        self.scrolled.set_min_content_height(180)
        self.scrolled.set_max_content_height(260)
        self.scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self.queue_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.scrolled.add(self.queue_box)
        self.dashboard_box.pack_start(self.scrolled, True, True, 0)

        # Footer info
        cfg = load_config()
        footer_label = Gtk.Label(label=f"<small>Email: {cfg.get('user_email')} | Calendar: GNOME &amp; Google</small>")
        footer_label.set_use_markup(True)
        footer_label.set_xalign(0.5)
        self.dashboard_box.pack_start(footer_label, False, False, 4)

        self.main_box.pack_start(self.dashboard_box, True, True, 0)

        # Initial Positioning
        self.position_window()

        # Start background timer for daemon checking and queue refresh
        GLib.timeout_add_seconds(60, self.on_background_timer)

    def position_window(self):
        """Position window at bottom-right corner or saved coordinates."""
        cfg = load_config()
        fw = cfg.get("floating_window", {})
        saved_x = fw.get("x", -1)
        saved_y = fw.get("y", -1)

        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        if monitor:
            geom = monitor.get_geometry()
            if saved_x > 0 and saved_y > 0 and saved_x < geom.width and saved_y < geom.height:
                self.move(saved_x, saved_y)
            else:
                # Default bottom-right corner with 30px margin
                self.move(geom.width - 240, geom.height - 120)
        else:
            self.move(100, 100)

    # Drag and Drop handlers
    def on_drag_motion(self, widget, context, x, y, time):
        self.get_style_context().add_class("drag-hover")
        self.sub_label.set_text("Release to Forward!")
        Gdk.drag_status(context, Gdk.DragAction.COPY, time)
        return True

    def on_drag_leave(self, widget, context, time):
        self.get_style_context().remove_class("drag-hover")
        self.sub_label.set_text("Drop any link or file")

    def on_drag_data_received(self, widget, context, x, y, data, info, time):
        self.get_style_context().remove_class("drag-hover")
        raw_text = data.get_text()
        if not raw_text:
            uris = data.get_uris()
            if uris:
                raw_text = "\n".join(uris)

        if raw_text:
            context.finish(True, False, time)
            self.trigger_scheduling_async(raw_text)
        else:
            context.finish(False, False, time)

    # Window Dragging / Moving handlers
    def on_button_press(self, widget, event):
        if event.button == 1:
            self._dragging_window = True
            self._drag_start_x = event.x
            self._drag_start_y = event.y
            return True
        return False

    def on_button_release(self, widget, event):
        if event.button == 1 and self._dragging_window:
            self._dragging_window = False
            # Save position
            x, y = self.get_position()
            cfg = load_config()
            cfg["floating_window"]["x"] = x
            cfg["floating_window"]["y"] = y
            save_config(cfg)
            return True
        return False

    def on_motion_notify(self, widget, event):
        if self._dragging_window:
            curr_x, curr_y = self.get_position()
            new_x = int(curr_x + (event.x - self._drag_start_x))
            new_y = int(curr_y + (event.y - self._drag_start_y))
            self.move(new_x, new_y)
            return True
        return False

    def toggle_dashboard(self, button):
        if self.dashboard_box.get_visible():
            self.dashboard_box.hide()
            self.expand_btn.set_label("📋")
            self.resize(1, 1)
        else:
            self.refresh_queue_ui()
            self.dashboard_box.show_all()
            self.expand_btn.set_label("✕")

    def on_manual_submit(self, widget):
        text = self.entry.get_text().strip()
        if text:
            self.entry.set_text("")
            self.trigger_scheduling_async(text)

    def trigger_scheduling_async(self, content_str: str):
        """Runs the AI and scheduling pipeline in a background thread."""
        self.icon_label.set_text("⏳")
        self.sub_label.set_text("Jarvis is scheduling...")

        def _worker():
            try:
                res = process_dropped_content(content_str)
                GLib.idle_add(self._on_schedule_finished, res)
            except Exception as e:
                GLib.idle_add(self._on_schedule_error, str(e))

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def _on_schedule_finished(self, result):
        self.icon_label.set_text("✅")
        title = result.get("title", "Item")
        dur = result.get("duration_minutes", 30)
        try:
            dt = datetime.fromisoformat(result.get("scheduled_start", ""))
            time_str = dt.strftime("%I:%M %p")
        except Exception:
            time_str = "soon"

        self.sub_label.set_text(f"Booked for {time_str} ({dur}m)")
        self.refresh_queue_ui()

        # Reset label back to normal after 5 seconds
        GLib.timeout_add_seconds(5, self._reset_labels)

    def _on_schedule_error(self, err_msg):
        self.icon_label.set_text("❌")
        self.sub_label.set_text("Scheduling error")
        print(f"[UI] Error: {err_msg}")
        GLib.timeout_add_seconds(5, self._reset_labels)

    def _reset_labels(self):
        self.icon_label.set_text("⚡")
        self.sub_label.set_text("Drop any link or file")
        return False

    def refresh_queue_ui(self):
        """Populates the upcoming scheduled items in the dashboard."""
        for child in self.queue_box.get_children():
            self.queue_box.remove(child)

        items = list_items(status="scheduled", limit=10)
        if not items:
            empty_lbl = Gtk.Label(label="<small>No pending items in queue.</small>")
            empty_lbl.set_use_markup(True)
            self.queue_box.pack_start(empty_lbl, True, True, 10)
        else:
            for item in items:
                card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                card.get_style_context().add_class("card-item")

                top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                badge = Gtk.Label(label=item.get("content_type", "item").upper())
                badge.get_style_context().add_class(f"badge-{item.get('content_type', 'article')}")
                top_row.pack_start(badge, False, False, 0)

                t_lbl = Gtk.Label(label=item.get("title", "Item")[:36])
                t_lbl.set_ellipsize(Pango.EllipsizeMode.END)
                t_lbl.set_xalign(0)
                top_row.pack_start(t_lbl, True, True, 0)

                card.pack_start(top_row, False, False, 0)

                try:
                    s_dt = datetime.fromisoformat(item["scheduled_start"])
                    slot_txt = s_dt.strftime("%b %d, %I:%M %p")
                except Exception:
                    slot_txt = "Scheduled"

                sub_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                time_lbl = Gtk.Label(label=f"<small style='color:#8b949e;'>📅 {slot_txt} ({item.get('duration_minutes', 30)}m)</small>")
                time_lbl.set_use_markup(True)
                time_lbl.set_xalign(0)
                sub_row.pack_start(time_lbl, True, True, 0)

                if item.get("url"):
                    open_btn = Gtk.Button(label="Open")
                    open_btn.set_relief(Gtk.ReliefStyle.NONE)
                    url_to_open = item["url"]
                    open_btn.connect("clicked", lambda b, u=url_to_open: os.system(f"xdg-open '{u}' &"))
                    sub_row.pack_end(open_btn, False, False, 0)

                card.pack_start(sub_row, False, False, 0)
                self.queue_box.pack_start(card, False, False, 0)

        self.queue_box.show_all()

    def on_background_timer(self):
        """Run periodic check cycle in background."""
        def _check():
            try:
                run_check_cycle()
                GLib.idle_add(self.refresh_queue_ui)
            except Exception:
                pass
        threading.Thread(target=_check, daemon=True).start()
        return True


def launch_ui():
    """Start the floating bin GTK application."""
    win = FloatingBinWindow()
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    launch_ui()
