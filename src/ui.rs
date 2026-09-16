use std::error::Error;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tiny_skia::{Color, FillRule, LineCap, Paint, PathBuilder, Pixmap, Rect, Stroke, Transform};
use x11rb::connection::Connection;
use x11rb::protocol::xproto::{
    ConnectionExt as _, CreateGCAux, CreateWindowAux, EventMask, ImageFormat, WindowClass,
};
use x11rb::protocol::Event;

pub struct AnimatedBin {
    pub width: u32,
    pub height: u32,
    pub lid_angle: f32,
    pub target_lid_angle: f32,
    pub lid_velocity: f32,
    pub pulse_phase: f32,
    pub reactor_angle: f32,
    pub is_drag_hover: bool,
    pub is_processing: bool,
    pub is_global_dragging: bool,
}

impl AnimatedBin {
    pub fn new(w: u32, h: u32) -> Self {
        Self {
            width: w,
            height: h,
            lid_angle: 0.0,
            target_lid_angle: 0.0,
            lid_velocity: 0.0,
            pulse_phase: 0.0,
            reactor_angle: 0.0,
            is_drag_hover: false,
            is_processing: false,
            is_global_dragging: false,
        }
    }

    pub fn update(&mut self, dt: f32) {
        self.pulse_phase += dt * 2.5;
        if self.is_processing {
            self.reactor_angle += dt * 6.0;
        } else {
            self.reactor_angle += dt * 0.8;
        }

        // Spring physics for lid
        if self.is_drag_hover || self.is_global_dragging {
            self.target_lid_angle = -1.15;
            self.lid_angle += (self.target_lid_angle - self.lid_angle) * (14.0 * dt);
        } else {
            let stiffness = 240.0;
            let damping = 18.0;
            let disp = self.lid_angle - self.target_lid_angle;
            let force = -stiffness * disp - damping * self.lid_velocity;
            self.lid_velocity += force * dt;
            self.lid_angle += self.lid_velocity * dt;

            if self.target_lid_angle == 0.0 && self.lid_angle > 0.08 {
                self.lid_angle = 0.08;
                self.lid_velocity = -self.lid_velocity * 0.4;
            }
        }
    }

    pub fn render(&self, pixmap: &mut Pixmap) {
        pixmap.fill(Color::TRANSPARENT);

        let w = self.width as f32;
        let cx = w / 2.0;
        let top_y = 48.0;
        let bin_h = 62.0;
        let bot_y = top_y + bin_h;
        let top_rx = 30.0;
        let top_ry = 9.0;
        let bot_rx = 24.0;
        let bot_ry = 7.0;

        let mut paint = Paint::default();
        paint.anti_alias = true;

        // 1. Bin Shadow
        let mut shadow_pb = PathBuilder::new();
        shadow_pb.push_oval(
            Rect::from_xywh(cx - bot_rx - 4.0, bot_y + 2.0, (bot_rx + 4.0) * 2.0, (bot_ry + 2.0) * 2.0).unwrap()
        );
        if let Some(path) = shadow_pb.finish() {
            paint.set_color_rgba8(0, 0, 0, 80);
            pixmap.fill_path(&path, &paint, FillRule::Winding, Transform::identity(), None);
        }

        // 2. Bin Body
        let mut body_pb = PathBuilder::new();
        body_pb.move_to(cx - top_rx, top_y);
        body_pb.line_to(cx - bot_rx, bot_y);
        body_pb.line_to(cx + bot_rx, bot_y);
        body_pb.line_to(cx + top_rx, top_y);
        body_pb.close();

        if let Some(path) = body_pb.finish() {
            paint.set_color_rgba8(30, 36, 46, 235);
            pixmap.fill_path(&path, &paint, FillRule::Winding, Transform::identity(), None);

            let stroke = Stroke { width: 1.4, ..Default::default() };
            paint.set_color_rgba8(88, 166, 255, 180);
            pixmap.stroke_path(&path, &paint, &stroke, Transform::identity(), None);
        }

        // 3. Futuristic Arc Reactor Core
        let reactor_y = top_y + bin_h * 0.48;
        let mut reactor_pb = PathBuilder::new();
        reactor_pb.push_circle(cx, reactor_y, 12.0);
        if let Some(path) = reactor_pb.finish() {
            paint.set_color_rgba8(15, 25, 40, 240);
            pixmap.fill_path(&path, &paint, FillRule::Winding, Transform::identity(), None);

            let stroke = Stroke { width: 1.3, ..Default::default() };
            paint.set_color_rgba8(88, 166, 255, 220);
            pixmap.stroke_path(&path, &paint, &stroke, Transform::identity(), None);
        }

        // Reactor Segments
        let pulse = 0.72 + 0.28 * (self.pulse_phase).sin();
        let core_color = if self.is_processing {
            (50, 240, 110)
        } else {
            (88, 190, 255)
        };

        for seg in 0..4 {
            let start_angle = self.reactor_angle + (seg as f32 * std::f32::consts::FRAC_PI_2) + 0.2;
            let end_angle = start_angle + std::f32::consts::FRAC_PI_2 - 0.4;
            let x1 = cx + 8.2 * start_angle.cos();
            let y1 = reactor_y + 8.2 * start_angle.sin();
            let x2 = cx + 8.2 * end_angle.cos();
            let y2 = reactor_y + 8.2 * end_angle.sin();

            let mut seg_pb = PathBuilder::new();
            seg_pb.move_to(x1, y1);
            seg_pb.line_to(x2, y2);
            if let Some(path) = seg_pb.finish() {
                let stroke = Stroke { width: 2.2, ..Default::default() };
                paint.set_color_rgba8(core_color.0, core_color.1, core_color.2, (220.0 * pulse) as u8);
                pixmap.stroke_path(&path, &paint, &stroke, Transform::identity(), None);
            }
        }

        // Chevron forward symbol >>
        let mut chev_pb = PathBuilder::new();
        chev_pb.move_to(cx - 3.5, reactor_y - 4.0);
        chev_pb.line_to(cx + 0.5, reactor_y);
        chev_pb.line_to(cx - 3.5, reactor_y + 4.0);
        chev_pb.move_to(cx + 1.5, reactor_y - 4.0);
        chev_pb.line_to(cx + 5.5, reactor_y);
        chev_pb.line_to(cx + 1.5, reactor_y + 4.0);
        if let Some(path) = chev_pb.finish() {
            let stroke = Stroke { width: 1.5, line_cap: LineCap::Round, ..Default::default() };
            paint.set_color_rgba8(255, 255, 255, (240.0 * pulse) as u8);
            pixmap.stroke_path(&path, &paint, &stroke, Transform::identity(), None);
        }

        // 4. Animated Lid with spring bounce rotation
        let hinge_x = cx - top_rx - 3.0;
        let hinge_y = top_y + 1.5;

        let lid_tf = Transform::from_translate(hinge_x, hinge_y)
            .pre_rotate(self.lid_angle.to_degrees())
            .pre_translate(-hinge_x, -hinge_y);

        let mut lid_pb = PathBuilder::new();
        lid_pb.move_to(cx - top_rx - 4.0, top_y);
        lid_pb.cubic_to(cx - top_rx, top_y - 12.0, cx + top_rx, top_y - 12.0, cx + top_rx + 4.0, top_y);
        lid_pb.close();

        if let Some(path) = lid_pb.finish() {
            paint.set_color_rgba8(35, 45, 60, 245);
            pixmap.fill_path(&path, &paint, FillRule::Winding, lid_tf, None);

            let stroke = Stroke { width: 1.4, ..Default::default() };
            paint.set_color_rgba8(88, 166, 255, 220);
            pixmap.stroke_path(&path, &paint, &stroke, lid_tf, None);
        }
    }
}

