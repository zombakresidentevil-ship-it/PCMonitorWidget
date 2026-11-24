# AERO PC MONITOR — compact Aero Glass widget for Windows 10/11
import ctypes
import subprocess
import tkinter as tk
import time
import winreg
import psutil

BG = "#0b1726"
PANEL = "#142b40"
PANEL2 = "#19364e"
EDGE = "#426681"
TEXT = "#edf7ff"
MUTED = "#91aec4"
BLUE = "#76caff"
GREEN = "#83e3bd"
GOLD = "#f2ce8a"
W, H = 340, 474

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
        return ((m.ullTotalPhys-m.ullAvailPhys)/1024**3, m.ullTotalPhys/1024**3)
    return 0, 0

def cpu_name():
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        return winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
    except Exception:
        return "Процессор Windows"

def disk_models():
    try:
        cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
               "Get-CimInstance Win32_DiskDrive | Select-Object -ExpandProperty Model"]
        raw = subprocess.check_output(cmd, creationflags=0x08000000,
            text=True, encoding="utf-8", errors="replace", timeout=5)
        return [x.strip() for x in raw.splitlines() if x.strip()]
    except Exception:
        return []

def wifi_info():
    try:
        raw = subprocess.check_output(["netsh", "wlan", "show", "interfaces"],
            creationflags=0x08000000, text=True, encoding="utf-8",
            errors="ignore", timeout=2)
        for line in raw.splitlines():
            if line.strip().lower().startswith("ssid") and "bssid" not in line.lower():
                value = line.split(":", 1)[-1].strip()
                if value: return value
        return "Wi-Fi не подключён"
    except Exception:
        return "Сеть Windows"

def gpu_load():
    try:
        cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
          "(Get-Counter '\\GPU Engine(*)\\Utilization Percentage' -ErrorAction Stop).CounterSamples | Measure-Object -Property CookedValue -Sum | Select-Object -ExpandProperty Sum"]
        raw = subprocess.check_output(cmd, creationflags=0x08000000,
            text=True, stderr=subprocess.DEVNULL, timeout=3).strip()
        return min(100, max(0, float(raw))) if raw else None
    except Exception:
        return None

