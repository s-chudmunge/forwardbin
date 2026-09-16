"""
Animated Drop Bin Widget for ForwardBin Jarvis
Features:
- Realistic / sci-fi animated trash can with an opening and closing lid
- Smooth 60 FPS physics-based animation via Cairo vector graphics
- Opens lid wide with glowing interior vortex when dragging a link or file over it
- Snaps shut with physical bounce when dropped, sucking in particles
- Pulsing front reactor core that spins during AI scheduling
- Always visible (stays on top of all windows), draggable across screen
- Tap to toggle sleek popup queue dashboard
"""

import sys
import os

# Force X11 backend on Linux (XWayland) so window can position at bottom-right corner without compositor centering
if sys.platform != "darwin" and "GDK_BACKEND" not in os.environ:
    os.environ["GDK_BACKEND"] = "x11"

import math
import time
import random
import threading
from datetime import datetime
from typing import List, Dict, Any, Optional

try:
    import cairo
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import Gtk, Gdk, GLib, Pango, PangoCairo
    HAS_GTK3 = True
except Exception:
    HAS_GTK3 = False

from forwardbin.config import load_config, save_config
from forwardbin.core import process_dropped_content
from forwardbin.db import list_items
from forwardbin.daemon import run_check_cycle


class Particle:
    def __init__(self, x: float, y: float, vx: float, vy: float, color: tuple, size: float, life: float):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.color = color
        self.size = size
        self.max_life = life
        self.life = life

    def update(self, dt: float) -> bool:
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.vy += 40.0 * dt  # slight gravity pulling into bin
        self.life -= dt
        return self.life > 0


