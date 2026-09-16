"""
ForwardBin Native Floating Drop Bin for macOS (Tkinter / Cocoa)
Provides a frameless, always-on-top, animated Jarvis orb widget for macOS users.
Zero C dependencies - works out of the box with standard macOS Python.
"""

import sys
import math
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import subprocess

from forwardbin.config import load_config, save_config
from forwardbin.core import process_dropped_content
from forwardbin.db import list_items


class MacOSFloatingBin:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("ForwardBin Jarvis")

        # Frameless and Always-on-Top
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-alpha", 0.94)
        except Exception:
            pass

        # Dimensions & Screen Placement (Bottom-Right corner)
        self.size = 110
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.x = sw - self.size - 40
        self.y = sh - self.size - 60

        cfg = load_config().get("floating_window", {})
        if cfg.get("x", -1) > 0 and cfg.get("y", -1) > 0:
            self.x = min(max(0, cfg["x"]), sw - self.size)
            self.y = min(max(0, cfg["y"]), sh - self.size)

        self.root.geometry(f"{self.size}x{self.size}+{self.x}+{self.y}")

        # Canvas for custom vector drawing
        self.canvas = tk.Canvas(
            self.root,
            width=self.size,
            height=self.size,
            bg="#0d1117",
            highlightthickness=0
        )
        self.canvas.pack(fill="both", expand=True)

        # Animation states
        self.angle = 0.0
        self.pulse = 0.0
        self.status = "idle"  # "idle", "processing", "success"
        self.status_timer = 0

        # Dragging support
        self._drag_start_x = 0
        self._drag_start_y = 0

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Button-2>", self.show_context_menu)  # macOS right-click / two-finger
        self.canvas.bind("<Button-3>", self.show_context_menu)

        # Context Menu
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="📋 Snatch Clipboard", command=self.snatch_clipboard)
        self.menu.add_command(label="📅 Scheduled Queue", command=self.open_queue_summary)
        self.menu.add_separator()
        self.menu.add_command(label="❌ Hide Bin", command=self.root.withdraw)
        self.menu.add_command(label="🚪 Quit ForwardBin", command=self.root.quit)

        self.animate()

    def on_press(self, event):
        self._drag_start_x = event.x
        self._drag_start_y = event.y
        self._press_time = time.time()

    def on_drag(self, event):
        dx = event.x - self._drag_start_x
        dy = event.y - self._drag_start_y
        self.x += dx
        self.y += dy
        self.root.geometry(f"{self.size}x{self.size}+{self.x}+{self.y}")

    def on_release(self, event):
        # Save position to config if moved
        cfg = load_config()
        if "floating_window" not in cfg:
            cfg["floating_window"] = {}
        cfg["floating_window"]["x"] = self.x
        cfg["floating_window"]["y"] = self.y
        save_config(cfg)

        # If it was a quick click rather than a drag, snatch clipboard!
        if getattr(self, "_press_time", 0) and (time.time() - self._press_time < 0.25):
            self.snatch_clipboard()

    def show_context_menu(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def snatch_clipboard(self):
        """Snatch whatever is in the macOS clipboard and schedule."""
        text = ""
        try:
            res = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=2)
            if res.returncode == 0:
                text = res.stdout.strip()
        except Exception:
            pass

        if not text:
            try:
                text = self.root.clipboard_get().strip()
            except Exception:
                pass

        if not text:
            return

        self.process_content_async(text)

    def process_content_async(self, content_str: str):
        self.status = "processing"

        def _worker():
            try:
                res = process_dropped_content(content_str)
                self.status = "success"
                self.status_timer = time.time()
            except Exception as e:
                print(f"[ForwardBin Mac UI] Error processing drop: {e}")
                self.status = "idle"

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def open_queue_summary(self):
        items = list_items(status="scheduled", limit=5)
        if not items:
            messagebox.showinfo("ForwardBin Queue", "Your forward queue is currently empty!")
            return

        msg = "Upcoming Scheduled Slots:\n\n"
        for it in items:
            msg += f"• [{it.get('content_type', 'item').upper()}] {it.get('title')}\n  {it.get('scheduled_start')} ({it.get('duration_minutes')}m)\n\n"

        messagebox.showinfo("ForwardBin Queue", msg)

    def animate(self):
        self.angle += 0.08
        self.pulse += 0.05
        cx, cy = self.size / 2, self.size / 2
        r = (self.size / 2) - 8

        self.canvas.delete("all")

        # Color scheme based on status
        if self.status == "processing":
            ring_color = "#ea580c"
            core_color = "#f97316"
        elif self.status == "success":
            ring_color = "#10b981"
            core_color = "#34d399"
            if time.time() - self.status_timer > 3.0:
                self.status = "idle"
        else:
            ring_color = "#00f2fe"
            core_color = "#0070f3"

        # Outer pulsing glow ring
        glow_r = r + math.sin(self.pulse) * 3
        self.canvas.create_oval(
            cx - glow_r, cy - glow_r, cx + glow_r, cy + glow_r,
            outline=ring_color, width=1.5
        )

        # Inner HUD Circle
        inner_r = r - 10
        self.canvas.create_oval(
            cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r,
            outline="#1e293b", width=2
        )

        # Rotating Arc segments
        deg = math.degrees(self.angle) % 360
        self.canvas.create_arc(
            cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r,
            start=deg, extent=80, outline=core_color, width=3, style="arc"
        )
        self.canvas.create_arc(
            cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r,
            start=deg + 180, extent=80, outline=ring_color, width=3, style="arc"
        )

        # Center energy orb
        center_r = 12 + math.sin(self.pulse * 2) * 2
        self.canvas.create_oval(
            cx - center_r, cy - center_r, cx + center_r, cy + center_r,
            fill=core_color, outline="#ffffff", width=1
        )

        # Center Label: "JARVIS" / Status
        label = "JARVIS" if self.status == "idle" else ("SYNC" if self.status == "processing" else "SAVED")
        self.canvas.create_text(
            cx, cy + 28,
            text=label,
            fill="#94a3b8",
            font=("Helvetica", 8, "bold")
        )

        self.root.after(35, self.animate)

    def run(self):
        self.root.mainloop()


def launch_macos_ui():
    app = MacOSFloatingBin()
    app.run()


if __name__ == "__main__":
    launch_macos_ui()
