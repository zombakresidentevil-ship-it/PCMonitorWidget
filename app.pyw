# Aero Monitor — lightweight Python edition
# Windows 10/11, Python 3.10+
import ctypes
import subprocess
import tkinter as tk
import tkinter.font as tkfont
import time
import shutil
import psutil

BG = "#101d2d"
PANEL = "#20364b"
EDGE = "#52758f"
TEXT = "#f1f7fc"
MUTED = "#9bb6ca"
BLUE = "#72c8ff"
GREEN = "#82e5bd"

class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

def memory():
    m = MEMORYSTATUSEX()
    m.dwLength = ctypes.sizeof(m)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
        total = m.ullTotalPhys / 1024**3
        used = (m.ullTotalPhys - m.ullAvailPhys) / 1024**3
        return used, total
    return 0, 0

def wifi_info():
    try:
        out = subprocess.check_output(["netsh", "wlan", "show", "interfaces"],
                                      creationflags=0x08000000, text=True,
                                      encoding="utf-8", errors="ignore", timeout=2)
        ssid = ""
        for line in out.splitlines():
            if line.strip().lower().startswith("ssid") and "bssid" not in line.lower():
                ssid = line.split(":", 1)[-1].strip()
                if ssid: break
        return ssid or "Wi-Fi не подключён"
    except Exception:
        return "Сеть Windows"

def gpu_load():
    # Windows GPU Engine performance counter; no third-party sensor driver required.
    try:
        cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
               "(Get-Counter '\\GPU Engine(*)\\Utilization Percentage' -ErrorAction Stop).CounterSamples | "
               "Measure-Object -Property CookedValue -Sum | Select-Object -ExpandProperty Sum"]
        raw = subprocess.check_output(cmd, creationflags=0x08000000, text=True,
                                      stderr=subprocess.DEVNULL, timeout=3).strip()
        return min(100, max(0, float(raw))) if raw else None
    except Exception:
        return None

