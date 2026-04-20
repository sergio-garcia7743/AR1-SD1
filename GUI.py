import tkinter as tk
from tkinter import ttk
import serial
import serial.tools.list_ports
import time
import math

BAUD_RATE = 115200

ser = None
ready = False
is_animating = False
action_cancelled = False
magnet_on = False
vacuum_on = False
solenoid_on = False

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

# Slightly different color for Servo Test
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

# ---------------------------------------------------------
# REAL ROBOT ORDER / SERIAL ORDER TO ARDUINO
# S1 = BASE
# S2 = LINK 1
# S3 = LINK 2
# S4 = LINK 3
# S5 = GRIPPER
# ---------------------------------------------------------
DEFAULT_ANGLE = 90

S1_MIN, S1_MAX = 0, 180
S2_MIN, S2_MAX = 20, 160
S3_MIN, S3_MAX = 10, 170
S4_MIN, S4_MAX = 0, 180
S5_MIN, S5_MAX = 0, 180

WORK_MIN = {
    "base":  20,
    "link1": 30,
    "link2": 25,
    "link3": 25,
    "tool":  0,
    "test":  30,   # same as most limited link
}
WORK_MAX = {
    "base":  160,
    "link1": 150,
    "link2": 155,
    "link3": 155,
    "tool":  180,
    "test":  150,
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

        self.label_text = label
        self.full_min = full_min
        self.full_max = full_max
        self.work_min = work_min
        self.work_max = work_max
        self.value = max(self.work_min, min(self.work_max, int(initial)))
        self.command = command

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

        # redraw whenever canvas size changes
        self.cv.bind("<Configure>", self._on_canvas_resize)

        # draw once now, then again after layout completes
        self.draw()
        self.after_idle(self.draw)

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

    def _val_to_x(self, v):
        x0 = self._track_x0()
        x1 = self._track_x1()
        t = (v - self.full_min) / (self.full_max - self.full_min)
        return x0 + t * (x1 - x0)

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
        self._set_from_x(e.x)

    def _drag(self, e):
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

    def _mu(self, e):
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

        cx, cy = self.W * 0.42, self.H * 0.60
        fov = max(420, min(self.W, self.H) * 0.95)
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
        except:
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
    # placeholder for future IDE support
    serial_send_line(f"TESTSERVO:{value}")

def set_magnet(state: bool):
    global magnet_on
    magnet_on = state
    if ready:
        serial_send_line("MAGNET:ON" if state else "MAGNET:OFF")
    update_aux_buttons()

def set_vacuum(state: bool):
    global vacuum_on
    vacuum_on = state
    if ready:
        serial_send_line("VACUUM:ON" if state else "VACUUM:OFF")
    update_aux_buttons()

def set_solenoid(state: bool):
    global solenoid_on
    solenoid_on = state
    if ready:
        serial_send_line("SOLENOID:ON" if state else "SOLENOID:OFF")
    update_aux_buttons()

def update_aux_buttons():
    if magnet_on:
        magnet_on_btn.config(bg=SUCCESS, fg=WHITE, activebackground=SUCCESS_BRIGHT)
        magnet_off_btn.config(bg="#DDE5EF", fg=DARK_GRAY, activebackground="#EDF3F9")
    else:
        magnet_on_btn.config(bg="#DDE5EF", fg=DARK_GRAY, activebackground="#EDF3F9")
        magnet_off_btn.config(bg=DARK_GRAY, fg=WHITE, activebackground="#444C55")

    if vacuum_on:
        vacuum_on_btn.config(bg=SUCCESS, fg=WHITE, activebackground=SUCCESS_BRIGHT)
        vacuum_off_btn.config(bg="#DDE5EF", fg=DARK_GRAY, activebackground="#EDF3F9")
    else:
        vacuum_on_btn.config(bg="#DDE5EF", fg=DARK_GRAY, activebackground="#EDF3F9")
        vacuum_off_btn.config(bg=DARK_GRAY, fg=WHITE, activebackground="#444C55")

    if solenoid_on:
        solenoid_on_btn.config(bg=SUCCESS, fg=WHITE, activebackground=SUCCESS_BRIGHT)
        solenoid_off_btn.config(bg="#DDE5EF", fg=DARK_GRAY, activebackground="#EDF3F9")
    else:
        solenoid_on_btn.config(bg="#DDE5EF", fg=DARK_GRAY, activebackground="#EDF3F9")
        solenoid_off_btn.config(bg=DARK_GRAY, fg=WHITE, activebackground="#444C55")

# ---------------------------------------------------------
# POSE UPDATE
# vals are in REAL ROBOT ORDER
# [base, link1, link2, link3, tool]
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

def run_sequence(sequence, idx=0):
    if action_cancelled:
        return
    if idx >= len(sequence):
        return

    item = sequence[idx]
    move = item["move"]
    pause_ms = item.get("pause_ms", 0)
    display_cmd = item.get("display", None)

    if display_cmd:
        display(display_cmd)

    def after_move():
        if action_cancelled:
            return
        if pause_ms > 0:
            root.after(pause_ms, lambda: run_sequence(sequence, idx + 1))
        else:
            run_sequence(sequence, idx + 1)

    animate_move(move, on_done=after_move)

def start_action(sequence):
    global is_animating, action_cancelled
    if is_animating:
        return
    action_cancelled = False
    run_sequence(sequence)

def cancel_action():
    global action_cancelled
    action_cancelled = True

# ---------------------------------------------------------
# COMMANDS
# ---------------------------------------------------------
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
    servo_test_var.set(f"{servo_test_slider.get():3d}°")
    send_test_servo(servo_test_slider.get())

def go_home():
    start_action([
        {"display": "SMILE", "move": [90, 90, 90, 90, 90], "pause_ms": 0}
    ])

def actionA():
    start_action([
        {"display": "A", "move": [90, 150, 120, 90, 120], "pause_ms": 500},
        {"move": [115, 150, 120, 90, 120], "pause_ms": 500},
        {"move": [115, 150, 120, 90, 75],  "pause_ms": 500},
        {"move": [60, 150, 120, 90, 75],   "pause_ms": 500},
        {"move": [60, 150, 120, 90, 120],  "pause_ms": 500},
        {"move": [115, 150, 120, 90, 120], "pause_ms": 500},
        {"move": [115, 150, 120, 90, 75],  "pause_ms": 500},
        {"move": [60, 150, 120, 90, 75],   "pause_ms": 500},
        {"move": [60, 90, 90, 90, 90],     "pause_ms": 0},
        {"display": "SMILE", "move": [90, 90, 90, 90, 90], "pause_ms": 0},
    ])

def actionB():
    seq = [
        {"display": "B", "move": [90, 90, 152, 90, 130], "pause_ms": 500},
        {"move": [115, 90, 152, 90, 130], "pause_ms": 500},
        {"move": [115, 90, 152, 90, 50],  "pause_ms": 500},
        {"move": [60, 90, 152, 90, 50],   "pause_ms": 500},
        {"move": [60, 90, 152, 90, 130],  "pause_ms": 500},
        {"move": [115, 90, 152, 90, 130], "pause_ms": 500},
        {"move": [115, 90, 152, 90, 50],  "pause_ms": 500},
        {"move": [60, 90, 152, 90, 50],   "pause_ms": 500},
        {"move": [60, 90, 152, 90, 130],  "pause_ms": 500},
        {"move": [115, 90, 152, 90, 130], "pause_ms": 500},
        {"move": [115, 90, 152, 90, 50],  "pause_ms": 500},
        {"move": [60, 90, 152, 90, 50],   "pause_ms": 500},
        {"move": [60, 90, 90, 90, 90],    "pause_ms": 0},
        {"display": "SMILE", "move": [90, 90, 90, 90, 90], "pause_ms": 0},
    ]
    start_action(seq)

def actionC():
    seq = [
        {"display": "C", "move": [90, 134, 151, 90, 125], "pause_ms": 0},
        {"move": [115, 134, 151, 90, 125], "pause_ms": 0},
        {"move": [115, 134, 115, 90, 77],  "pause_ms": 0},
        {"move": [115, 134, 115, 90, 77],  "pause_ms": 0},
        {"move": [90, 134, 115, 90, 77],   "pause_ms": 0},

        {"move": [90, 134, 151, 90, 125], "pause_ms": 0},
        {"move": [115, 134, 151, 90, 125], "pause_ms": 0},
        {"move": [115, 134, 115, 90, 77],  "pause_ms": 0},
        {"move": [115, 134, 115, 90, 77],  "pause_ms": 0},
        {"move": [90, 134, 115, 90, 77],   "pause_ms": 0},

        {"move": [90, 134, 151, 90, 125], "pause_ms": 0},
        {"move": [115, 134, 151, 90, 125], "pause_ms": 0},
        {"move": [115, 134, 115, 90, 77],  "pause_ms": 0},
        {"move": [115, 134, 115, 90, 77],  "pause_ms": 0},
        {"move": [90, 134, 115, 90, 77],   "pause_ms": 0},

        {"move": [90, 134, 151, 90, 125], "pause_ms": 0},
        {"move": [115, 134, 151, 90, 125], "pause_ms": 0},
        {"move": [115, 134, 115, 90, 77],  "pause_ms": 0},
        {"move": [115, 134, 115, 90, 77],  "pause_ms": 0},
        {"move": [90, 134, 115, 90, 77],   "pause_ms": 0},

        {"move": [90, 120, 140, 90, 90], "pause_ms": 0},
        {"move": [90, 120, 155, 90, 90], "pause_ms": 0},
        {"move": [90, 120, 140, 90, 90], "pause_ms": 0},
        {"move": [90, 120, 155, 90, 90], "pause_ms": 0},
        {"move": [90, 120, 140, 90, 90], "pause_ms": 0},
        {"move": [90, 120, 155, 90, 90], "pause_ms": 500},
        {"display": "SMILE", "move": [90, 90, 90, 90, 90], "pause_ms": 0},
    ]
    start_action(seq)

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
    slider_body, "Gripper",
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

# New Servo Test slider
servo_test_slider = LimitedSlider(
    slider_body, "Servo Test  (Pin 31)",
    full_min=0, full_max=180,
    work_min=WORK_MIN["test"], work_max=WORK_MAX["test"],
    initial=90, command=servo_test_changed,
    active_color=TEST_TRACK_ACTIVE,
    thumb_outline=TEST_THUMB_OUTLINE,
    width=500
)
servo_test_slider.pack(fill="x", pady=(8, 4))

servo_test_var = tk.StringVar(value=" 90°")

aux_frame = tk.Frame(slider_body, bg=PANEL_BG)
aux_frame.pack(fill="x", pady=(10, 4))

# Magnet controls
magnet_card = tk.Frame(aux_frame, bg=PANEL_BG)
magnet_card.pack(fill="x", pady=(0, 8))

tk.Label(magnet_card, text="Magnet (P4)", bg=PANEL_BG, fg=DARK_GRAY, font=SANS_B).pack(anchor="w")
magnet_btn_row = tk.Frame(magnet_card, bg=PANEL_BG)
magnet_btn_row.pack(anchor="w", pady=(4, 0))

magnet_on_btn = abb_button(magnet_btn_row, "ON", lambda: set_magnet(True), width=12)
magnet_on_btn.pack(side="left")
magnet_off_btn = abb_button(magnet_btn_row, "OFF", lambda: set_magnet(False), width=12)
magnet_off_btn.pack(side="left", padx=(8, 0))

# Vacuum controls
vacuum_card = tk.Frame(aux_frame, bg=PANEL_BG)
vacuum_card.pack(fill="x", pady=(0, 8))

tk.Label(vacuum_card, text="Vacuum (P3)", bg=PANEL_BG, fg=DARK_GRAY, font=SANS_B).pack(anchor="w")
vacuum_btn_row = tk.Frame(vacuum_card, bg=PANEL_BG)
vacuum_btn_row.pack(anchor="w", pady=(4, 0))

vacuum_on_btn = abb_button(vacuum_btn_row, "ON", lambda: set_vacuum(True), width=12)
vacuum_on_btn.pack(side="left")
vacuum_off_btn = abb_button(vacuum_btn_row, "OFF", lambda: set_vacuum(False), width=12)
vacuum_off_btn.pack(side="left", padx=(8, 0))

# Solenoid controls
solenoid_card = tk.Frame(aux_frame, bg=PANEL_BG)
solenoid_card.pack(fill="x")

tk.Label(solenoid_card, text="Solenoid (P2)", bg=PANEL_BG, fg=DARK_GRAY, font=SANS_B).pack(anchor="w")
solenoid_btn_row = tk.Frame(solenoid_card, bg=PANEL_BG)
solenoid_btn_row.pack(anchor="w", pady=(4, 0))

solenoid_on_btn = abb_button(solenoid_btn_row, "ON", lambda: set_solenoid(True), width=12)
solenoid_on_btn.pack(side="left")
solenoid_off_btn = abb_button(solenoid_btn_row, "OFF", lambda: set_solenoid(False), width=12)
solenoid_off_btn.pack(side="left", padx=(8, 0))

update_aux_buttons()

legend = tk.Label(
    slider_body,
    text="Light gray = blocked zone   |   Blue = working zone   |   Marker = 90° center",
    bg=PANEL_BG,
    fg=MID_GRAY,
    font=SANS_S,
    anchor="w"
)
legend.pack(fill="x", pady=(8, 0))

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

canvas_wrap = tk.Frame(view_card, bg=PANEL_BG)
canvas_wrap.pack(fill="both", expand=True, padx=12, pady=10)

arm = ArmCanvas(canvas_wrap)

overlay_wrap = tk.Frame(canvas_wrap, bg=PANEL_BG)
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
    ("TOOL",   tool_var),
    ("LINK 3", link3_var),
    ("LINK 2", link2_var),
    ("LINK 1", link1_var),
    ("BASE",   base_var),
]:
    row = tk.Frame(joint_body, bg=WHITE)
    row.pack(fill="x")
    tk.Label(row, text=f"{lbl}:", bg=WHITE, fg=DARK_GRAY, font=("Segoe UI", 8, "bold"), width=8, anchor="w").pack(side="left")
    tk.Label(row, textvariable=var, bg=WHITE, fg=DARK_GRAY, font=("Consolas", 8), width=6, anchor="e").pack(side="left")

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
    arm.draw()

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

