# AERO PC MONITOR — Aero Glass desktop widget for Windows 10/11
import ctypes
import colorsys
import json
import os
import subprocess
import time
import tkinter as tk
import winreg
from pathlib import Path

import psutil

W = 370
BG_HUE = 0.57
DEFAULT_ALPHA = 0.96
SETTINGS_FILE = Path(os.getenv("APPDATA", str(Path.home()))) / "AeroPCMonitor" / "settings.json"

TEXT = "#edf7ff"
MUTED = "#91aec4"
GREEN = "#72d9a9"
YELLOW = "#e6bd62"
RED = "#e47777"

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
        return m.ullTotalPhys - m.ullAvailPhys, m.ullTotalPhys
    return 0, 0

def cpu_name():
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            return winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
    except Exception:
        return "Процессор Windows"

def wifi_info():
    try:
        raw = subprocess.check_output(["netsh", "wlan", "show", "interfaces"],
            creationflags=0x08000000, text=True, encoding="utf-8",
            errors="ignore", timeout=2)
        for line in raw.splitlines():
            if line.strip().lower().startswith("ssid") and "bssid" not in line.lower():
                value = line.split(":", 1)[-1].strip()
                if value:
                    return value
        return "Wi-Fi не подключён"
    except Exception:
        return "Сеть Windows"

def gpu_load():
    try:
        cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
          "(Get-Counter '\\GPU Engine(*)\\Utilization Percentage' -ErrorAction Stop).CounterSamples | Measure-Object -Property CookedValue -Sum | Select-Object -ExpandProperty Sum"]
        raw = subprocess.check_output(cmd, creationflags=0x08000000,
            text=True, stderr=subprocess.DEVNULL, timeout=3).strip()
        return min(100.0, max(0.0, float(raw))) if raw else None
    except Exception:
        return None

def temperatures():
    # Real readings are queried from LibreHardwareMonitor/OpenHardwareMonitor WMI providers.
    # If no provider is installed/enabled, show unavailable rather than inventing values.
    script = r"""
$namespaces = @('root/LibreHardwareMonitor','root/OpenHardwareMonitor')
foreach ($ns in $namespaces) {
  try {
    $sensors = Get-CimInstance -Namespace $ns -ClassName Sensor -ErrorAction Stop |
      Where-Object { $_.SensorType -eq 'Temperature' }
    if ($sensors) {
      $sensors | ForEach-Object {
        [PSCustomObject]@{ Hardware=$_.Parent; Name=$_.Name; Value=$_.Value; Identifier=$_.Identifier }
      } | ConvertTo-Json -Compress
      exit
    }
  } catch {}
}
"""
    try:
        raw = subprocess.check_output(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            creationflags=0x08000000, text=True, encoding="utf-8",
            errors="replace", stderr=subprocess.DEVNULL, timeout=5).strip()
        if not raw:
            return None, None
        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]
        cpu_values, gpu_values = [], []
        for item in data:
            try:
                value = float(item.get("Value"))
                if not (-10 <= value <= 150):
                    continue
                label = (str(item.get("Hardware", "")) + " " +
                         str(item.get("Name", "")) + " " +
                         str(item.get("Identifier", ""))).lower()
                if any(k in label for k in ("gpu", "radeon", "rx 580", "graphics")):
                    gpu_values.append(value)
                elif any(k in label for k in ("cpu", "xeon", "processor", "package", "core")):
                    cpu_values.append(value)
            except Exception:
                pass
        return (max(cpu_values) if cpu_values else None,
                max(gpu_values) if gpu_values else None)
    except Exception:
        return None, None

def partitions():
    result = []
    for p in psutil.disk_partitions(all=False):
        if "cdrom" in p.opts.lower():
            continue
        try:
            usage = psutil.disk_usage(p.mountpoint)
            result.append((p.device[:2].upper() or p.mountpoint, usage.total, usage.free, usage.percent))
        except Exception:
            pass
    # Avoid duplicate drive letters returned by unusual mount configurations.
    unique = {}
    for item in result:
        unique[item[0]] = item
    return list(unique.values())

def fmt_gb(value):
    return f"{value / (1024 ** 3):.0f}"

