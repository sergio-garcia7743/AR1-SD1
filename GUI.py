import tkinter as tk
from tkinter import ttk
import serial
import serial.tools.list_ports
import time
import math
import threading

import cv2
from PIL import Image, ImageTk

BAUD_RATE = 115200

ser = None
ready = False
is_animating = False
action_cancelled = False
magnet_on = False
vacuum_on = False
solenoid_on = False
precision_lock = False

# ---------------------------------------------------------
# MANUAL TOOL STATE
# ---------------------------------------------------------
active_tool = None
tool_attached = False

# ---------------------------------------------------------
# BRAND COLORS
# ---------------------------------------------------------
ULTRAMARINE = "#003087"
LANL_BLUE   = "#3296DC"
LIGHT_BLUE  = "#69C3FF"
WHITE       = "#FFFFFF"
BG_APP      = "#E9EDF3"
PANEL_BG    = "#F7F9FC"
CANVAS_BG   = "#F3F7FB"
DARK_GRAY   = "#2F3640"
MID_GRAY    = "#5C6670"
LIGHT_GRAY  = "#C9D2DC"
BORDER      = "#B7C3CF"

SUCCESS        = "#35A853"
SUCCESS_BRIGHT = "#49D16D"
DANGER         = "#D64C4C"

TRACK_BG       = "#D4DBE3"
TRACK_ACTIVE   = LANL_BLUE
TRACK_BLOCKED  = "#E8EEF5"
THUMB_FILL     = WHITE
THUMB_OUTLINE  = ULTRAMARINE
CENTER_MARKER  = "#7C8A99"

TEST_TRACK_ACTIVE  = "#6B8AF7"
TEST_THUMB_OUTLINE = "#304FCF"

SANS    = ("Segoe UI", 10)
SANS_B  = ("Segoe UI", 10, "bold")
SANS_H1 = ("Segoe UI", 14, "bold")
SANS_H2 = ("Segoe UI", 11, "bold")
SANS_S  = ("Segoe UI", 8)

FRAME_MS = 16
MIN_MOTION_STEPS = 35

LINKS = [70, 80, 60, 40, 20]
DEFAULT_ANGLE = 90

WORK_MIN = {
    "base":  20,
    "link1": 30,
    "link2": 25,
    "link3": 25,
    "tool":  0,
    "test":  85,
}
WORK_MAX = {
    "base":  160,
    "link1": 150,
    "link2": 155,
    "link3": 155,
    "tool":  180,
    "test":  95,
}

# ---------------------------------------------------------
# CUSTOM LIMITED SLIDER
# ---------------------------------------------------------
class LimitedSlider(tk.Frame):
    def __init__(
        self,
        parent,
        label,
        full_min=0,
        full_max=180,
        work_min=0,
        work_max=180,
        initial=90,
        command=None,
        width=500,
        height=58,
        active_color=TRACK_ACTIVE,
        thumb_outline=THUMB_OUTLINE
    ):
        super().__init__(parent, bg=PANEL_BG)

        self.full_min = full_min
        self.full_max = full_max
        self.work_min = work_min
        self.work_max = work_max
        self.value = max(self.work_min, min(self.work_max, int(initial)))
        self.command = command
        self.pointer_locked = False

        self.width = width
        self.height = height

        self.left_pad = 16
        self.right_pad = 16
        self.track_y = 33
        self.track_h = 10
        self.thumb_r = 8

        self.active_color = active_color
        self.thumb_outline = thumb_outline

        header = tk.Frame(self, bg=PANEL_BG)
        header.pack(fill="x")

        self.lbl = tk.Label(header, text=label, bg=PANEL_BG, fg=DARK_GRAY, font=SANS_B, anchor="w")
        self.lbl.pack(side="left")

        self.val_var = tk.StringVar(value=f"{self.value}°")
        self.val_lbl = tk.Label(header, textvariable=self.val_var, bg=PANEL_BG, fg=ULTRAMARINE, font=SANS_B, anchor="e")
        self.val_lbl.pack(side="right")

        slider_row = tk.Frame(self, bg=PANEL_BG)
        slider_row.pack(fill="x")

        self.left_btn = tk.Button(
            slider_row,
            text="◀",
            command=self.step_down,
            bg=WHITE,
            fg=DARK_GRAY,
            activebackground="#EAF1F8",
            activeforeground=DARK_GRAY,
            relief="raised",
            bd=1,
            font=("Segoe UI", 9, "bold"),
            width=3,
            cursor="hand2",
            pady=8
        )
        self.left_btn.pack(side="left", padx=(0, 6))

        self.cv = tk.Canvas(
            slider_row,
            width=self.width,
            height=self.height,
            bg=PANEL_BG,
            highlightthickness=0,
            bd=0
        )
        self.cv.pack(side="left", fill="x", expand=True)

        self.right_btn = tk.Button(
            slider_row,
            text="▶",
            command=self.step_up,
            bg=WHITE,
            fg=DARK_GRAY,
            activebackground="#EAF1F8",
            activeforeground=DARK_GRAY,
            relief="raised",
            bd=1,
            font=("Segoe UI", 9, "bold"),
            width=3,
            cursor="hand2",
            pady=8
        )
        self.right_btn.pack(side="left", padx=(6, 0))

        self.cv.bind("<Button-1>", self._click)
        self.cv.bind("<B1-Motion>", self._drag)
        self.cv.bind("<Configure>", self._on_canvas_resize)

        self.draw()
        self.after_idle(self.draw)

    def set_pointer_lock(self, locked: bool):
        self.pointer_locked = locked

    def configure(self, **kwargs):
        if "command" in kwargs:
            self.command = kwargs["command"]

    config = configure

    def _on_canvas_resize(self, _event=None):
        self.draw()

    def _track_x0(self):
        return self.left_pad

    def _track_x1(self):
        w = self.cv.winfo_width()
        if w <= 1:
            w = self.width
        return w - self.right_pad

    def _x_to_val(self, x):
        x0 = self._track_x0()
        x1 = self._track_x1()
        x = max(x0, min(x1, x))
        t = (x - x0) / (x1 - x0)
        v = self.full_min + t * (self.full_max - self.full_min)
        v = round(v)
        v = max(self.work_min, min(self.work_max, v))
        return v

    def _emit_change(self):
        self.val_var.set(f"{self.value}°")
        self.draw()
        if self.command:
            self.command(str(self.value))

    def _set_from_x(self, x):
        new_val = self._x_to_val(x)
        if new_val != self.value:
            self.value = new_val
            self._emit_change()

    def _click(self, e):
        if self.pointer_locked:
            return
        self._set_from_x(e.x)

    def _drag(self, e):
        if self.pointer_locked:
            return
        self._set_from_x(e.x)

    def step_down(self):
        if self.value > self.work_min:
            self.value -= 1
            self._emit_change()

    def step_up(self):
        if self.value < self.work_max:
            self.value += 1
            self._emit_change()

    def set(self, v):
        self.value = max(self.work_min, min(self.work_max, int(v)))
        self.val_var.set(f"{self.value}°")
        self.draw()

    def get(self):
        return int(self.value)

    def draw(self):
        cv = self.cv
        cv.delete("all")

        current_width = self.cv.winfo_width()
        if current_width <= 1:
            current_width = self.width

        x0 = self.left_pad
        x1 = current_width - self.right_pad

        y0 = self.track_y - self.track_h // 2
        y1 = self.track_y + self.track_h // 2

        def val_to_x_dynamic(v):
            t = (v - self.full_min) / (self.full_max - self.full_min)
            return x0 + t * (x1 - x0)

        wx0 = val_to_x_dynamic(self.work_min)
        wx1 = val_to_x_dynamic(self.work_max)

        cv.create_rectangle(x0, y0, x1, y1, fill=TRACK_BG, outline=BORDER, width=1)

        if wx0 > x0:
            cv.create_rectangle(x0, y0, wx0, y1, fill=TRACK_BLOCKED, outline="")
        if wx1 < x1:
            cv.create_rectangle(wx1, y0, x1, y1, fill=TRACK_BLOCKED, outline="")

        cv.create_rectangle(wx0, y0, wx1, y1, fill=self.active_color, outline="")

        cx = val_to_x_dynamic(90)
        cv.create_line(cx, y0 - 5, cx, y1 + 5, fill=CENTER_MARKER, width=1)

        cv.create_text(x0, 12, text=str(self.full_min), fill=MID_GRAY, font=SANS_S, anchor="w")
        cv.create_text(x1, 12, text=str(self.full_max), fill=MID_GRAY, font=SANS_S, anchor="e")
        cv.create_text(wx0, y1 + 13, text=str(self.work_min), fill="#8D99A6", font=SANS_S, anchor="center")
        cv.create_text(wx1, y1 + 13, text=str(self.work_max), fill="#8D99A6", font=SANS_S, anchor="center")

        tx = val_to_x_dynamic(self.value)
        ty = self.track_y
        cv.create_oval(
            tx - self.thumb_r, ty - self.thumb_r,
            tx + self.thumb_r, ty + self.thumb_r,
            fill=THUMB_FILL, outline=self.thumb_outline, width=2
        )

        if self.pointer_locked:
            cv.create_text(
                x1, 12,
                text="LOCKED",
                fill=DANGER,
                font=("Segoe UI", 8, "bold"),
                anchor="e"
            )