class Widget:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Aero Monitor")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.96)
        self.root.configure(bg=BG)
        self.root.geometry("326x438+120+120")
        self.root.resizable(False, False)
        self.drag = (0, 0)
        self.last_net = psutil.net_io_counters()
        self.last_time = time.monotonic()
        self.cpu_temp = "—"
        self.gpu_temp = "—"
        self.gpu_value = None
        self.build()
        self.update()
        self.root.mainloop()

    def build(self):
        self.canvas = tk.Canvas(self.root, width=326, height=438, bg=BG,
                                highlightthickness=1, highlightbackground=EDGE)
        self.canvas.pack(fill="both", expand=True)
        c = self.canvas
        c.create_rectangle(1, 1, 325, 437, fill=BG, outline=EDGE, width=1)
        c.create_rectangle(2, 2, 324, 54, fill="#1b344a", outline="")
        self.txt(17, 12, "AERO MONITOR", 10, "#c6eaff", "bold")
        self.txt(17, 30, "СИСТЕМА В РЕАЛЬНОМ ВРЕМЕНИ", 7, MUTED)
        c.create_text(279, 20, text="–", fill=TEXT, font=("Segoe UI", 14),
                      tags="min")
        c.create_text(305, 20, text="×", fill=TEXT, font=("Segoe UI", 14),
                      tags="close")
        c.tag_bind("min", "<Button-1>", lambda e: self.root.iconify())
        c.tag_bind("close", "<Button-1>", lambda e: self.root.destroy())
        c.bind("<Button-1>", self.start_move)
        c.bind("<B1-Motion>", self.move)
        self.metric(16, 62, "ПРОЦЕССОР", "cpu")
        self.metric(170, 62, "ВИДЕОКАРТА", "gpu")
        self.panel(16, 168, 294, 76, "ОПЕРАТИВНАЯ ПАМЯТЬ")
        self.txt(29, 190, "—", 21, TEXT, "bold", "ram")
        self.txt(113, 198, "из — ГБ", 10, MUTED, tag="ramtotal")
        self.bar(29, 225, 267, "rambar", BLUE)
        self.panel(16, 254, 294, 48, "НАКОПИТЕЛИ")
        self.txt(29, 278, "Проверка…", 9, TEXT, tag="disk")
        self.panel(16, 312, 294, 106, "СЕТЬ • WI-FI / ETHERNET")
        self.txt(29, 335, "Поиск сети…", 10, TEXT, "bold", "ssid")
        self.txt(29, 354, "IP: —", 8, MUTED, tag="ip")
        self.txt(29, 378, "↓ — КБ/с", 10, BLUE, "bold", "down")
        self.txt(166, 378, "↑ — КБ/с", 10, GREEN, "bold", "up")
        self.root.bind("<Escape>", lambda e: self.root.destroy())

    def txt(self, x, y, value, size, color, weight="normal", tag=None):
        return self.canvas.create_text(x, y, text=value, anchor="nw",
                 fill=color, font=("Segoe UI", size, weight), tags=tag or ())

    def panel(self, x, y, w, h, title):
        self.canvas.create_rectangle(x, y, x+w, y+h, fill=PANEL, outline="#36556d")
        self.txt(x+12, y+8, title, 7, MUTED, "bold")

    def metric(self, x, y, title, prefix):
        self.panel(x, y, 140, 92, title)
        self.txt(x+12, y+26, "—%", 25, TEXT, "bold", prefix+"load")
        self.txt(x+13, y+57, "ЗАГРУЗКА", 7, MUTED)
        self.txt(x+76, y+29, "—°C", 15, BLUE if prefix=="cpu" else GREEN,
                 "bold", prefix+"temp")
        self.txt(x+79, y+57, "ТЕМП.", 7, MUTED)
        self.bar(x+12, y+76, 116, prefix+"bar",
                 BLUE if prefix=="cpu" else GREEN)

    def bar(self, x, y, w, tag, color):
        self.canvas.create_rectangle(x, y, x+w, y+5, fill="#344d61", outline="")
        self.canvas.create_rectangle(x, y, x, y+5, fill=color, outline="", tags=tag)

    def set_text(self, tag, value):
        self.canvas.itemconfigure(tag, text=value)

    def set_bar(self, tag, x, y, w, value, color):
        self.canvas.delete(tag)
        self.canvas.create_rectangle(x, y, x+w*max(0,min(100,value))/100, y+5,
                                     fill=color, outline="", tags=tag)

    def start_move(self, event):
        self.drag = (event.x_root-self.root.winfo_x(), event.y_root-self.root.winfo_y())

    def move(self, event):
        x = event.x_root-self.drag[0]
        y = event.y_root-self.drag[1]
        self.root.geometry(f"+{x}+{y}")

    def update(self):
        try:
            cpu = psutil.cpu_percent(interval=None)
            used, total = memory()
            self.set_text("cpuload", f"{cpu:.0f}%")
            self.set_bar("cpubar", 28, 138, 116, cpu, BLUE)
            self.set_text("cputemp", f"{self.cpu_temp}°C")
            self.set_text("ram", f"{used:.1f} ГБ")
            self.set_text("ramtotal", f"из {total:.1f} ГБ")
            self.set_bar("rambar", 29, 225, 267, used/total*100 if total else 0, BLUE)

            if int(time.monotonic()) % 4 == 0:
                self.gpu_value = gpu_load()
            self.set_text("gpuload", f"{self.gpu_value:.0f}%" if self.gpu_value is not None else "—%")
            self.set_bar("gpubar", 182, 138, 116, self.gpu_value or 0, GREEN)
            self.set_text("gputemp", f"{self.gpu_temp}°C")

            disks = []
            for part in psutil.disk_partitions():
                if "cdrom" in part.opts.lower(): continue
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    if part.mountpoint in ("C:\\", "D:\\"):
                        disks.append(f"{part.mountpoint[:2]}  {usage.percent}%")
                except Exception: pass
            self.set_text("disk", "     ".join(disks[:2]) or "Диски не найдены")

            ssid = wifi_info()
            self.set_text("ssid", ssid[:34])
            addrs = psutil.net_if_addrs()
            ip = next((a.address for values in addrs.values() for a in values
                       if a.family == 2 and not a.address.startswith("127.")), "—")
            self.set_text("ip", "IP: " + ip)
            now = time.monotonic()
            net = psutil.net_io_counters()
            dt = max(.1, now-self.last_time)
            down = max(0, net.bytes_recv-self.last_net.bytes_recv)/dt/1024
            up = max(0, net.bytes_sent-self.last_net.bytes_sent)/dt/1024
            self.set_text("down", "↓ " + self.speed(down))
            self.set_text("up", "↑ " + self.speed(up))
            self.last_net, self.last_time = net, now
        except Exception:
            pass
        self.root.after(1500, self.update)

    @staticmethod
    def speed(kb):
        return f"{kb/1024:.2f} МБ/с" if kb >= 1024 else f"{kb:.1f} КБ/с"

if __name__ == "__main__":
    psutil.cpu_percent(interval=None)
    Widget()