tk.Label(
    bottom_controls,
    text="Drag canvas to orbit",
    bg=PANEL_BG,
    fg=LIGHT_GRAY,
    font=SANS_S
).pack(side="right")

# ---------------------------------------------------------
# PROGRAM SEQUENCES CARD UNDER VIEW SECTION
# ---------------------------------------------------------
program_card = make_card(right_col)
program_card.pack(fill="x", pady=(10, 0))
section_header(program_card, "Program Sequences")

program_body = tk.Frame(program_card, bg=PANEL_BG)
program_body.pack(fill="x", padx=12, pady=12)

abb_button(program_body, "Home", go_home, width=10, style="home").pack(side="left")
abb_button(program_body, "Action A", actionA, width=10, style="primary").pack(side="left", padx=(8, 0))
abb_button(program_body, "Action B", actionB, width=10, style="primary").pack(side="left", padx=(8, 0))
abb_button(program_body, "Action C", actionC, width=10, style="primary").pack(side="left", padx=(8, 0))
abb_button(program_body, "Stop", cancel_action, width=10, style="danger").pack(side="left", padx=(8, 0))

# ---------------------------------------------------------
# FOOTER
# ---------------------------------------------------------
footer = tk.Frame(root, bg=ULTRAMARINE, height=28)
footer.pack(fill="x", side="bottom")
footer.pack_propagate(False)

tk.Label(
    footer,
    text="Sponsored by Los Alamos National Lab | Savannah River National Laboratory | TECHSOURCE",
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

update_pose([90, 90, 90, 90, 90], send_serial=False)
servo_test_slider.set(90)
servo_test_changed()
info_loop()

root.mainloop()