# ---------------------------------------------------------
# 3D MATH
# ---------------------------------------------------------
def mat4_identity():
    return [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]

def mat4_mul(a, b):
    r = [0] * 16
    for i in range(4):
        for j in range(4):
            for k in range(4):
                r[i*4+j] += a[i*4+k] * b[k*4+j]
    return r

def rot_y(t):
    c, s = math.cos(t), math.sin(t)
    return [c,0,s,0, 0,1,0,0, -s,0,c,0, 0,0,0,1]

def rot_z(t):
    c, s = math.cos(t), math.sin(t)
    return [c,-s,0,0, s,c,0,0, 0,0,1,0, 0,0,0,1]

def trans_y(d):
    return [1,0,0,0, 0,1,0,d, 0,0,1,0, 0,0,0,1]

def apply_mat(m, p):
    x, y, z = p
    return (
        m[0]*x + m[1]*y + m[2]*z + m[3],
        m[4]*x + m[5]*y + m[6]*z + m[7],
        m[8]*x + m[9]*y + m[10]*z + m[11]
    )

def smoothstep(t):
    return t * t * (3 - 2 * t)

# ---------------------------------------------------------
# 3D ARM VIEW
# ---------------------------------------------------------
class ArmCanvas:
    def __init__(self, parent):
        self.parent = parent
        self.W = 430
        self.H = 520
        self.cv = tk.Canvas(
            parent,
            bg=CANVAS_BG,
            highlightthickness=1,
            highlightbackground=BORDER
        )
        self.cv.pack(fill="both", expand=True)

        self.cam_theta = -math.pi / 4
        self.cam_phi = math.radians(28)
        self.zoom = 1.0
        self.zoom_min = 0.55
        self.zoom_max = 2.50
        self.zoom_step = 1.10

        self._drag_x = None
        self._drag_y = None
        self._angles = [0.0] * 5

        self.show_envelope = False
        self._envelope_points = []
        self._generate_envelope()

        self.cv.bind("<ButtonPress-1>", self._md)
        self.cv.bind("<B1-Motion>", self._mm)
        self.cv.bind("<ButtonRelease-1>", self._mu)
        self.cv.bind("<Configure>", self._on_resize)

        self.cv.bind("<MouseWheel>", self._mousewheel_zoom)
        self.cv.bind("<Button-4>", lambda e: self.zoom_in())
        self.cv.bind("<Button-5>", lambda e: self.zoom_out())

        self.draw()

    def _on_resize(self, e):
        self.W = max(200, e.width)
        self.H = max(200, e.height)
        self.draw()

    def set_angles_from_servos(self, s1, s2, s3, s4, s5):
        self._angles = [
            math.radians(s1 - 90),
            math.radians(-(s2 - 90)),
            math.radians(-(s3 - 90)),
            math.radians(-(s4 - 90)),
            math.radians(s5 - 90),
        ]
        self.draw()

    def zoom_in(self):
        self.zoom = min(self.zoom_max, self.zoom * self.zoom_step)
        self.draw()

    def zoom_out(self):
        self.zoom = max(self.zoom_min, self.zoom / self.zoom_step)
        self.draw()

    def reset_zoom(self):
        self.zoom = 1.0
        self.draw()

    def _mousewheel_zoom(self, e):
        if hasattr(e, "delta") and e.delta != 0:
            if e.delta > 0:
                self.zoom_in()
            else:
                self.zoom_out()

    def _md(self, e):
        self._drag_x, self._drag_y = e.x, e.y

    def _mm(self, e):
        if self._drag_x is None:
            return
        self.cam_theta += (e.x - self._drag_x) * 0.012
        self.cam_phi += (e.y - self._drag_y) * 0.012
        self.cam_phi = max(-1.45, min(1.45, self.cam_phi))
        self._drag_x, self._drag_y = e.x, e.y
        self.draw()

    def _mu(self, _e):
        self._drag_x = None
        self._drag_y = None

    def _project(self, p):
        x, y, z = p
        ca, sa = math.cos(self.cam_theta), math.sin(self.cam_theta)
        cb, sb = math.cos(self.cam_phi), math.sin(self.cam_phi)

        x2 = ca*x + sa*z
        z2 = -sa*x + ca*z
        y2 = cb*y - sb*z2
        z3 = sb*y + cb*z2

        cx, cy = self.W * 0.50, self.H * 0.60
        fov = max(420, min(self.W, self.H) * 0.95) * self.zoom
        sc = fov / (fov + z3 + 300)
        return cx + x2 * sc, cy - y2 * sc, sc

    def _compute_chain(self):
        M = mat4_identity()
        pts = [(0.0, 0.0, 0.0)]
        ops = [
            (rot_y, 0, LINKS[0]),
            (rot_z, 1, LINKS[1]),
            (rot_z, 2, LINKS[2]),
            (rot_z, 3, LINKS[3]),
            (rot_y, 4, LINKS[4]),
        ]
        for fn, ai, lk in ops:
            M = mat4_mul(M, fn(self._angles[ai]))
            M = mat4_mul(M, trans_y(lk))
            pts.append(apply_mat(M, (0, 0, 0)))
        return pts

    def _tcp_from_servos(self, s1, s2, s3, s4, s5):
        angles = [
            math.radians(s1 - 90),
            math.radians(-(s2 - 90)),
            math.radians(-(s3 - 90)),
            math.radians(-(s4 - 90)),
            math.radians(s5 - 90),
        ]
        M = mat4_identity()
        ops = [
            (rot_y, 0, LINKS[0]),
            (rot_z, 1, LINKS[1]),
            (rot_z, 2, LINKS[2]),
            (rot_z, 3, LINKS[3]),
            (rot_y, 4, LINKS[4]),
        ]
        for fn, ai, lk in ops:
            M = mat4_mul(M, fn(angles[ai]))
            M = mat4_mul(M, trans_y(lk))
        return apply_mat(M, (0, 0, 0))

    def _generate_envelope(self):
        pts = []
        s5 = DEFAULT_ANGLE
        for s1 in range(WORK_MIN["base"], WORK_MAX["base"] + 1, 30):
            for s2 in range(WORK_MIN["link1"], WORK_MAX["link1"] + 1, 30):
                for s3 in range(WORK_MIN["link2"], WORK_MAX["link2"] + 1, 30):
                    for s4 in range(WORK_MIN["link3"], WORK_MAX["link3"] + 1, 30):
                        pts.append(self._tcp_from_servos(s1, s2, s3, s4, s5))
        self._envelope_points = pts

    def toggle_envelope(self):
        self.show_envelope = not self.show_envelope
        self.draw()

    def get_tcp_position(self):
        pts = self._compute_chain()
        return pts[-1]

    def draw(self):
        cv = self.cv
        cv.delete("all")

        for i, band in enumerate(range(0, self.H, 8)):
            shade = 243 - i // 6
            shade = max(232, shade)
            col = f"#{shade:02x}{min(255, shade+5):02x}{min(255, shade+10):02x}"
            cv.create_rectangle(0, band, self.W, band + 8, fill=col, outline="")

        N = 6
        step = min(self.W, self.H) * 0.08
        for i in range(-N, N + 1):
            a = self._project((i * step, 0, -N * step))
            b = self._project((i * step, 0,  N * step))
            c = self._project((-N * step, 0, i * step))
            d = self._project(( N * step, 0, i * step))
            col = "#D0D9E3"
            cv.create_line(a[0], a[1], b[0], b[1], fill=col, width=1)
            cv.create_line(c[0], c[1], d[0], d[1], fill=col, width=1)

        o = self._project((0, 0, 0))
        axis_len = N * step
        for tgt, col, lbl in [
            ((axis_len, 0, 0), "#E53935", "X"),
            ((0, axis_len, 0), SUCCESS, "Y"),
            ((0, 0, axis_len), "#2F6BFF", "Z"),
        ]:
            t = self._project(tgt)
            cv.create_line(o[0], o[1], t[0], t[1], fill=col, width=2, arrow="last", arrowshape=(8, 10, 3))
            cv.create_text(t[0] + 6, t[1], text=lbl, fill=col, font=("Segoe UI", 10, "bold"), anchor="w")

        base_size = 18
        corners = []
        for bx, bz in [(-base_size, -base_size), (base_size, -base_size), (base_size, base_size), (-base_size, base_size)]:
            p = self._project((bx, 0, bz))
            corners.extend([p[0], p[1]])
        cv.create_polygon(corners, fill="#95A2B3", outline="#68788C", width=1.5)

        if self.show_envelope:
            projected = []
            for p in self._envelope_points:
                px, py, sc = self._project(p)
                projected.append((sc, px, py))
            projected.sort(key=lambda t: t[0])
            for sc, px, py in projected:
                r = max(1, int(1.8 * sc))
                cv.create_oval(px-r, py-r, px+r, py+r, fill=LANL_BLUE, outline="")

        pts3d = self._compute_chain()
        pts2d = [self._project(p) for p in pts3d]

        shadow = []
        for p3 in pts3d:
            s = self._project((p3[0], 0, p3[2]))
            shadow.append((s[0], s[1]))
        for i in range(len(shadow) - 1):
            cv.create_line(
                shadow[i][0], shadow[i][1],
                shadow[i + 1][0], shadow[i + 1][1],
                fill="#C8D0DA", width=2, capstyle="round"
            )

        link_styles = [
            ("#70859A", "#4E6175", 14),
            (ULTRAMARINE, "#001F5C", 12),
            (LANL_BLUE, "#1E6FA8", 10),
            ("#8094A8", "#5E7287", 8),
            ("#506477", "#3B4C5B", 6),
        ]
        for i in range(len(pts2d) - 1):
            p, q = pts2d[i], pts2d[i + 1]
            sc = (p[2] + q[2]) * 0.5
            fill, outl, bw = link_styles[i]
            w = max(3, int(bw * sc * 0.95))
            wo = max(4, int((bw + 3) * sc * 0.95))
            cv.create_line(p[0], p[1], q[0], q[1], fill=outl, width=wo, capstyle="round")
            cv.create_line(p[0], p[1], q[0], q[1], fill=fill, width=w, capstyle="round")
            cv.create_line(p[0], p[1], q[0], q[1], fill=WHITE, width=max(1, w // 6), capstyle="round")

        for i, (px, py, sc) in enumerate(pts2d):
            r = max(4, int(10 * sc * 0.85))
            cv.create_oval(px-r, py-r, px+r, py+r, fill=DARK_GRAY, outline="#1F252B", width=1)
            if 0 < i <= 5:
                cv.create_text(px, py, text=str(i), fill=WHITE, font=("Segoe UI", max(6, int(r * 0.8)), "bold"))

# ---------------------------------------------------------
# LIVE VIEW PANEL
# ---------------------------------------------------------
class LiveViewPanel:
    def __init__(self, parent):
        self.parent = parent
        self.cap = None
        self.current_index = None
        self.running = False
        self.photo = None
        self.after_id = None

        self.wrap = tk.Frame(parent, bg=WHITE)
        self.wrap.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(
            self.wrap,
            bg="#111111",
            highlightthickness=1,
            highlightbackground=BORDER
        )
        self.canvas.place(x=0, y=0)

        self.wrap.bind("<Configure>", self.enforce_16_9)

    def enforce_16_9(self, _event=None):
        w = max(100, self.wrap.winfo_width())
        h = max(100, self.wrap.winfo_height())

        target_ratio = 16 / 9
        current_ratio = w / h

        if current_ratio > target_ratio:
            box_h = h
            box_w = int(h * target_ratio)
        else:
            box_w = w
            box_h = int(w / target_ratio)

        x = (w - box_w) // 2
        y = (h - box_h) // 2

        self.canvas.place(x=x, y=y, width=box_w, height=box_h)

    def _schedule_after(self, delay_ms, callback):
        top = self.wrap.winfo_toplevel()
        if top and top.winfo_exists():
            self.after_id = top.after(delay_ms, callback)

    def scan_cameras(self, max_index=1):
        found = []
        for i in range(max_index + 1):
            cap = None
            try:
                cap = cv2.VideoCapture(i, cv2.CAP_AVFOUNDATION)
                if cap is not None and cap.isOpened():
                    found.append(i)
            except Exception:
                pass
            finally:
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass
        return found

    def start(self, cam_index):
        self.stop()

        try:
            self.cap = cv2.VideoCapture(cam_index, cv2.CAP_AVFOUNDATION)
        except Exception:
            self.cap = None

        if not self.cap or not self.cap.isOpened():
            self.current_index = None
            self.running = False
            self.draw_message("Unable to open selected webcam")
            return False

        self.current_index = cam_index
        self.running = True
        self._schedule_after(50, self._update_frame)
        return True

    def stop(self):
        self.running = False

        if self.after_id is not None:
            try:
                top = self.wrap.winfo_toplevel()
                if top and top.winfo_exists():
                    top.after_cancel(self.after_id)
            except Exception:
                pass
            self.after_id = None

        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass

        self.cap = None
        self.current_index = None
        self.photo = None

    def draw_message(self, msg):
        self.canvas.delete("all")
        w = max(100, self.canvas.winfo_width())
        h = max(100, self.canvas.winfo_height())
        self.canvas.create_text(
            w / 2, h / 2,
            text=msg,
            fill=WHITE,
            font=("Segoe UI", 12, "bold")
        )

    def _update_frame(self):
        self.after_id = None

        if not self.running or self.cap is None:
            return

        try:
            ok, frame = self.cap.read()
        except Exception:
            ok, frame = False, None

        if not ok or frame is None:
            self.draw_message("Live feed unavailable")
            self._schedule_after(250, self._update_frame)
            return

        try:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        except Exception:
            self.draw_message("Camera frame error")
            self._schedule_after(250, self._update_frame)
            return

        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()

        if cw < 10 or ch < 10:
            self._schedule_after(100, self._update_frame)
            return

        fh, fw = frame.shape[:2]
        if fh <= 0 or fw <= 0:
            self.draw_message("Invalid camera frame")
            self._schedule_after(250, self._update_frame)
            return

        canvas_ratio = cw / ch
        frame_ratio = fw / fh

        if frame_ratio > canvas_ratio:
            scale = ch / fh
            new_w = int(fw * scale)
            new_h = ch
        else:
            scale = cw / fw
            new_w = cw
            new_h = int(fh * scale)

        try:
            frame = cv2.resize(frame, (new_w, new_h))
        except Exception:
            self.draw_message("Resize error")
            self._schedule_after(250, self._update_frame)
            return

        crop_x = max(0, (new_w - cw) // 2)
        crop_y = max(0, (new_h - ch) // 2)
        frame = frame[crop_y:crop_y + ch, crop_x:crop_x + cw]

        img = Image.fromarray(frame)
        self.photo = ImageTk.PhotoImage(img)

        self.canvas.delete("all")
        self.canvas.create_image(cw // 2, ch // 2, image=self.photo, anchor="center")

        self._schedule_after(30, self._update_frame)

# ---------------------------------------------------------
# SERIAL HELPERS
# ---------------------------------------------------------
def list_com_ports():
    ports = []
    for p in serial.tools.list_ports.comports():
        desc = p.description if p.description else ""
        ports.append(f"{p.device} - {desc}".strip(" -"))
    return ports

def selected_port_device():
    val = port_var.get().strip()
    if not val:
        return ""
    return val.split(" - ")[0].strip()

def serial_send_line(line):
    if ser and ser.is_open:
        ser.write((line + "\n").encode())

def connect_serial():
    global ser, ready
    ready = False

    if ser and ser.is_open:
        try:
            ser.close()
        except Exception:
            pass
        ser = None

    dev = selected_port_device()
    if not dev:
        status_var.set("Select a COM port first.")
        online_var.set("OFFLINE")
        online_dot.config(fg=DANGER)
        online_label.config(fg=DANGER)
        connect_btn.config(text="Connect", bg=ULTRAMARINE, activebackground="#0B4AA8")
        return

    try:
        ser = serial.Serial(dev, BAUD_RATE, timeout=1)
        time.sleep(2)
        ready = True
        status_var.set(f"Connected to {dev} @ {BAUD_RATE}")
        online_var.set("ONLINE")
        online_dot.config(fg=SUCCESS_BRIGHT)
        online_label.config(fg=SUCCESS_BRIGHT)
        connect_btn.config(text="Connected", bg=SUCCESS, activebackground=SUCCESS_BRIGHT)
    except Exception as e:
        ser = None
        ready = False
        status_var.set(f"Serial error: {e}")
        online_var.set("OFFLINE")
        online_dot.config(fg=DANGER)
        online_label.config(fg=DANGER)
        connect_btn.config(text="Connect", bg=ULTRAMARINE, activebackground="#0B4AA8")

def refresh_ports():
    ports = list_com_ports()
    port_combo["values"] = ports
    if ports and not port_var.get():
        port_var.set(ports[0])
    status_var.set(f"{len(ports)} port(s) found.")

# ---------------------------------------------------------
# CAMERA HELPERS
# ---------------------------------------------------------
_camera_scan_in_progress = False

def refresh_cameras():
    global _camera_scan_in_progress
    if _camera_scan_in_progress:
        return

    _camera_scan_in_progress = True
    live_status_var.set("Scanning cameras...")

    def _scan():
        cams = live_view.scan_cameras(max_index=1)
        labels = [f"Camera {i}" for i in cams]

        def _update():
            global _camera_scan_in_progress
            _camera_scan_in_progress = False
            camera_combo["values"] = labels

            if labels:
                if camera_var.get() not in labels:
                    camera_var.set(labels[0])
                live_status_var.set(f"{len(labels)} camera(s) found.")
            else:
                camera_var.set("")
                live_status_var.set("No webcams found.")
                live_view.draw_message("No webcam detected")

        root.after(0, _update)

    threading.Thread(target=_scan, daemon=True).start()

def selected_camera_index():
    val = camera_var.get().strip()
    if not val:
        return None
    try:
        return int(val.split()[-1])
    except Exception:
        return None

def start_selected_camera():
    idx = selected_camera_index()
    if idx is None:
        live_status_var.set("Select a webcam first.")
        live_view.draw_message("No camera selected")
        return

    ok = live_view.start(idx)
    if ok:
        live_status_var.set(f"Live View running on Camera {idx}")
    else:
        live_status_var.set(f"Could not open Camera {idx}")

def stop_selected_camera():
    live_view.stop()
    live_view.draw_message("Live view stopped")
    live_status_var.set("Live view stopped")

# ---------------------------------------------------------
# SERIAL SEND
# ---------------------------------------------------------
def clamp_ranges(base, link1, link2, link3, tool):
    base  = max(WORK_MIN["base"],  min(WORK_MAX["base"],  int(base)))
    link1 = max(WORK_MIN["link1"], min(WORK_MAX["link1"], int(link1)))
    link2 = max(WORK_MIN["link2"], min(WORK_MAX["link2"], int(link2)))
    link3 = max(WORK_MIN["link3"], min(WORK_MAX["link3"], int(link3)))
    tool  = max(WORK_MIN["tool"],  min(WORK_MAX["tool"],  int(tool)))
    return [base, link1, link2, link3, tool]

def display(text):
    serial_send_line(f"DISPLAY:{text}")

def send_angles(base, link1, link2, link3, tool):
    if not ready:
        return
    vals = clamp_ranges(base, link1, link2, link3, tool)
    serial_send_line(f"{vals[0]},{vals[1]},{vals[2]},{vals[3]},{vals[4]}")

def send_test_servo(value):
    if not ready:
        return
    value = max(WORK_MIN["test"], min(WORK_MAX["test"], int(value)))
    serial_send_line(f"TESTSERVO:{value}")

def set_magnet(state: bool):
    global magnet_on
    magnet_on = state
    if ready:
        serial_send_line("MAGNET:ON" if state else "MAGNET:OFF")
    update_tool_control_buttons()

def set_vacuum(state: bool):
    global vacuum_on
    vacuum_on = state
    if ready:
        serial_send_line("VACUUM:ON" if state else "VACUUM:OFF")
    update_tool_control_buttons()

def set_solenoid(state: bool):
    global solenoid_on
    solenoid_on = state
    if ready:
        serial_send_line("SOLENOID:ON" if state else "SOLENOID:OFF")
    update_tool_control_buttons()

def toggle_magnet():
    set_magnet(not magnet_on)

def toggle_vacuum():
    set_vacuum(not vacuum_on)

def toggle_solenoid():
    set_solenoid(not solenoid_on)

def update_tool_control_buttons():
    if magnet_on:
        magnet_toggle_btn.config(text="Magnet (P4): ON", bg=SUCCESS, fg=WHITE, activebackground=SUCCESS_BRIGHT)
    else:
        magnet_toggle_btn.config(text="Magnet (P4): OFF", bg="#DDE5EF", fg=DARK_GRAY, activebackground="#EDF3F9")

    if solenoid_on:
        solenoid_toggle_btn.config(text="Solenoid (P2): ON", bg=SUCCESS, fg=WHITE, activebackground=SUCCESS_BRIGHT)
    else:
        solenoid_toggle_btn.config(text="Solenoid (P2): OFF", bg="#DDE5EF", fg=DARK_GRAY, activebackground="#EDF3F9")

    if vacuum_on:
        vacuum_toggle_btn.config(text="Pump (P3): ON", bg=SUCCESS, fg=WHITE, activebackground=SUCCESS_BRIGHT)
    else:
        vacuum_toggle_btn.config(text="Pump (P3): OFF", bg="#DDE5EF", fg=DARK_GRAY, activebackground="#EDF3F9")

# ---------------------------------------------------------
# POSE UPDATE
# ---------------------------------------------------------
def update_pose(vals, send_serial=True):
    base, link1, link2, link3, tool = clamp_ranges(*vals)

    tool_slider.configure(command=None)
    link3_slider.configure(command=None)
    link2_slider.configure(command=None)
    link1_slider.configure(command=None)
    base_slider.configure(command=None)

    tool_slider.set(tool)
    link3_slider.set(link3)
    link2_slider.set(link2)
    link1_slider.set(link1)
    base_slider.set(base)

    tool_slider.configure(command=slider_changed)
    link3_slider.configure(command=slider_changed)
    link2_slider.configure(command=slider_changed)
    link1_slider.configure(command=slider_changed)
    base_slider.configure(command=slider_changed)

    arm.set_angles_from_servos(base, link1, link2, link3, tool)
    update_info_boxes()

    if send_serial:
        send_angles(base, link1, link2, link3, tool)

# ---------------------------------------------------------
# ANIMATION / SEQUENCES
# ---------------------------------------------------------
def animate_move(targets, on_done=None):
    global is_animating, action_cancelled

    targets = clamp_ranges(*targets)
    current = [
        int(base_slider.get()),
        int(link1_slider.get()),
        int(link2_slider.get()),
        int(link3_slider.get()),
        int(tool_slider.get())
    ]

    diffs = [t - c for c, t in zip(current, targets)]
    max_diff = max(abs(d) for d in diffs)

    if max_diff == 0:
        update_pose(targets, send_serial=True)
        if on_done:
            root.after(0, on_done)
        return

    steps = max(MIN_MOTION_STEPS, max_diff)
    is_animating = True

    def step_fn(step_idx):
        global is_animating

        if action_cancelled:
            is_animating = False
            return

        t = step_idx / steps
        te = smoothstep(t)
        vals = [round(c + d * te) for c, d in zip(current, diffs)]
        update_pose(vals, send_serial=True)

        if step_idx < steps:
            root.after(FRAME_MS, lambda: step_fn(step_idx + 1))
        else:
            update_pose(targets, send_serial=True)
            is_animating = False
            if on_done:
                root.after(0, on_done)

    step_fn(1)

def run_sequence(sequence, idx=0, on_done=None):
    if action_cancelled:
        return
    if idx >= len(sequence):
        if on_done:
            on_done()
        return

    item = sequence[idx]

    if "display" in item and item["display"]:
        display(item["display"])

    relay = item.get("relay", None)
    state = item.get("state", None)
    if relay and state:
        relay = relay.upper()
        state = state.upper()

        if relay == "MAGNET":
            set_magnet(state == "ON")
        elif relay == "VACUUM":
            set_vacuum(state == "ON")
        elif relay == "SOLENOID":
            set_solenoid(state == "ON")

    pause_ms = item.get("pause_ms", 0)

    if "move" not in item:
        if pause_ms > 0:
            root.after(pause_ms, lambda: run_sequence(sequence, idx + 1, on_done))
        else:
            run_sequence(sequence, idx + 1, on_done)
        return

    move = item["move"]

    def after_move():
        if action_cancelled:
            return
        if pause_ms > 0:
            root.after(pause_ms, lambda: run_sequence(sequence, idx + 1, on_done))
        else:
            run_sequence(sequence, idx + 1, on_done)

    animate_move(move, on_done=after_move)

def start_action(sequence, on_done=None):
    global is_animating, action_cancelled
    if is_animating:
        return
    action_cancelled = False
    run_sequence(sequence, on_done=on_done)

def cancel_action():
    global action_cancelled
    action_cancelled = True

# ---------------------------------------------------------
# MANUAL TOOL STATE HELPERS
# ---------------------------------------------------------
def update_manual_mode_buttons():
    if tool_attached:
        gripper_select_btn.config(state="disabled")
        pump_select_btn.config(state="disabled")
        pneumatic_select_btn.config(state="disabled")

        home_btn.config(state="disabled")
        action_a_btn.config(state="disabled")
        action_b_btn.config(state="disabled")
        action_c_btn.config(state="disabled")

        return_tool_btn.config(state="normal")
    else:
        gripper_select_btn.config(state="normal")
        pump_select_btn.config(state="normal")
        pneumatic_select_btn.config(state="normal")

        home_btn.config(state="normal")
        action_a_btn.config(state="normal")
        action_b_btn.config(state="normal")
        action_c_btn.config(state="normal")

        return_tool_btn.config(state="disabled")

def mark_tool_attached(tool_name):
    global active_tool, tool_attached
    active_tool = tool_name
    tool_attached = True
    update_manual_mode_buttons()
    status_var.set(f"Manual tool active: {tool_name.capitalize()}")

def mark_tool_returned():
    global active_tool, tool_attached
    active_tool = None
    tool_attached = False
    update_manual_mode_buttons()
    status_var.set("Tool returned. Ready for new selection.")

# ---------------------------------------------------------
# PRECISION LOCK
# ---------------------------------------------------------
def apply_precision_lock():
    locked = precision_lock_var.get()
    for s in [tool_slider, link3_slider, link2_slider, link1_slider, base_slider, servo_test_slider]:
        s.set_pointer_lock(locked)

    if locked:
        precision_lock_btn.config(text="Precision Lock: ON", bg=SUCCESS, fg=WHITE, activebackground=SUCCESS_BRIGHT)
        precision_lock_status.config(text="Canvas drag disabled | Arrow buttons active", fg=SUCCESS)
    else:
        precision_lock_btn.config(text="Precision Lock: OFF", bg="#DDE5EF", fg=DARK_GRAY, activebackground="#EDF3F9")
        precision_lock_status.config(text="Canvas drag enabled", fg=MID_GRAY)

def toggle_precision_lock():
    precision_lock_var.set(not precision_lock_var.get())
    apply_precision_lock()

# ------------------------------------------------------------------------------------------------------
# COMMANDS
# ------------------------------------------------------------------------------------------------------
def slider_changed(_val=None):
    global ready
    ready = True

    if is_animating:
        return

    base  = base_slider.get()
    link1 = link1_slider.get()
    link2 = link2_slider.get()
    link3 = link3_slider.get()
    tool  = tool_slider.get()

    send_angles(base, link1, link2, link3, tool)
    arm.set_angles_from_servos(base, link1, link2, link3, tool)
    update_info_boxes()

def servo_test_changed(_val=None):
    send_test_servo(servo_test_slider.get())

def go_home():
    if tool_attached:
        status_var.set("Return the active tool before using Home.")
        return

    start_action([
        {"display": "SMILE", "move": [90, 90, 90, 90, 90], "pause_ms": 0}
    ])

def actionA():
    if tool_attached:
        status_var.set("Return the active tool before running Action A.")
        return

    start_action([
        {"display": "A", "move": [90, 90, 90, 90, 90], "pause_ms": 500},
        {"display": "SMILE", "move": [90, 90, 90, 90, 90], "pause_ms": 0},
    ])

def actionB():
    if tool_attached:
        status_var.set("Return the active tool before running Action B.")
        return

    seq = [
        {"display": "B", "move": [90, 90, 90, 90, 90], "pause_ms": 500},
        {"display": "SMILE", "move": [90, 90, 90, 90, 90], "pause_ms": 0},
    ]
    start_action(seq)

def actionC():
    if tool_attached:
        status_var.set("Return the active tool before running Action C.")
        return

    seq = [
        {"display": "C", "move": [90, 90, 90, 90, 90], "pause_ms": 0},
        {"display": "SMILE", "move": [90, 90, 90, 90, 90], "pause_ms": 0},
    ]
    start_action(seq)

# [base, link1, link2, link3, wrist]
def select_gripper():
    if is_animating or tool_attached:
        return

    start_action([
        {"move": [90, 90, 90, 90, 90], "pause_ms": 600},
        {"move": [152, 97, 147, 152, 82], "pause_ms": 3000}, #hover
        {"move": [152, 101, 145, 152, 82], "pause_ms": 600}, #latch
        {"relay": "MAGNET", "state": "ON", "pause_ms": 1000},
        {"move": [90, 90, 90, 90, 90], "pause_ms": 600}, 
    ], on_done=lambda: mark_tool_attached("gripper"))

def select_pump():
    if is_animating or tool_attached:
        return

    start_action([
        {"move": [90, 90, 90, 90, 90], "pause_ms": 300},
        {"move": [90, 65, 132, 134, 90], "pause_ms": 600},
        {"move": [90, 65, 150, 134, 90], "pause_ms": 600},
        {"move": [90, 114, 150, 134, 90], "pause_ms": 1000},
        {"move": [90, 117, 150, 134, 90], "pause_ms": 1000},
        {"relay": "MAGNET", "state": "ON", "pause_ms": 100},
        {"move": [90, 90, 90, 90, 90], "pause_ms": 300},
    ], on_done=lambda: mark_tool_attached("pump"))

def select_pneumatic():
    if is_animating or tool_attached:
        return

    start_action([
        {"move": [90, 90, 90, 90, 90], "pause_ms": 600},
        {"move": [90, 65, 132, 136, 90], "pause_ms": 600},
        {"move": [22, 65, 132, 136, 90], "pause_ms": 600},
        {"move": [20, 107, 139, 150, 88], "pause_ms": 1200},
        {"relay": "MAGNET", "state": "ON", "pause_ms": 600},
        {"move": [20, 111, 139, 150, 88], "pause_ms": 1200},
        {"move": [20, 60, 147, 128, 90], "pause_ms": 600},
        {"move": [90, 60, 147, 128, 90], "pause_ms": 600},
    ], on_done=lambda: mark_tool_attached("pneumatic"))

def return_active_tool():
    if is_animating or not tool_attached or active_tool is None:
        return

    if active_tool == "gripper":
        seq = [
        {"move": [90, 90, 90, 90, 90], "pause_ms": 600},
        {"move": [152, 97, 147, 152, 82], "pause_ms": 3000}, #hover
        {"move": [152, 101, 145, 152, 82], "pause_ms": 600}, #latch
        {"relay": "MAGNET", "state": "OFF", "pause_ms": 1000},
        {"move": [90, 90, 90, 90, 90], "pause_ms": 600}, 
        ]
    elif active_tool == "pump":
        seq = [
            {"move": [90, 90, 90, 90, 90], "pause_ms": 300},
            {"move": [90, 90, 90, 90, 90], "pause_ms": 300},
            {"move": [90, 90, 90, 90, 90], "pause_ms": 0},
        ]
    elif active_tool == "pneumatic":
        seq = [
            {"move": [90, 90, 90, 90, 90], "pause_ms": 300},
            {"move": [90, 90, 90, 90, 90], "pause_ms": 300},
            {"move": [90, 90, 90, 90, 90], "pause_ms": 0},
        ]
    else:
        return

    start_action(seq, on_done=mark_tool_returned)

# ---------------------------------------------------------
# GUI HELPERS
# ---------------------------------------------------------
def make_card(parent):
    return tk.Frame(parent, bg=PANEL_BG, highlightbackground=BORDER, highlightthickness=1, bd=0)

def section_header(parent, text):
    f = tk.Frame(parent, bg=ULTRAMARINE, height=34)
    f.pack(fill="x")
    f.pack_propagate(False)
    tk.Label(f, text=text, fg=WHITE, bg=ULTRAMARINE, font=SANS_H2, padx=12, pady=4).pack(side="left")
    return f

def abb_button(parent, text, cmd=None, width=10, style="normal", state="normal"):
    if style == "primary":
        bg, fg, abg = LANL_BLUE, WHITE, LIGHT_BLUE
    elif style == "home":
        bg, fg, abg = ULTRAMARINE, WHITE, "#0B4AA8"
    elif style == "success":
        bg, fg, abg = SUCCESS, WHITE, SUCCESS_BRIGHT
    elif style == "danger":
        bg, fg, abg = "#D3D3D3", DARK_GRAY, "#E3E3E3"
    else:
        bg, fg, abg = "#DDE5EF", DARK_GRAY, "#EDF3F9"

    return tk.Button(
        parent, text=text, command=cmd,
        bg=bg, fg=fg, activebackground=abg, activeforeground=fg,
        relief="raised", bd=1, font=SANS_B, width=width, cursor="hand2",
        pady=8, state=state
    )

def update_info_boxes():
    tcp = arm.get_tcp_position()
    tcp_x_var.set(f"{tcp[0] / 10:+.1f} cm")
    tcp_y_var.set(f"{tcp[1] / 10:+.1f} cm")
    tcp_z_var.set(f"{tcp[2] / 10:+.1f} cm")

    tool_var.set(f"{tool_slider.get():3d}°")
    link3_var.set(f"{link3_slider.get():3d}°")
    link2_var.set(f"{link2_slider.get():3d}°")
    link1_var.set(f"{link1_slider.get():3d}°")
    base_var.set(f"{base_slider.get():3d}°")

# ---------------------------------------------------------
# GUI SETUP
# ---------------------------------------------------------
root = tk.Tk()
root.title("UTRGV Robotic Arm Controller")
root.geometry("1360x900")
root.minsize(1220, 780)
root.configure(bg=BG_APP)

style = ttk.Style()
style.theme_use("clam")
style.configure(
    "Modern.TCombobox",
    fieldbackground=WHITE,
    background=WHITE,
    foreground=DARK_GRAY,
    bordercolor=BORDER,
    lightcolor=WHITE,
    darkcolor=WHITE,
    arrowsize=16,
    padding=6
)

# ---------------------------------------------------------
# TOP HEADER
# ---------------------------------------------------------
header = tk.Frame(root, bg=ULTRAMARINE, height=62)
header.pack(fill="x", side="top")
header.pack_propagate(False)

accent_bar = tk.Frame(header, bg=LANL_BLUE, width=12)
accent_bar.pack(side="left", fill="y")

title_wrap = tk.Frame(header, bg=ULTRAMARINE)
title_wrap.pack(side="left", fill="both", expand=True)

tk.Label(
    title_wrap,
    text="UTRGV Robotic Arm Controller",
    bg=ULTRAMARINE,
    fg=WHITE,
    font=SANS_H1,
    pady=14
).pack(anchor="w", padx=18)

online_var = tk.StringVar(value="OFFLINE")
online_block = tk.Frame(header, bg=ULTRAMARINE)
online_block.pack(side="right", padx=18)

online_dot = tk.Label(online_block, text="●", bg=ULTRAMARINE, fg=DANGER, font=("Segoe UI", 14, "bold"))
online_dot.pack(side="left", pady=10)

online_label = tk.Label(
    online_block,
    textvariable=online_var,
    bg=ULTRAMARINE,
    fg=DANGER,
    font=("Segoe UI", 12, "bold")
)
online_label.pack(side="left", pady=10, padx=(6, 0))

# ---------------------------------------------------------
# MAIN AREA
# ---------------------------------------------------------
main = tk.Frame(root, bg=BG_APP)
main.pack(fill="both", expand=True, padx=12, pady=12)

left_col = tk.Frame(main, bg=BG_APP, width=620)
left_col.pack(side="left", fill="y")
left_col.pack_propagate(False)

right_col = tk.Frame(main, bg=BG_APP, width=520)
right_col.pack(side="right", fill="both", expand=True, padx=(12, 0))
right_col.pack_propagate(False)

# ---------------------------------------------------------
# SERIAL CARD
# ---------------------------------------------------------
serial_card = make_card(left_col)
serial_card.pack(fill="x", pady=(0, 10))
section_header(serial_card, "Serial Connection")

serial_body = tk.Frame(serial_card, bg=PANEL_BG)
serial_body.pack(fill="x", padx=12, pady=12)

port_var = tk.StringVar(value="")
port_combo = ttk.Combobox(
    serial_body,
    textvariable=port_var,
    state="readonly",
    width=38,
    style="Modern.TCombobox"
)
port_combo.pack(fill="x", pady=(0, 10), ipady=3)

serial_btns = tk.Frame(serial_body, bg=PANEL_BG)
serial_btns.pack(fill="x")

abb_button(serial_btns, "Refresh", refresh_ports, width=12).pack(side="left")
connect_btn = abb_button(serial_btns, "Connect", connect_serial, width=12, style="home")
connect_btn.pack(side="left", padx=(8, 0))

status_var = tk.StringVar(value="Select a COM port, then connect.")
status_label = tk.Label(serial_card, textvariable=status_var, anchor="w", bg=PANEL_BG, fg=MID_GRAY, font=SANS)
status_label.pack(fill="x", padx=12, pady=(0, 12))

refresh_ports()

# ---------------------------------------------------------
# JOINT CONTROL CARD
# ---------------------------------------------------------
slider_card = make_card(left_col)
slider_card.pack(fill="x", pady=(0, 10))
section_header(slider_card, "Joint Control")

slider_body = tk.Frame(slider_card, bg=PANEL_BG)
slider_body.pack(fill="x", padx=12, pady=12)

tool_slider = LimitedSlider(
    slider_body, "Wrist",
    full_min=0, full_max=180,
    work_min=WORK_MIN["tool"], work_max=WORK_MAX["tool"],
    initial=90, command=slider_changed, width=500
)
tool_slider.pack(fill="x", pady=4)

link3_slider = LimitedSlider(
    slider_body, "Link 3",
    full_min=0, full_max=180,
    work_min=WORK_MIN["link3"], work_max=WORK_MAX["link3"],
    initial=90, command=slider_changed, width=500
)
link3_slider.pack(fill="x", pady=4)

link2_slider = LimitedSlider(
    slider_body, "Link 2",
    full_min=0, full_max=180,
    work_min=WORK_MIN["link2"], work_max=WORK_MAX["link2"],
    initial=90, command=slider_changed, width=500
)
link2_slider.pack(fill="x", pady=4)

link1_slider = LimitedSlider(
    slider_body, "Link 1",
    full_min=0, full_max=180,
    work_min=WORK_MIN["link1"], work_max=WORK_MAX["link1"],
    initial=90, command=slider_changed, width=500
)
link1_slider.pack(fill="x", pady=4)

base_slider = LimitedSlider(
    slider_body, "Base",
    full_min=0, full_max=180,
    work_min=WORK_MIN["base"], work_max=WORK_MAX["base"],
    initial=90, command=slider_changed, width=500
)
base_slider.pack(fill="x", pady=4)

servo_test_slider = LimitedSlider(
    slider_body, "Gripper Tool",
    full_min=0, full_max=180,
    work_min=WORK_MIN["test"], work_max=WORK_MAX["test"],
    initial=90, command=servo_test_changed,
    active_color=TEST_TRACK_ACTIVE,
    thumb_outline=TEST_THUMB_OUTLINE,
    width=500
)
servo_test_slider.pack(fill="x", pady=(8, 4))

precision_row = tk.Frame(slider_body, bg=PANEL_BG)
precision_row.pack(fill="x", pady=(8, 4))

precision_lock_var = tk.BooleanVar(value=False)

precision_lock_btn = tk.Button(
    precision_row,
    text="Precision Lock: OFF",
    command=toggle_precision_lock,
    bg="#DDE5EF",
    fg=DARK_GRAY,
    activebackground="#EDF3F9",
    activeforeground=DARK_GRAY,
    relief="raised",
    bd=1,
    font=SANS_B,
    cursor="hand2",
    padx=12,
    pady=6
)
precision_lock_btn.pack(side="left")

precision_lock_status = tk.Label(
    precision_row,
    text="Canvas drag enabled",
    bg=PANEL_BG,
    fg=MID_GRAY,
    font=SANS_S
)
precision_lock_status.pack(side="left", padx=(10, 0))

legend = tk.Label(
    slider_body,
    text="Light gray = blocked zone   |   Blue = working zone   |   Marker = 90° center",
    bg=PANEL_BG,
    fg=MID_GRAY,
    font=SANS_S,
    anchor="w"
)
legend.pack(fill="x", pady=(4, 0))

# ---------------------------------------------------------
# RIGHT WORKSPACE
# ---------------------------------------------------------
view_card = make_card(right_col)
view_card.pack(fill="both", expand=True)
section_header(view_card, "3D Workspace View")

view_info = tk.Frame(view_card, bg=PANEL_BG)
view_info.pack(fill="x", padx=12, pady=(10, 0))

env_var = tk.StringVar(value="Work Envelope: OFF")
env_label = tk.Label(view_info, textvariable=env_var, bg=PANEL_BG, fg=ULTRAMARINE, font=SANS_H2)
env_label.pack(side="left")

split_wrap = tk.Frame(view_card, bg=PANEL_BG)
split_wrap.pack(fill="both", expand=True, padx=12, pady=10)

split_wrap.grid_columnconfigure(0, weight=3)
split_wrap.grid_columnconfigure(1, weight=2)
split_wrap.grid_rowconfigure(0, weight=1)

workspace_left = tk.Frame(split_wrap, bg=PANEL_BG)
workspace_left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

workspace_left_inner = tk.Frame(workspace_left, bg=PANEL_BG)
workspace_left_inner.pack(fill="both", expand=True)

arm = ArmCanvas(workspace_left_inner)

overlay_wrap = tk.Frame(workspace_left_inner, bg=PANEL_BG)
overlay_wrap.place(relx=1.0, y=10, x=-12, anchor="ne")

info_box_style = {
    "bg": WHITE,
    "highlightbackground": BORDER,
    "highlightthickness": 1,
    "bd": 0
}

tcp_box = tk.Frame(overlay_wrap, **info_box_style)
tcp_box.pack(anchor="ne", pady=(0, 8))

tk.Label(tcp_box, text="TCP POSITION", bg=WHITE, fg=ULTRAMARINE, font=("Segoe UI", 8, "bold")).pack(pady=(6, 2))

tcp_body = tk.Frame(tcp_box, bg=WHITE)
tcp_body.pack(padx=10, pady=(0, 8))

tcp_x_var = tk.StringVar()
tcp_y_var = tk.StringVar()
tcp_z_var = tk.StringVar()

for lbl, col, var in [
    ("X:", "#E53935", tcp_x_var),
    ("Y:", SUCCESS,   tcp_y_var),
    ("Z:", "#2F6BFF", tcp_z_var),
]:
    row = tk.Frame(tcp_body, bg=WHITE)
    row.pack(fill="x")
    tk.Label(row, text=lbl, bg=WHITE, fg=col, font=("Segoe UI", 9, "bold"), width=2, anchor="w").pack(side="left")
    tk.Label(row, textvariable=var, bg=WHITE, fg=DARK_GRAY, font=("Consolas", 9), width=10, anchor="e").pack(side="left")

joint_box = tk.Frame(overlay_wrap, **info_box_style)
joint_box.pack(anchor="ne")

tk.Label(joint_box, text="JOINT TELEMETRY", bg=WHITE, fg=ULTRAMARINE, font=("Segoe UI", 8, "bold")).pack(pady=(6, 2))

joint_body = tk.Frame(joint_box, bg=WHITE)
joint_body.pack(padx=10, pady=(0, 8))

tool_var  = tk.StringVar()
link3_var = tk.StringVar()
link2_var = tk.StringVar()
link1_var = tk.StringVar()
base_var  = tk.StringVar()

for lbl, var in [
    ("WRIST",  tool_var),
    ("LINK 3", link3_var),
    ("LINK 2", link2_var),
    ("LINK 1", link1_var),
    ("BASE",   base_var),
]:
    row = tk.Frame(joint_body, bg=WHITE)
    row.pack(fill="x")
    tk.Label(row, text=f"{lbl}:", bg=WHITE, fg=DARK_GRAY, font=("Segoe UI", 8, "bold"), width=8, anchor="w").pack(side="left")
    tk.Label(row, textvariable=var, bg=WHITE, fg=DARK_GRAY, font=("Consolas", 8), width=6, anchor="e").pack(side="left")

workspace_right = tk.Frame(split_wrap, bg=PANEL_BG)
workspace_right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

live_card = tk.Frame(workspace_right, bg=WHITE, highlightbackground=BORDER, highlightthickness=1, bd=0)
live_card.pack(fill="both", expand=True)

live_top = tk.Frame(live_card, bg=WHITE)
live_top.pack(fill="x", padx=10, pady=(10, 6))

tk.Label(live_top, text="LIVE VIEW", bg=WHITE, fg=ULTRAMARINE, font=("Segoe UI", 10, "bold")).pack(side="left")

camera_var = tk.StringVar(value="")
camera_combo = ttk.Combobox(
    live_top,
    textvariable=camera_var,
    state="readonly",
    width=16,
    style="Modern.TCombobox"
)
camera_combo.pack(side="right")

live_body = tk.Frame(live_card, bg=WHITE)
live_body.pack(fill="both", expand=True, padx=10, pady=(0, 10))

live_view = LiveViewPanel(live_body)
root.after(100, lambda: live_view.draw_message("Press Refresh Cams"))

live_controls = tk.Frame(live_card, bg=WHITE)
live_controls.pack(fill="x", padx=10, pady=(0, 10))

tk.Button(
    live_controls, text="Refresh Cams", command=refresh_cameras,
    bg=WHITE, fg=DARK_GRAY, activebackground=LIGHT_BLUE, activeforeground=DARK_GRAY,
    relief="raised", bd=1, font=SANS, padx=10, pady=5
).pack(side="left")

tk.Button(
    live_controls, text="Start", command=start_selected_camera,
    bg=WHITE, fg=DARK_GRAY, activebackground=LIGHT_BLUE, activeforeground=DARK_GRAY,
    relief="raised", bd=1, font=SANS, padx=10, pady=5
).pack(side="left", padx=(6, 0))

tk.Button(
    live_controls, text="Stop", command=stop_selected_camera,
    bg=WHITE, fg=DARK_GRAY, activebackground=LIGHT_BLUE, activeforeground=DARK_GRAY,
    relief="raised", bd=1, font=SANS, padx=10, pady=5
).pack(side="left", padx=(6, 0))

live_status_var = tk.StringVar(value="Press Refresh Cams to detect webcams.")
tk.Label(
    live_controls,
    textvariable=live_status_var,
    bg=WHITE,
    fg=MID_GRAY,
    font=SANS_S
).pack(side="right")

bottom_controls = tk.Frame(view_card, bg=PANEL_BG)
bottom_controls.pack(fill="x", padx=12, pady=(0, 8))

tk.Label(bottom_controls, text="View:", bg=PANEL_BG, fg=MID_GRAY, font=SANS_B).pack(side="left", padx=(0, 6))

def set_view(name):
    presets = {
        "front": (0.0, 0.0),
        "side":  (-math.pi / 2, 0.0),
        "top":   (0.0, math.radians(89)),
        "iso":   (-math.pi / 4, math.radians(28)),
    }
    arm.cam_theta, arm.cam_phi = presets[name]
    arm.reset_zoom()

for lbl, key in [("Front", "front"), ("Side", "side"), ("Top", "top"), ("Iso", "iso")]:
    tk.Button(
        bottom_controls, text=lbl, command=lambda k=key: set_view(k),
        bg=WHITE, fg=DARK_GRAY, activebackground=LIGHT_BLUE, activeforeground=DARK_GRAY,
        relief="raised", bd=1, font=SANS, padx=12, pady=5
    ).pack(side="left", padx=3)

def toggle_envelope_ui():
    arm.toggle_envelope()
    env_var.set(f"Work Envelope: {'ON' if arm.show_envelope else 'OFF'}")

tk.Button(
    bottom_controls, text="Work Envelope", command=toggle_envelope_ui,
    bg=WHITE, fg=DARK_GRAY, activebackground=LIGHT_BLUE, activeforeground=DARK_GRAY,
    relief="raised", bd=1, font=SANS, padx=12, pady=5
).pack(side="left", padx=(10, 0))

tk.Button(
    bottom_controls, text="Zoom -", command=arm.zoom_out,
    bg=WHITE, fg=DARK_GRAY, activebackground=LIGHT_BLUE, activeforeground=DARK_GRAY,
    relief="raised", bd=1, font=SANS, padx=12, pady=5
).pack(side="left", padx=(10, 0))

tk.Button(
    bottom_controls, text="Zoom +", command=arm.zoom_in,
    bg=WHITE, fg=DARK_GRAY, activebackground=LIGHT_BLUE, activeforeground=DARK_GRAY,
    relief="raised", bd=1, font=SANS, padx=12, pady=5
).pack(side="left", padx=3)

tk.Button(
    bottom_controls, text="Zoom Reset", command=arm.reset_zoom,
    bg=WHITE, fg=DARK_GRAY, activebackground=LIGHT_BLUE, activeforeground=DARK_GRAY,
    relief="raised", bd=1, font=SANS, padx=12, pady=5
).pack(side="left", padx=3)

tk.Label(
    bottom_controls,
    text="Drag to orbit | Mouse wheel to zoom",
    bg=PANEL_BG,
    fg=LIGHT_GRAY,
    font=SANS_S
).pack(side="right")

# ---------------------------------------------------------
# PROGRAM SEQUENCES CARD
# ---------------------------------------------------------
program_card = make_card(right_col)
program_card.pack(fill="x", pady=(10, 0))
section_header(program_card, "Program Sequences")

program_body = tk.Frame(program_card, bg=PANEL_BG)
program_body.pack(fill="x", padx=12, pady=12)

home_btn = abb_button(program_body, "Home", go_home, width=10, style="home")
home_btn.pack(side="left")

action_a_btn = abb_button(program_body, "Action A", actionA, width=10, style="primary")
action_a_btn.pack(side="left", padx=(8, 0))

action_b_btn = abb_button(program_body, "Action B", actionB, width=10, style="primary")
action_b_btn.pack(side="left", padx=(8, 0))

action_c_btn = abb_button(program_body, "Action C", actionC, width=10, style="primary")
action_c_btn.pack(side="left", padx=(8, 0))

stop_btn = abb_button(program_body, "Stop", cancel_action, width=10, style="danger")
stop_btn.pack(side="left", padx=(8, 0))

# ---------------------------------------------------------
# TOOL SELECTION CARD
# ---------------------------------------------------------
tool_select_card = make_card(right_col)
tool_select_card.pack(fill="x", pady=(10, 0))
section_header(tool_select_card, "Tool Selection")

tool_select_body = tk.Frame(tool_select_card, bg=PANEL_BG)
tool_select_body.pack(fill="x", padx=12, pady=12)

gripper_select_btn = abb_button(tool_select_body, "Gripper", select_gripper, width=10, style="primary")
gripper_select_btn.pack(side="left")

pump_select_btn = abb_button(tool_select_body, "Pump", select_pump, width=10, style="primary")
pump_select_btn.pack(side="left", padx=(8, 0))

pneumatic_select_btn = abb_button(tool_select_body, "Pneumatic", select_pneumatic, width=10, style="primary")
pneumatic_select_btn.pack(side="left", padx=(8, 0))

return_tool_btn = abb_button(tool_select_body, "Tool Return", return_active_tool, width=12, style="home", state="disabled")
return_tool_btn.pack(side="left", padx=(8, 0))

# ---------------------------------------------------------
# TOOL CONTROLS CARD
# ---------------------------------------------------------
tool_controls_card = make_card(right_col)
tool_controls_card.pack(fill="x", pady=(10, 0))
section_header(tool_controls_card, "Tool Controls")

tool_controls_body = tk.Frame(tool_controls_card, bg=PANEL_BG)
tool_controls_body.pack(fill="x", padx=12, pady=12)

magnet_toggle_btn = abb_button(tool_controls_body, "Magnet (P4): OFF", toggle_magnet, width=16)
magnet_toggle_btn.pack(side="left")

solenoid_toggle_btn = abb_button(tool_controls_body, "Solenoid (P2): OFF", toggle_solenoid, width=16)
solenoid_toggle_btn.pack(side="left", padx=(8, 0))

vacuum_toggle_btn = abb_button(tool_controls_body, "Pump (P3): OFF", toggle_vacuum, width=16)
vacuum_toggle_btn.pack(side="left", padx=(8, 0))

# ---------------------------------------------------------
# FOOTER
# ---------------------------------------------------------
footer = tk.Frame(root, bg=ULTRAMARINE, height=28)
footer.pack(fill="x", side="bottom")
footer.pack_propagate(False)

tk.Label(
    footer,
    text="In collaboration with Los Alamos National Lab | Savannah River National Laboratory | TechSource",
    bg=ULTRAMARINE,
    fg=WHITE,
    font=("Segoe UI", 9, "bold")
).pack(pady=4)

# ---------------------------------------------------------
# LOOP / INIT
# ---------------------------------------------------------
def info_loop():
    update_info_boxes()
    root.after(150, info_loop)

def on_close():
    try:
        live_view.stop()
    except Exception:
        pass

    try:
        if ser and ser.is_open:
            ser.close()
    except Exception:
        pass

    root.destroy()

root.protocol("WM_DELETE_WINDOW", on_close)

update_pose([90, 90, 90, 90, 90], send_serial=False)
servo_test_slider.set(90)
servo_test_changed()
update_tool_control_buttons()
update_manual_mode_buttons()
apply_precision_lock()
info_loop()

# Manual scan only is safer on macOS. Press Refresh Cams after launch.
# root.after(500, refresh_cameras)

root.mainloop()