def mix_color(hue, sat, val):
    r, g, b = colorsys.hsv_to_rgb(hue % 1.0, sat, val)
    return "#%02x%02x%02x" % (int(r*255), int(g*255), int(b*255))

class Widget:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("AERO PC MONITOR")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#0b1726")
        self.drag = (0, 0)
        self.cpu = cpu_name()
        self.cores = psutil.cpu_count(logical=False) or 0
        self.threads = psutil.cpu_count(logical=True) or 0
        self.ssid = "Поиск сети…"
        self.ip = "—"
        self.gpu = None
        self.cpu_temp = None
        self.gpu_temp = None
        self.last_gpu = 0
        self.last_temp = 0
        self.last_wifi = 0
        self.last_disks = 0
        self.drives = partitions()
        self.last_net = psutil.net_io_counters()
        self.last_time = time.monotonic()
        self.alpha = DEFAULT_ALPHA
        self.hue = BG_HUE
        self.saved_alpha = self.alpha
        self.saved_hue = self.hue
        self.load_settings()
        psutil.cpu_percent(interval=None)
        self.show_main()
        self.update_data()
        self.root.mainloop()

    def load_settings(self):
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            self.alpha = min(0.98, max(0.55, float(data.get("alpha", DEFAULT_ALPHA))))
            self.hue = (float(data.get("hue", BG_HUE)) % 360) / 360
        except Exception:
            pass
        self.saved_alpha, self.saved_hue = self.alpha, self.hue
        self.apply_window_alpha()

    def save_settings(self):
        try:
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps({
                "alpha": self.alpha, "hue": self.hue * 360
            }), encoding="utf-8")
        except Exception:
            pass

    def palette(self):
        return {
            "bg": mix_color(self.hue, .58, .105),
            "header": mix_color(self.hue, .62, .19),
            "panel": mix_color(self.hue, .52, .17),
            "panel2": mix_color(self.hue, .56, .22),
            "edge": mix_color(self.hue, .42, .43),
            "accent": mix_color(self.hue, .48, .96),
            "accent2": mix_color((self.hue + .10) % 1, .45, .91),
            "track": mix_color(self.hue, .28, .29),
        }

    def apply_window_alpha(self):
        try:
            self.root.attributes("-alpha", self.alpha)
        except Exception:
            pass

    def paint(self):
        p = self.palette()
        self.root.configure(bg=p["bg"])
        if hasattr(self, "canvas"):
            self.canvas.configure(bg=p["bg"], highlightbackground=p["edge"])
            self.canvas.delete("all")
            if self.screen == "main":
                self.draw_main()
            else:
                self.draw_settings()

    def show_main(self):
        self.screen = "main"
        self.clear_screen()
        self.apply_window_alpha()
        self.root.geometry(f"{W}x{self.main_height()}+120+90")
        self.canvas = tk.Canvas(self.root, width=W, height=self.main_height(),
            bg=self.palette()["bg"], highlightthickness=1,
            highlightbackground=self.palette()["edge"])
        self.canvas.pack(fill="both", expand=True)
        self.draw_main()
        self.bind_drag()

    def clear_screen(self):
        for child in self.root.winfo_children():
            child.destroy()

    def main_height(self):
        # Each detected volume receives its own complete row.
        return 440 + max(1, len(self.drives)) * 48

    def bind_drag(self):
        self.canvas.bind("<Button-1>", self.start_move)
        self.canvas.bind("<B1-Motion>", self.move)

    def start_move(self, event):
        self.drag = (event.x_root-self.root.winfo_x(), event.y_root-self.root.winfo_y())

    def move(self, event):
        self.root.geometry(f"+{event.x_root-self.drag[0]}+{event.y_root-self.drag[1]}")

    def text(self, x, y, value, size=9, color=TEXT, weight="normal", anchor="nw", tags=None):
        return self.canvas.create_text(x, y, text=value, anchor=anchor,
            fill=color, font=("Segoe UI", size, weight), tags=tags or ())

    def panel(self, x, y, w, h, title):
        p = self.palette()
        self.canvas.create_rectangle(x, y, x+w, y+h, fill=p["panel"],
            outline=p["edge"], width=1, tags="panel_bg")
        self.text(x+11, y+7, title, 7, MUTED, "bold")

    def header(self, subtitle):
        p = self.palette()
        self.canvas.create_rectangle(1, 1, W-1, 49, fill=p["header"], outline="", tags="header_bg")
        self.canvas.create_line(8, 48, W-8, 48, fill=p["edge"])
        self.text(14, 7, "AERO PC MONITOR", 11, TEXT, "bold")
        self.text(14, 28, subtitle, 6, MUTED)
        # Gear, minimize and close buttons are drawn as distinct clickable controls.
        self.text(292, 12, "⚙", 13, TEXT, tags="settings_btn")
        self.text(326, 12, "–", 14, TEXT, tags="min_btn")
        self.text(350, 12, "×", 14, TEXT, tags="close_btn")
        self.canvas.tag_bind("settings_btn", "<Button-1>", lambda e: self.show_settings())
        self.canvas.tag_bind("min_btn", "<Button-1>", lambda e: self.root.iconify())
        self.canvas.tag_bind("close_btn", "<Button-1>", lambda e: self.root.destroy())

    def draw_bar(self, x, y, w, percent, color, tag=None, height=5):
        p = self.palette()
        self.canvas.create_rectangle(x, y, x+w, y+height, fill=p["track"], outline="")
        self.canvas.create_rectangle(x, y, x+w*max(0, min(100, percent))/100,
            y+height, fill=color, outline="", tags=tag or ())

    def draw_main(self):
        p = self.palette()
        self.header("СИСТЕМА МОНИТОРИНГА В РЕАЛЬНОМ ВРЕМЕНИ")
        self.panel(12, 58, 168, 91, "ПРОЦЕССОР")
        self.text(22, 78, self.cpu[:38], 8, TEXT, "bold")
        self.text(22, 98, "НАГРУЗКА", 6, MUTED)
        self.text(22, 108, "—%", 18, TEXT, "bold", tags="cpu_load")
        self.text(111, 99, "ТЕМПЕРАТУРА", 6, MUTED)
        self.text(111, 109, "—°C", 15, p["accent"], "bold", tags="cpu_temp")
        self.draw_bar(22, 137, 148, 0, p["accent"], "cpu_bar")

        self.panel(190, 58, 168, 91, "ВИДЕОКАРТА")
        self.text(200, 78, "GPU • WINDOWS", 8, TEXT, "bold")
        self.text(200, 98, "НАГРУЗКА", 6, MUTED)
        self.text(200, 108, "—%", 18, TEXT, "bold", tags="gpu_load")
        self.text(289, 99, "ТЕМПЕРАТУРА", 6, MUTED)
        self.text(289, 109, "—°C", 15, p["accent2"], "bold", tags="gpu_temp")
        self.draw_bar(200, 137, 148, 0, p["accent2"], "gpu_bar")

        self.text(14, 154, f"{self.cores} физических ядер  •  {self.threads} потоков", 7, MUTED)
        self.panel(12, 172, 346, 62, "ОПЕРАТИВНАЯ ПАМЯТЬ")
        self.text(23, 193, "— ГБ", 17, TEXT, "bold", tags="ram_used")
        self.text(112, 201, "из — ГБ", 8, MUTED, tags="ram_total")
        self.draw_bar(23, 222, 324, 0, p["accent"], "ram_bar", 5)

        disk_y = 244
        disk_h = max(1, len(self.drives)) * 48 + 25
        self.panel(12, disk_y, 346, disk_h, "НАКОПИТЕЛИ")
        if not self.drives:
            self.text(23, disk_y+28, "Накопители не обнаружены", 8, MUTED)
        for i, (letter, total, free, used_pct) in enumerate(self.drives):
            y = disk_y + 26 + i*48
            color = GREEN if used_pct < 70 else YELLOW if used_pct < 90 else RED
            self.text(23, y, f"ДИСК {letter}", 8, TEXT, "bold")
            self.text(347, y, f"{used_pct:.0f}%", 8, color, "bold", anchor="ne")
            self.text(23, y+14, f"Свободно {fmt_gb(free)} ГБ из {fmt_gb(total)} ГБ", 7, MUTED)
            self.draw_bar(23, y+32, 324, used_pct, color, f"drive_{i}", 5)

        net_y = disk_y + disk_h + 10
        self.panel(12, net_y, 346, 76, "СЕТЬ")
        self.text(23, net_y+25, self.ssid[:44], 8, TEXT, "bold", tags="ssid")
        self.text(23, net_y+43, "IP: " + self.ip, 7, MUTED, tags="ip")
        self.text(210, net_y+26, "↓ — КБ/с", 8, p["accent"], "bold", tags="net_down")
        self.text(210, net_y+45, "↑ — КБ/с", 8, p["accent2"], "bold", tags="net_up")
        self.root.geometry(f"{W}x{net_y+88}+{self.root.winfo_x()}+{self.root.winfo_y()}")

    def show_settings(self):
        self.saved_alpha, self.saved_hue = self.alpha, self.hue
        self.screen = "settings"
        self.clear_screen()
        self.root.geometry(f"{W}x330+{self.root.winfo_x()}+{self.root.winfo_y()}")
        self.canvas = tk.Canvas(self.root, width=W, height=330,
            bg=self.palette()["bg"], highlightthickness=1,
            highlightbackground=self.palette()["edge"])
        self.canvas.pack(fill="both", expand=True)
        self.draw_settings()
        self.bind_drag()

    def draw_settings(self):
        p = self.palette()
        self.header("НАСТРОЙКИ ОФОРМЛЕНИЯ")
        self.panel(12, 60, 346, 94, "ПРОЗРАЧНОСТЬ ОКНА")
        self.alpha_value = self.text(337, 81, f"{int(self.alpha*100)}%", 9, p["accent"], "bold", anchor="ne", tags="alpha_value")
        self.alpha_scale = tk.Scale(self.root, from_=55, to=98, orient="horizontal",
            showvalue=False, resolution=1, length=310, sliderlength=18,
            highlightthickness=0, bd=0, troughcolor=p["track"],
            bg=p["panel"], fg=TEXT, activebackground=p["accent"],
            command=self.change_alpha)
        self.alpha_scale.set(round(self.alpha*100))
        self.canvas.create_window(185, 119, window=self.alpha_scale, width=316, height=34)

        self.panel(12, 166, 346, 100, "ЦВЕТ ОФОРМЛЕНИЯ")
        self.hue_value = self.text(337, 187, f"{int(self.hue*360)}°", 9, p["accent"], "bold", anchor="ne", tags="hue_value")
        self.hue_scale = tk.Scale(self.root, from_=0, to=359, orient="horizontal",
            showvalue=False, resolution=1, length=310, sliderlength=18,
            highlightthickness=0, bd=0, troughcolor=p["track"],
            bg=p["panel"], fg=TEXT, activebackground=p["accent"],
            command=self.change_hue)
        self.hue_scale.set(round(self.hue*360))
        self.canvas.create_window(185, 225, window=self.hue_scale, width=316, height=34)

        self.canvas.create_rectangle(12, 278, 178, 316, fill=p["panel2"], outline=p["edge"], tags="cancel_btn")
        self.text(95, 288, "ОТМЕНА", 9, TEXT, "bold", anchor="n", tags="cancel_label")
        self.canvas.create_rectangle(192, 278, 358, 316, fill=p["accent"], outline="", tags="apply_btn")
        self.text(275, 288, "ПРИМЕНИТЬ", 9, p["bg"], "bold", anchor="n", tags="apply_label")
        for tag in ("cancel_btn", "cancel_label"):
            self.canvas.tag_bind(tag, "<Button-1>", lambda e: self.cancel_settings())
        for tag in ("apply_btn", "apply_label"):
            self.canvas.tag_bind(tag, "<Button-1>", lambda e: self.apply_settings())

    def change_alpha(self, value):
        self.alpha = int(float(value)) / 100
        self.apply_window_alpha()
        if hasattr(self, "alpha_value"):
            self.canvas.itemconfigure(self.alpha_value, text=f"{int(self.alpha*100)}%")

    def change_hue(self, value):
        self.hue = int(float(value)) / 360
        if hasattr(self, "hue_value"):
            self.canvas.itemconfigure(self.hue_value, text=f"{int(self.hue*360)}°")
        # Repaint the full settings view as the slider moves, while preserving its current value.
        if getattr(self, "screen", "") == "settings":
            self.refresh_settings_colors()

    def refresh_settings_colors(self):
        p = self.palette()
        self.root.configure(bg=p["bg"])
        self.canvas.configure(bg=p["bg"], highlightbackground=p["edge"])
        # Update the complete palette without rebuilding the active slider widgets.
        self.canvas.itemconfigure("panel_bg", fill=p["panel"], outline=p["edge"])
        self.canvas.itemconfigure("header_bg", fill=p["header"])
        for item in self.canvas.find_all():
            tags = self.canvas.gettags(item)
            if "cancel_btn" in tags:
                self.canvas.itemconfigure(item, fill=p["panel2"], outline=p["edge"])
            elif "apply_btn" in tags:
                self.canvas.itemconfigure(item, fill=p["accent"])
            elif "cancel_label" in tags:
                self.canvas.itemconfigure(item, fill=TEXT)
            elif "apply_label" in tags:
                self.canvas.itemconfigure(item, fill=p["bg"])
            elif "hue_value" in tags or "alpha_value" in tags:
                self.canvas.itemconfigure(item, fill=p["accent"])
        for scale in (self.alpha_scale, self.hue_scale):
            scale.configure(troughcolor=p["track"], bg=p["panel"], activebackground=p["accent"])

    def apply_settings(self):
        self.saved_alpha, self.saved_hue = self.alpha, self.hue
        self.save_settings()
        self.show_main()

    def cancel_settings(self):
        self.alpha, self.hue = self.saved_alpha, self.saved_hue
        self.apply_window_alpha()
        self.show_main()

    def set_text(self, tag, value):
        self.canvas.itemconfigure(tag, text=value)

    def update_data(self):
        try:
            now = time.monotonic()
            cpu = psutil.cpu_percent(interval=None)
            used, total = memory()
            if self.screen == "main":
                self.set_text("cpu_load", f"{cpu:.0f}%")
                self.set_text("ram_used", f"{used/1024**3:.1f} ГБ")
                self.set_text("ram_total", f"из {total/1024**3:.1f} ГБ")
                self.canvas.delete("ram_bar")
                self.draw_bar(23, 222, 324, used/total*100 if total else 0,
                    self.palette()["accent"], "ram_bar", 5)
                self.canvas.delete("cpu_bar")
                self.draw_bar(22, 137, 148, cpu, self.palette()["accent"], "cpu_bar")
                if now-self.last_gpu >= 5:
                    self.gpu = gpu_load()
                    self.last_gpu = now
                self.set_text("gpu_load", f"{self.gpu:.0f}%" if self.gpu is not None else "—%")
                self.canvas.delete("gpu_bar")
                self.draw_bar(200, 137, 148, self.gpu or 0,
                    self.palette()["accent2"], "gpu_bar")
                if now-self.last_temp >= 8:
                    self.cpu_temp, self.gpu_temp = temperatures()
                    self.last_temp = now
                self.set_text("cpu_temp", f"{self.cpu_temp:.0f}°C" if self.cpu_temp is not None else "н/д")
                self.set_text("gpu_temp", f"{self.gpu_temp:.0f}°C" if self.gpu_temp is not None else "н/д")
                if now-self.last_disks >= 10:
                    self.drives = partitions()
                    self.last_disks = now
                if now-self.last_wifi >= 8:
                    self.ssid = wifi_info()
                    self.last_wifi = now
                    self.ip = next((a.address for vals in psutil.net_if_addrs().values()
                        for a in vals if a.family == 2 and not a.address.startswith("127.")), "—")
                self.set_text("ssid", self.ssid[:44])
                self.set_text("ip", "IP: " + self.ip)
                net = psutil.net_io_counters()
                dt = max(.1, now-self.last_time)
                down = max(0, net.bytes_recv-self.last_net.bytes_recv)/dt/1024
                up = max(0, net.bytes_sent-self.last_net.bytes_sent)/dt/1024
                self.set_text("net_down", "↓ " + self.speed(down))
                self.set_text("net_up", "↑ " + self.speed(up))
                self.last_net, self.last_time = net, now
        except Exception:
            pass
        self.root.after(1500, self.update_data)

    @staticmethod
    def speed(kb):
        return f"{kb/1024:.2f} МБ/с" if kb >= 1024 else f"{kb:.1f} КБ/с"

if __name__ == "__main__":
    Widget()