class AnimatedBinWindow(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_title("ForwardBin Jarvis")
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_keep_above(True)
        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.stick()

        # Compact, unobtrusive canvas dimensions (reduced footprint)
        self.canvas_w = 78
        self.canvas_h = 98
        self.set_default_size(self.canvas_w, self.canvas_h)
        self.set_size_request(self.canvas_w, self.canvas_h)

        # Transparent RGBA visual
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)

        # Connect drawing
        self.connect("draw", self.on_draw)
        self.connect("map-event", lambda w, e: self.position_window())

        # Drag-and-Drop Destination
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

        # Mouse Click and Dragging Handlers
        self._dragging_window = False
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._press_time = 0.0

        self.connect("button-press-event", self.on_button_press)
        self.connect("button-release-event", self.on_button_release)
        self.connect("motion-notify-event", self.on_motion_notify)
        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
        )

        # Animation State Variables
        self.lid_angle = 0.0          # Current angle in radians
        self.target_lid_angle = 0.0   # Target angle (0 = closed, ~ -1.1 rad = open)
        self.lid_velocity = 0.0
        self.is_drag_hover = False
        self.is_processing = False
        self.pulse_phase = 0.0
        self.reactor_angle = 0.0
        self.status_text = ""
        self.status_color = (0.35, 0.65, 1.0)
        self.status_alpha = 0.0
        self.particles: List[Particle] = []
        self.dashboard_window: Optional[Gtk.Window] = None

        # Global Drag Detection & Visibility States
        self.is_global_dragging = False
        self.idle_opacity = 0.9        # Always visible as a sleek desk clock
        self.target_opacity = self.idle_opacity
        self.current_opacity = self.idle_opacity
        self._last_btn1_down = False
        self._drag_origin_x = 0
        self._drag_origin_y = 0
        self._keep_visible_until = 0.0

        # Position Window on screen (default locked to bottom right)
        self.position_window()

        # Dynamic Adaptive Frame Ticker: 60 FPS (16ms) during interactions, throttled (80ms) when idle
        self._last_tick = time.time()
        self._current_interval_ms = 16
        self._ticker_id = GLib.timeout_add(self._current_interval_ms, self.on_animation_tick)

        # Periodic background daemon cycle
        GLib.timeout_add_seconds(60, self.on_daemon_timer)

    def wake_up_high_fps(self):
        """Instantly elevate to 60 FPS (16ms) for fluid animations during user interaction."""
        if self._current_interval_ms != 16:
            self._current_interval_ms = 16
            if hasattr(self, "_ticker_id") and self._ticker_id:
                try:
                    GLib.source_remove(self._ticker_id)
                except Exception:
                    pass
            self._last_tick = time.time()
            self._ticker_id = GLib.timeout_add(16, self.on_animation_tick)

    def position_window(self):
        """Position window cleanly at the bottom-right corner."""
        cfg = load_config()
        fw = cfg.get("floating_window", {})
        saved_x = fw.get("x", -1)
        saved_y = fw.get("y", -1)

        screen = self.get_screen()
        sw = screen.get_width()
        sh = screen.get_height()

        target_x = sw - self.canvas_w - 20
        target_y = sh - self.canvas_h - 45

        # Only use saved coordinates if explicitly moved by user (> 50px)
        if 50 < saved_x < sw - 50 and 50 < saved_y < sh - 50:
            self.move(saved_x, saved_y)
        else:
            self.move(target_x, target_y)

    # -------------------------------------------------------------
    # Animation Ticker (60 FPS) with Global Drag Detection
    # -------------------------------------------------------------
    def on_animation_tick(self):
        now = time.time()
        dt = min(now - self._last_tick, 0.05)
        self._last_tick = now

        # Update pulse and reactor spin
        self.pulse_phase += dt * 3.0
        if self.is_processing:
            self.reactor_angle += dt * 6.0
        else:
            self.reactor_angle += dt * 0.8

        # Default to idle desk clock visibility
        if not self.is_processing and now > self._keep_visible_until:
            self.target_opacity = self.idle_opacity

        # --- GLOBAL DRAG-AND-DROP DETECTION ---
        # Checks if user is holding down left mouse button and dragging anywhere across the OS
        try:
            screen = self.get_screen()
            root = screen.get_root_window()
            seat = self.get_display().get_default_seat()
            if seat and root:
                pointer = seat.get_pointer()
                if pointer:
                    win, px, py, mask = root.get_device_position(pointer)
                    btn1 = bool(mask & Gdk.ModifierType.BUTTON1_MASK)

                    if btn1:
                        if not self._last_btn1_down:
                            self._last_btn1_down = True
                            self._drag_origin_x = px
                            self._drag_origin_y = py
                        else:
                            dist = math.hypot(px - self._drag_origin_x, py - self._drag_origin_y)
                            if dist > 12:  # Drag gesture detected anywhere on OS!
                                self.is_global_dragging = True
                                self.target_opacity = 1.0      # Glow at 100% power!
                                self.target_lid_angle = -1.15  # Swing lid open wide
                                if not self.is_processing:
                                    self.status_text = "Feed Me!"
                                    self.status_color = (0.35, 0.75, 1.0)
                    else:
                        if self._last_btn1_down:
                            self._last_btn1_down = False
                            self.is_global_dragging = False
                            if not self.is_drag_hover:
                                self.target_lid_angle = 0.0
                            if not self.is_processing and now > self._keep_visible_until:
                                self.target_opacity = self.idle_opacity

                    # Proximity hover: boost to 100% if mouse is within 55px of the bin
                    bx, by = self.get_position()
                    dist_to_bin = math.hypot(px - (bx + self.canvas_w / 2), py - (by + self.canvas_h / 2))
                    if dist_to_bin < 55:
                        self.target_opacity = 1.0
        except Exception:
            pass

        # Keep 100% visible if processing or during post-drop confirmation
        if self.is_processing or now < self._keep_visible_until:
            self.target_opacity = 1.0

        # Smooth Opacity Interpolation (fades in and out gracefully)
        self.current_opacity += (self.target_opacity - self.current_opacity) * min(1.0, 16.0 * dt)
        if self.current_opacity < 0.005:
            self.current_opacity = 0.0

        # Lid Physics: spring interpolation
        if self.is_drag_hover or self.is_global_dragging:
            self.target_lid_angle = -1.15  # Open wide (~65 degrees up)
            self.lid_angle += (self.target_lid_angle - self.lid_angle) * (14.0 * dt)
        else:
            # Spring bounce towards 0.0
            stiffness = 240.0
            damping = 18.0
            displacement = self.lid_angle - self.target_lid_angle
            spring_force = -stiffness * displacement
            damping_force = -damping * self.lid_velocity
            acc = spring_force + damping_force
            self.lid_velocity += acc * dt
            self.lid_angle += self.lid_velocity * dt

            # Constrain closed boundary
            if self.target_lid_angle == 0.0 and self.lid_angle > 0.08:
                self.lid_angle = 0.08
                self.lid_velocity = -self.lid_velocity * 0.4

        # Update Particles
        alive_particles = []
        for p in self.particles:
            if p.update(dt):
                alive_particles.append(p)
        self.particles = alive_particles

        # Status text fade
        if self.status_text and self.status_alpha < 1.0:
            self.status_alpha = min(1.0, self.status_alpha + dt * 3.0)
        elif not self.status_text and self.status_alpha > 0.0:
            self.status_alpha = max(0.0, self.status_alpha - dt * 2.0)

        self.queue_draw()

        # Dynamic Adaptive Throttle:
        # High-performance 60 FPS (16ms) during user drag, lid motion, particle effects, or AI processing
        # Relaxed power-saver mode (80ms ~ 12.5 FPS) when resting idle
        anim_in_progress = (
            self.is_drag_hover
            or self.is_global_dragging
            or self.is_processing
            or len(self.particles) > 0
            or abs(self.lid_angle - self.target_lid_angle) > 0.005
            or abs(self.lid_velocity) > 0.005
            or abs(self.current_opacity - self.target_opacity) > 0.008
            or self._dragging_window
            or (now < self._keep_visible_until)
        )

        desired_interval = 16 if anim_in_progress else 100  # 60 FPS active vs 10 FPS idle

        if desired_interval != self._current_interval_ms:
            self._current_interval_ms = desired_interval
            self._ticker_id = GLib.timeout_add(self._current_interval_ms, self.on_animation_tick)
            return False  # Detach previous timer, rescheduled at new interval

        return True

    # -------------------------------------------------------------
    # Cairo Drawing Engine
    # -------------------------------------------------------------
    def on_draw(self, widget, cr: cairo.Context):
        # 1. Clear background transparently
        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)

        # If fully invisible, don't waste GPU/CPU cycles
        if self.current_opacity <= 0.005:
            return

        cr.push_group()

        # Responsive scaling relative to reference dimensions (105 x 130)
        scale = self.canvas_w / 105.0
        cr.scale(scale, scale)

        w = 105.0
        h = 130.0
        cx = w / 2.0

        # Compact Bin Geometry Parameters
        top_y = 48.0
        bin_h = 62.0
        bot_y = top_y + bin_h
        top_rx = 30.0
        top_ry = 9.0
        bot_rx = 24.0
        bot_ry = 7.0

        # A. Ground Shadow
        cr.save()
        cr.translate(cx, bot_y + bot_ry)
        cr.scale(bot_rx * 1.3, bot_ry * 1.3)
        shadow_pat = cairo.RadialGradient(0, 0, 0.2, 0, 0, 1.0)
        shadow_pat.add_color_stop_rgba(0.0, 0, 0, 0, 0.5)
        shadow_pat.add_color_stop_rgba(1.0, 0, 0, 0, 0.0)
        cr.arc(0, 0, 1.0, 0, 2 * math.pi)
        cr.set_source(shadow_pat)
        cr.fill()
        cr.restore()

        # B. Inside Cavity (Visible when lid opens)
        if abs(self.lid_angle) > 0.04:
            openness = min(1.0, abs(self.lid_angle) / 1.0)
            cr.save()
            cr.translate(cx, top_y)
            cr.scale(top_rx, top_ry)
            cavity_pat = cairo.RadialGradient(0, 0, 0.1, 0, 0, 1.0)
            glow_intensity = 0.6 + 0.4 * math.sin(self.pulse_phase)
            cavity_pat.add_color_stop_rgba(0.0, 0.94, 0.62, 0.50, 0.95 * openness * glow_intensity)
            cavity_pat.add_color_stop_rgba(0.5, 0.851, 0.467, 0.341, 0.75 * openness)
            cavity_pat.add_color_stop_rgba(1.0, 0.16, 0.07, 0.05, 0.95)
            cr.arc(0, 0, 1.0, 0, 2 * math.pi)
            cr.set_source(cavity_pat)
            cr.fill()

            # Glowing suction rings inside
            cr.set_source_rgba(0.96, 0.72, 0.60, 0.85 * openness)
            cr.set_line_width(0.07)
            cr.arc(0, 0, 0.65, 0, 2 * math.pi)
            cr.stroke()
            cr.arc(0, 0, 0.35, 0, 2 * math.pi)
            cr.stroke()
            cr.restore()

        # C. Bin Body in Terracotta (#D97757)
        cr.save()
        cr.move_to(cx - top_rx, top_y)
        cr.curve_to(cx - top_rx, top_y + top_ry, cx + top_rx, top_y + top_ry, cx + top_rx, top_y)
        cr.line_to(cx + bot_rx, bot_y)
        cr.curve_to(cx + bot_rx, bot_y + bot_ry, cx - bot_rx, bot_y + bot_ry, cx - bot_rx, bot_y)
        cr.close_path()

        # Terracotta Satin Gradient
        body_pat = cairo.LinearGradient(cx - top_rx, 0, cx + top_rx, 0)
        body_pat.add_color_stop_rgb(0.0, 0.55, 0.23, 0.13)   # left shadow edge
        body_pat.add_color_stop_rgb(0.22, 0.94, 0.60, 0.49)  # specular highlight sheen
        body_pat.add_color_stop_rgb(0.50, 0.851, 0.467, 0.341) # logo terracotta (#D97757)
        body_pat.add_color_stop_rgb(0.80, 0.77, 0.36, 0.23)  # mid shadow
        body_pat.add_color_stop_rgb(1.0, 0.48, 0.18, 0.10)   # right shadow edge
        cr.set_source(body_pat)
        cr.fill_preserve()

        # Outer border
        border_glow = 0.95 if self.is_drag_hover else (0.55 if not self.is_processing else 0.95)
        cr.set_source_rgba(0.95, 0.65, 0.52, border_glow)
        cr.set_line_width(1.4)
        cr.stroke()

        # Vertical Futuristic Ribs
        for rib_frac in [-0.52, -0.24, 0.24, 0.52]:
            rx_t = cx + rib_frac * top_rx
            rx_b = cx + rib_frac * bot_rx
            cr.move_to(rx_t, top_y + 6)
            cr.line_to(rx_b, bot_y - 5)
            cr.set_source_rgba(0.38, 0.14, 0.08, 0.55)
            cr.set_line_width(1.6)
            cr.stroke()
            cr.move_to(rx_t + 0.8, top_y + 6)
            cr.line_to(rx_b + 0.8, bot_y - 5)
            cr.set_source_rgba(0.96, 0.70, 0.58, 0.35)
            cr.set_line_width(0.8)
            cr.stroke()
        cr.restore()

        # D. Central Front Emblem: The ForwardBin Logo Badge
        reactor_y = top_y + bin_h * 0.48
        cr.save()
        cr.translate(cx, reactor_y)

        # Base emblem backing plate (dark metallic circle)
        cr.arc(0, 0, 13.0, 0, 2 * math.pi)
        cr.set_source_rgba(0.14, 0.05, 0.03, 0.92)
        cr.fill_preserve()
        cr.set_source_rgba(0.94, 0.62, 0.50, 0.85)
        cr.set_line_width(1.2)
        cr.stroke()

        # ForwardBin Logo inside the emblem
        pulse = 0.82 + 0.18 * math.sin(self.pulse_phase)
        cr.save()
        scale_factor = 0.20
        cr.scale(scale_factor, scale_factor)
        cr.translate(-50, -50)

        logo_color = (0.2, 0.95, 0.45) if self.is_processing else (1.0, 1.0, 1.0)
        cr.set_source_rgba(logo_color[0], logo_color[1], logo_color[2], 0.96 * pulse)
        cr.set_line_width(11.5)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)

        # Chrono Hopper Arc
        cr.arc(52.5, 50, 33, math.radians(52), math.radians(308))
        cr.stroke()

        # Intake Chevron
        cr.new_path()
        cr.move_to(44.5, 34)
        cr.line_to(60.5, 50)
        cr.line_to(44.5, 66)
        cr.stroke()

        # Forward Vector
        cr.new_path()
        cr.move_to(64.5, 34)
        cr.line_to(80.5, 50)
        cr.line_to(64.5, 66)
        cr.stroke()

        cr.restore()
        cr.restore()

        # E. Top Rim Collar
        cr.save()
        cr.translate(cx, top_y)
        cr.scale(top_rx, top_ry)
        cr.arc(0, 0, 1.0, 0, 2 * math.pi)
        rim_pat = cairo.LinearGradient(-1, 0, 1, 0)
        rim_pat.add_color_stop_rgb(0.0, 0.65, 0.28, 0.18)
        rim_pat.add_color_stop_rgb(0.4, 0.94, 0.62, 0.50)
        rim_pat.add_color_stop_rgb(1.0, 0.55, 0.22, 0.12)
        cr.set_source(rim_pat)
        cr.set_line_width(0.18)
        cr.stroke()
        cr.restore()

        # F. Particles (Falling into bin)
        for p in self.particles:
            alpha = max(0.0, p.life / p.max_life)
            cr.arc(p.x, p.y, p.size, 0, 2 * math.pi)
            cr.set_source_rgba(p.color[0], p.color[1], p.color[2], alpha)
            cr.fill()

        # G. The Animated Lid (Hinged at top-left)
        cr.save()
        hinge_x = cx - top_rx - 3.0
        hinge_y = top_y + 1.5

        cr.translate(hinge_x, hinge_y)
        cr.rotate(self.lid_angle)
        cr.translate(-hinge_x, -hinge_y)

        # Lid Base Dome
        lid_rx = top_rx + 3.0
        lid_ry = top_ry + 1.5
        cr.save()
        cr.translate(cx, top_y - 1.5)
        cr.scale(lid_rx, lid_ry)
        cr.arc(0, 0, 1.0, 0, 2 * math.pi)
        lid_pat = cairo.LinearGradient(-1, 0, 1, 0)
        lid_pat.add_color_stop_rgb(0.0, 0.58, 0.24, 0.14)
        lid_pat.add_color_stop_rgb(0.3, 0.94, 0.60, 0.48)
        lid_pat.add_color_stop_rgb(0.7, 0.851, 0.467, 0.341)
        lid_pat.add_color_stop_rgb(1.0, 0.48, 0.18, 0.10)
        cr.set_source(lid_pat)
        cr.fill_preserve()

        # Glowing lid rim
        cr.set_source_rgba(0.95, 0.65, 0.52, 0.95 if self.is_drag_hover else 0.55)
        cr.set_line_width(0.08)
        cr.stroke()
        cr.restore()

        # Lid Top Handle
        cr.save()
        cr.translate(cx, top_y - 6.0)
        cr.arc(0, 0, 8.0, math.pi, 2 * math.pi)
        cr.set_source_rgba(0.98, 0.85, 0.78, 0.95)
        cr.set_line_width(2.2)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.stroke()

        cr.arc(-7.0, 0, 1.6, 0, 2 * math.pi)
        cr.arc(7.0, 0, 1.6, 0, 2 * math.pi)
        cr.set_source_rgba(0.55, 0.23, 0.13, 1.0)
        cr.fill()
        cr.restore()

        # Hinge pin
        cr.arc(hinge_x, hinge_y, 2.8, 0, 2 * math.pi)
        cr.set_source_rgba(0.38, 0.14, 0.08, 1.0)
        cr.fill_preserve()
        cr.set_source_rgba(0.851, 0.467, 0.341, 0.9)
        cr.set_line_width(1.0)
        cr.stroke()

        cr.restore()

        # H. Floating Status Badge / Toast (Above the bin)
        if self.status_alpha > 0.01 and self.status_text:
            cr.save()
            text_str = self.status_text
            layout = self.create_pango_layout(text_str)
            desc = Pango.FontDescription("Sans Bold 7.5")
            layout.set_font_description(desc)
            p_width, p_height = layout.get_pixel_size()

            box_w = p_width + 14
            box_h = p_height + 6
            box_x = cx - box_w / 2.0
            box_y = 6.0

            # Background Pill
            cr.move_to(box_x + 6, box_y)
            cr.line_to(box_x + box_w - 6, box_y)
            cr.curve_to(box_x + box_w, box_y, box_x + box_w, box_y + box_h, box_x + box_w - 6, box_y + box_h)
            cr.line_to(box_x + 6, box_y + box_h)
            cr.curve_to(box_x, box_y + box_h, box_x, box_y, box_x + 6, box_y)
            cr.close_path()

            cr.set_source_rgba(0.05, 0.08, 0.12, 0.92 * self.status_alpha)
            cr.fill_preserve()
            cr.set_source_rgba(self.status_color[0], self.status_color[1], self.status_color[2], 0.9 * self.status_alpha)
            cr.set_line_width(1.2)
            cr.stroke()

            # Text
            cr.move_to(box_x + 7, box_y + 3)
            cr.set_source_rgba(1.0, 1.0, 1.0, self.status_alpha)
            PangoCairo.show_layout(cr, layout)
            cr.restore()

        # Pop cached group and render with global animated opacity
        cr.pop_group_to_source()
        cr.paint_with_alpha(self.current_opacity)

    # -------------------------------------------------------------
    # Drag & Drop Handlers (The Lid Animation Triggers!)
    # -------------------------------------------------------------
    def on_drag_motion(self, widget, context, x, y, time_stamp):
        self.wake_up_high_fps()
        if not self.is_drag_hover:
            self.is_drag_hover = True
            self.status_text = "Feed Me!"
            self.status_color = (0.851, 0.467, 0.341)
            self.spawn_burst_particles(10, (0.851, 0.467, 0.341))
        Gdk.drag_status(context, Gdk.DragAction.COPY, time_stamp)
        return True

    def on_drag_leave(self, widget, context, time_stamp):
        self.wake_up_high_fps()
        self.is_drag_hover = False
        if not self.is_processing:
            self.status_text = ""
        self.target_lid_angle = 0.0

    def on_drag_data_received(self, widget, context, x, y, data, info, time_stamp):
        self.wake_up_high_fps()
        self.is_drag_hover = False
        self.target_lid_angle = 0.0

        raw_text = data.get_text()
        if not raw_text:
            uris = data.get_uris()
            if uris:
                raw_text = "\n".join(uris)

        if raw_text:
            context.finish(True, False, time_stamp)
            self._keep_visible_until = time.time() + 6.0
            self.target_opacity = 1.0
            # Satisfying physical slam sound/particles
            self.lid_velocity = 8.0  # Slam velocity downwards to cause bounce
            self.spawn_burst_particles(25, (0.95, 0.65, 0.45))
            self.trigger_scheduling_async(raw_text)
        else:
            context.finish(False, False, time_stamp)

    def spawn_burst_particles(self, count: int, color: tuple):
        self.wake_up_high_fps()
        cx = 105.0 / 2.0
        cy = 48.0
        for _ in range(count):
            vx = random.uniform(-25, 25)
            vy = random.uniform(-40, 15)
            size = random.uniform(1.2, 2.4)
            life = random.uniform(0.3, 0.7)
            self.particles.append(Particle(cx + random.uniform(-12, 12), cy, vx, vy, color, size, life))

    # -------------------------------------------------------------
    # Async Scheduling Pipeline
    # -------------------------------------------------------------
    def trigger_scheduling_async(self, content_str: str):
        self.wake_up_high_fps()
        self.is_processing = True
        self.status_text = "Jarvis Analyzing..."
        self.status_color = (0.95, 0.60, 0.40)

        def _worker():
            try:
                result = process_dropped_content(content_str)
                GLib.idle_add(self._on_schedule_finished, result)
            except Exception as e:
                GLib.idle_add(self._on_schedule_error, str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_schedule_finished(self, result: Dict[str, Any]):
        self.is_processing = False
        dur = result.get("duration_minutes", 30)
        try:
            dt = datetime.fromisoformat(result.get("scheduled_start", ""))
            time_str = dt.strftime("%I:%M %p")
        except Exception:
            time_str = "soon"

        self.status_text = f"Booked {time_str} ({dur}m)"
        self.status_color = (0.25, 0.95, 0.45)
        self.spawn_burst_particles(30, (0.3, 0.95, 0.4))
        self._keep_visible_until = time.time() + 5.0
        self.target_opacity = 1.0

        # Clear status after 6 seconds
        GLib.timeout_add_seconds(6, self._clear_status)
        if self.dashboard_window and self.dashboard_window.get_visible():
            self.refresh_dashboard_data()

    def _on_schedule_error(self, err_msg: str):
        self.is_processing = False
        self.status_text = "Scheduling Error"
        self.status_color = (1.0, 0.3, 0.3)
        GLib.timeout_add_seconds(5, self._clear_status)

    def _clear_status(self):
        self.status_text = ""
        return False

    # -------------------------------------------------------------
    # Mouse Move and Dashboard Click Handlers
    # -------------------------------------------------------------
    def on_button_press(self, widget, event):
        self.wake_up_high_fps()
        if event.button == 1:
            self._dragging_window = True
            self._drag_start_x = event.x
            self._drag_start_y = event.y
            self._press_time = time.time()
            return True
        elif event.button == 3:
            self.show_context_menu(event)
            return True
        return False

    def on_button_release(self, widget, event):
        if event.button == 1 and self._dragging_window:
            self._dragging_window = False
            click_duration = time.time() - self._press_time
            dx = abs(event.x - self._drag_start_x)
            dy = abs(event.y - self._drag_start_y)

            # If user dragged deliberately, save coordinates
            if dx > 10 or dy > 10:
                x, y = self.get_position()
                if x > 50 and y > 50:
                    cfg = load_config()
                    cfg["floating_window"]["x"] = x
                    cfg["floating_window"]["y"] = y
                    save_config(cfg)
            elif click_duration < 0.35:
                self.toggle_dashboard()

            return True
        return False

    def on_motion_notify(self, widget, event):
        if self._dragging_window:
            curr_x, curr_y = self.get_position()
            new_x = int(curr_x + (event.x - self._drag_start_x))
            new_y = int(curr_y + (event.y - self._drag_start_y))
            self.move(new_x, new_y)
            if self.dashboard_window and self.dashboard_window.get_visible():
                self.position_dashboard(new_x, new_y)
            return True
        return False

    def show_context_menu(self, event):
        menu = Gtk.Menu()

        item_queue = Gtk.MenuItem(label="📋 View Scheduled Queue")
        item_queue.connect("activate", lambda w: self.toggle_dashboard())
        menu.append(item_queue)

        item_clip = Gtk.MenuItem(label="📎 Snatch Clipboard Now")
        item_clip.connect("activate", lambda w: os.system("forwardbin clipboard &"))
        menu.append(item_clip)

        item_test = Gtk.MenuItem(label="📧 Send Test Email")
        item_test.connect("activate", lambda w: os.system("forwardbin test-email &"))
        menu.append(item_test)

        menu.append(Gtk.SeparatorMenuItem())

        item_quit = Gtk.MenuItem(label="✕ Close ForwardBin")
        item_quit.connect("activate", lambda w: Gtk.main_quit())
        menu.append(item_quit)

        menu.show_all()
        menu.popup(None, None, None, None, event.button, event.time)

    # -------------------------------------------------------------
    # Companion Dashboard Window
    # -------------------------------------------------------------
    def toggle_dashboard(self):
        if self.dashboard_window and self.dashboard_window.get_visible():
            self.dashboard_window.hide()
        else:
            if not self.dashboard_window:
                self.create_dashboard_window()
            self.refresh_dashboard_data()
            x, y = self.get_position()
            self.position_dashboard(x, y)
            self.dashboard_window.show_all()

    def position_dashboard(self, bin_x: int, bin_y: int):
        if not self.dashboard_window:
            return
        # Position to the left or above the bin
        dash_w = 340
        if bin_x > dash_w + 20:
            target_x = bin_x - dash_w - 10
            target_y = max(10, bin_y - 80)
        else:
            target_x = bin_x + self.canvas_w + 10
            target_y = max(10, bin_y - 80)
        self.dashboard_window.move(target_x, target_y)

    def create_dashboard_window(self):
        self.dashboard_window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.dashboard_window.set_title("Jarvis Queue")
        self.dashboard_window.set_keep_above(True)
        self.dashboard_window.set_decorated(False)
        self.dashboard_window.set_skip_taskbar_hint(True)
        self.dashboard_window.set_default_size(340, 360)

        # Style with dark CSS
        css = b"""
        window {
            background-color: #0d1117;
            border: 1px solid rgba(217, 119, 87, 0.45);
            border-radius: 12px;
        }
        .header-title {
            color: #D97757;
            font-weight: 700;
            font-size: 14px;
        }
        .card-row {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 8px;
            padding: 8px 10px;
            margin-bottom: 6px;
        }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        self.dashboard_window.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        vbox.set_margin_top(12)
        vbox.set_margin_bottom(12)
        vbox.set_margin_start(12)
        vbox.set_margin_end(12)
        self.dashboard_window.add(vbox)

        # Header Row
        h_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        t_lbl = Gtk.Label(label="⚡ ForwardBin Jarvis Queue")
        t_lbl.get_style_context().add_class("header-title")
        h_row.pack_start(t_lbl, True, True, 0)

        close_btn = Gtk.Button(label="✕")
        close_btn.set_relief(Gtk.ReliefStyle.NONE)
        close_btn.connect("clicked", lambda b: self.dashboard_window.hide())
        h_row.pack_end(close_btn, False, False, 0)
        vbox.pack_start(h_row, False, False, 0)

        # Quick Add entry
        entry_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.dash_entry = Gtk.Entry()
        self.dash_entry.set_placeholder_text("Paste link & press Enter...")
        self.dash_entry.connect("activate", self.on_dash_manual_submit)
        entry_box.pack_start(self.dash_entry, True, True, 0)

        sub_btn = Gtk.Button(label="Add")
        sub_btn.connect("clicked", self.on_dash_manual_submit)
        entry_box.pack_start(sub_btn, False, False, 0)
        vbox.pack_start(entry_box, False, False, 0)

        # Scrolled Queue
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(220)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.dash_queue_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        scrolled.add(self.dash_queue_box)
        vbox.pack_start(scrolled, True, True, 0)

        # Footer
        cfg = load_config()
        footer = Gtk.Label(label=f"<small style='color:#8b949e;'>Email: {cfg.get('user_email')} | Super+Shift+F</small>")
        footer.set_use_markup(True)
        vbox.pack_start(footer, False, False, 0)

    def on_dash_manual_submit(self, widget):
        text = self.dash_entry.get_text().strip()
        if text:
            self.dash_entry.set_text("")
            self.trigger_scheduling_async(text)

    def refresh_dashboard_data(self):
        if not self.dashboard_window:
            return
        for c in self.dash_queue_box.get_children():
            self.dash_queue_box.remove(c)

        items = list_items(status="scheduled", limit=10)
        if not items:
            lbl = Gtk.Label(label="<small style='color:#8b949e;'>No items in queue.</small>")
            lbl.set_use_markup(True)
            self.dash_queue_box.pack_start(lbl, True, True, 20)
        else:
            for it in items:
                row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                row.get_style_context().add_class("card-row")

                top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                badge_lbl = Gtk.Label(label=f"<b>[{it.get('content_type', 'item').upper()}]</b>")
                badge_lbl.set_use_markup(True)
                top.pack_start(badge_lbl, False, False, 0)

                t = Gtk.Label(label=it.get("title", "Item")[:32])
                t.set_xalign(0)
                t.set_ellipsize(Pango.EllipsizeMode.END)
                top.pack_start(t, True, True, 0)
                row.pack_start(top, False, False, 0)

                sub = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                try:
                    dt = datetime.fromisoformat(it["scheduled_start"])
                    dt_str = dt.strftime("%b %d, %I:%M %p")
                except Exception:
                    dt_str = "Scheduled"
                time_lbl = Gtk.Label(label=f"<small style='color:#8b949e;'>📅 {dt_str} ({it.get('duration_minutes', 30)}m)</small>")
                time_lbl.set_use_markup(True)
                time_lbl.set_xalign(0)
                sub.pack_start(time_lbl, True, True, 0)

                if it.get("url"):
                    open_btn = Gtk.Button(label="Open")
                    open_btn.set_relief(Gtk.ReliefStyle.NONE)
                    u = it["url"]
                    open_btn.connect("clicked", lambda b, target_url=u: os.system(f"xdg-open '{target_url}' &"))
                    sub.pack_end(open_btn, False, False, 0)

                row.pack_start(sub, False, False, 0)
                self.dash_queue_box.pack_start(row, False, False, 0)

        self.dash_queue_box.show_all()

    def on_daemon_timer(self):
        def _check():
            try:
                run_check_cycle()
                if self.dashboard_window and self.dashboard_window.get_visible():
                    GLib.idle_add(self.refresh_dashboard_data)
            except Exception:
                pass
        threading.Thread(target=_check, daemon=True).start()
        return True


def launch_animated_ui():
    if not HAS_GTK3:
        try:
            from forwardbin.ui.macos_bin import launch_macos_ui
            launch_macos_ui()
            return
        except Exception as e:
            print(f"Error launching UI: {e}")
            return

    win = AnimatedBinWindow()
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    launch_animated_ui()