class Widget:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("AERO PC MONITOR")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.97)
        self.root.configure(bg=BG)
        self.root.geometry(f"{W}x{H}+120+100")
        self.root.resizable(False, False)
        self.drag = (0, 0)
        self.cpu = cpu_name()
        self.cores = psutil.cpu_count(logical=False) or 0
        self.threads = psutil.cpu_count(logical=True) or 0
        self.models = disk_models()
        self.last_disk_poll = time.monotonic()
        self.last_gpu_poll = 0
        self.last_wifi_poll = 0
        self.gpu = None
        self.ssid = "Поиск сети…"
        self.last_net = psutil.net_io_counters()
        self.last_time = time.monotonic()
        self.build()
        psutil.cpu_percent(interval=None)
        self.update()
        self.root.mainloop()

    def build(self):
        c = self.canvas = tk.Canvas(self.root, width=W, height=H, bg=BG,
            highlightthickness=1, highlightbackground=EDGE)
        c.pack(fill="both", expand=True)
        c.create_rectangle(1, 1, W-1, H-1, fill=BG, outline=EDGE)
        c.create_rectangle(2, 2, W-2, 51, fill="#193750", outline="")
        c.create_line(8, 50, W-8, 50, fill="#6b9cbb")
        self.txt(15, 8, "AERO PC MONITOR", 11, "#d9f1ff", "bold")
        self.txt(15, 29, "СИСТЕМА МОНИТОРИНГА В РЕАЛЬНОМ ВРЕМЕНИ", 6, "#a8c4d8")
        c.create_text(298, 17, text="–", fill=TEXT, font=("Segoe UI", 14), tags="min")
        c.create_text(320, 17, text="×", fill=TEXT, font=("Segoe UI", 13), tags="close")
        c.tag_bind("min", "<Button-1>", lambda e: self.root.iconify())
        c.tag_bind("close", "<Button-1>", lambda e: self.root.destroy())
        c.bind("<Button-1>", self.start_move)
        c.bind("<B1-Motion>", self.move)
        self.metric(12, 58, 154, "ПРОЦЕССОР", "cpu", BLUE)
        self.metric(174, 58, 154, "ВИДЕОКАРТА", "gpu", GREEN)
        self.panel(12, 146, 316, 35, "ПРОЦЕССОР • МОДЕЛЬ")
        self.txt(22, 163, self.cpu[:48], 8, TEXT, tag="cpuname")
        self.txt(22, 174, f"{self.cores} ядер  •  {self.threads} потоков", 7, MUTED, tag="coreinfo")
        self.panel(12, 188, 316, 63, "ОПЕРАТИВНАЯ ПАМЯТЬ")
        self.txt(23, 207, "—", 19, TEXT, "bold", "ram")
        self.txt(105, 215, "из — ГБ", 9, MUTED, tag="ramtotal")
        self.bar(23, 238, 294, "rambar", BLUE)
        self.panel(12, 258, 316, 73, "ЖЁСТКИЕ ДИСКИ / SSD")
        self.txt(23, 278, "Определение моделей…", 8, TEXT, tag="diskmodels")
        self.txt(23, 306, "Разделы: —", 8, MUTED, tag="diskusage")
        self.panel(12, 338, 316, 124, "СЕТЬ • WI-FI / ETHERNET")
        self.txt(23, 360, "Поиск сети…", 9, TEXT, "bold", "ssid")
        self.txt(23, 381, "IP: —", 8, MUTED, tag="ip")
        self.txt(23, 410, "↓ — КБ/с", 9, BLUE, "bold", "down")
        self.txt(180, 410, "↑ — КБ/с", 9, GREEN, "bold", "up")
        self.txt(23, 440, "Обновление данных каждые 1,5 сек.", 7, MUTED)
        self.root.bind("<Escape>", lambda e: self.root.destroy())

    def txt(self, x, y, value, size, color, weight="normal", tag=None):
        return self.canvas.create_text(x, y, text=value, anchor="nw",
            fill=color, font=("Segoe UI", size, weight), tags=tag or ())

    def panel(self, x, y, w, h, title):
        self.canvas.create_rectangle(x, y, x+w, y+h, fill=PANEL,
            outline="#2e5069", width=1)
        self.txt(x+10, y+5, title, 7, MUTED, "bold")

    def metric(self, x, y, w, title, prefix, color):
        self.panel(x, y, w, 82, title)
        self.txt(x+10, y+21, "—%", 23, TEXT, "bold", prefix+"load")
        self.txt(x+11, y+49, "ЗАГРУЗКА", 6, MUTED)
        self.txt(x+91, y+25, "—°C", 14, color, "bold", prefix+"temp")
        self.txt(x+94, y+49, "ТЕМП.", 6, MUTED)
        self.bar(x+10, y+68, w-20, prefix+"bar", color)

    def bar(self, x, y, w, tag, color):
        self.canvas.create_rectangle(x, y, x+w, y+4, fill="#30485b", outline="")
        self.canvas.create_rectangle(x, y, x, y+4, fill=color, outline="", tags=tag)

    def set_text(self, tag, value):
        self.canvas.itemconfigure(tag, text=value)

    def set_bar(self, tag, x, y, w, value, color):
        self.canvas.delete(tag)
        end = x+w*max(0, min(100, value))/100
        self.canvas.create_rectangle(x, y, end, y+4, fill=color, outline="", tags=tag)

    def start_move(self, event):
        self.drag = (event.x_root-self.root.winfo_x(), event.y_root-self.root.winfo_y())

    def move(self, event):
        self.root.geometry(f"+{event.x_root-self.drag[0]}+{event.y_root-self.drag[1]}")

    def update(self):
        try:
            cpu = psutil.cpu_percent(interval=None)
            used, total = memory()
            self.set_text("cpuload", f"{cpu:.0f}%")
            self.set_bar("cpubar", 22, 126, 134, cpu, BLUE)
            self.set_text("ram", f"{used:.1f} ГБ")
            self.set_text("ramtotal", f"из {total:.1f} ГБ")
            self.set_bar("rambar", 23, 238, 294, used/total*100 if total else 0, BLUE)
            if time.monotonic()-self.last_gpu_poll >= 5:
                self.gpu = gpu_load()
                self.last_gpu_poll = time.monotonic()
            self.set_text("gpuload", f"{self.gpu:.0f}%" if self.gpu is not None else "—%")
            self.set_bar("gpubar", 184, 126, 134, self.gpu or 0, GREEN)

            if time.monotonic()-self.last_disk_poll >= 60:
                self.models = disk_models()
                self.last_disk_poll = time.monotonic()
            model_text = "  |  ".join(self.models[:2]) if self.models else "Модели не определены"
            self.set_text("diskmodels", model_text[:58])
            parts = []
            for p in psutil.disk_partitions():
                if "cdrom" in p.opts.lower(): continue
                try:
                    u = psutil.disk_usage(p.mountpoint)
                    if p.mountpoint[:2].upper() in ("C:", "D:", "E:"):
                        parts.append(f"{p.mountpoint[:2]} {u.percent}%")
                except Exception:
                    pass
            self.set_text("diskusage", "Разделы: " + ("   •   ".join(parts[:3]) or "—"))

            if time.monotonic()-self.last_wifi_poll >= 8:
                self.ssid = wifi_info()
                self.last_wifi_poll = time.monotonic()
            self.set_text("ssid", self.ssid[:42])
            ip = next((a.address for vals in psutil.net_if_addrs().values()
                for a in vals if a.family == 2 and not a.address.startswith("127.")), "—")
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
    Widget()