pub fn run_ui() -> Result<(), Box<dyn Error>> {
    let (conn, screen_num) = x11rb::connect(None)?;
    let screen = &conn.setup().roots[screen_num];

    let width = 105u16;
    let height = 130u16;
    let x = (screen.width_in_pixels - width - 20) as i16;
    let y = (screen.height_in_pixels - height - 45) as i16;

    let win = conn.generate_id()?;
    conn.create_window(
        x11rb::COPY_DEPTH_FROM_PARENT,
        win,
        screen.root,
        x,
        y,
        width,
        height,
        0,
        WindowClass::INPUT_OUTPUT,
        screen.root_visual,
        &CreateWindowAux::new()
            .background_pixel(screen.black_pixel)
            .override_redirect(1)
            .event_mask(
                EventMask::EXPOSURE
                    | EventMask::BUTTON_PRESS
                    | EventMask::BUTTON_RELEASE
                    | EventMask::POINTER_MOTION
                    | EventMask::STRUCTURE_NOTIFY,
            ),
    )?;

    conn.map_window(win)?;
    conn.flush()?;

    let gc = conn.generate_id()?;
    conn.create_gc(gc, win, &CreateGCAux::new())?;

    let mut bin = AnimatedBin::new(width as u32, height as u32);
    let mut pixmap = Pixmap::new(width as u32, height as u32).unwrap();
    let mut last_tick = Instant::now();

    let running = Arc::new(AtomicBool::new(true));
    println!("[UI] ForwardBin Jarvis (Rust) window launched at ({}, {}) [XWayland Native]", x, y);

    while running.load(Ordering::Relaxed) {
        let now = Instant::now();
        let dt = (now - last_tick).as_secs_f32().min(0.05);
        last_tick = now;

        // Drain pending X11 events without blocking
        while let Some(event) = conn.poll_for_event()? {
            match event {
                Event::ButtonPress(_) => {
                    bin.is_drag_hover = !bin.is_drag_hover;
                }
                Event::DestroyNotify(_) => {
                    running.store(false, Ordering::Relaxed);
                }
                _ => {}
            }
        }

        bin.update(dt);
        bin.render(&mut pixmap);

        // Convert RGBA to BGRX for standard X11 PutImage
        let data = pixmap.data();
        let mut x11_pixels = Vec::with_capacity(data.len());
        for chunk in data.chunks_exact(4) {
            let r = chunk[0];
            let g = chunk[1];
            let b = chunk[2];
            let a = chunk[3];
            // Premultiply over dark background
            let alpha = a as f32 / 255.0;
            let pr = ((r as f32 * alpha) + 13.0 * (1.0 - alpha)) as u8;
            let pg = ((g as f32 * alpha) + 17.0 * (1.0 - alpha)) as u8;
            let pb = ((b as f32 * alpha) + 23.0 * (1.0 - alpha)) as u8;
            x11_pixels.push(pb);
            x11_pixels.push(pg);
            x11_pixels.push(pr);
            x11_pixels.push(0);
        }

        conn.put_image(
            ImageFormat::Z_PIXMAP,
            win,
            gc,
            width,
            height,
            0,
            0,
            0,
            screen.root_depth,
            &x11_pixels,
        )?;
        conn.flush()?;

        // Dynamic Adaptive Sleep: 16ms when animating, 80ms when idle
        let is_animating = bin.lid_angle.abs() > 0.005 || bin.is_drag_hover || bin.is_processing;
        let sleep_ms = if is_animating { 16 } else { 80 };
        std::thread::sleep(Duration::from_millis(sleep_ms));
    }

    Ok(())
}
