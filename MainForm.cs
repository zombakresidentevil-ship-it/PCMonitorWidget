using System.Diagnostics;
using System.Drawing.Drawing2D;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
using LibreHardwareMonitor.Hardware;

namespace PCMonitorWidget;

public sealed class MainForm : Form
{
    private readonly System.Windows.Forms.Timer timer = new() { Interval = 1200 };
    private readonly Computer computer = new()
    {
        IsCpuEnabled = true, IsGpuEnabled = true,
        IsMemoryEnabled = true, IsStorageEnabled = true
    };
    private PerformanceCounter? cpuCounter;
    private float cpuLoad, gpuLoad;
    private float? cpuTemp, gpuTemp;
    private double ramUsed, ramTotal;
    private string gpuName = "Видеокарта";
    private string wifiName = "Поиск сети…";
    private string ipAddress = "";
    private string diskInfo = "Проверка дисков…";
    private double downSpeed, upSpeed;
    private long oldReceived, oldSent;
    private DateTime oldNetworkTime = DateTime.UtcNow;
    private bool firstNetworkSample = true;
    private Rectangle closeRect, minimizeRect;
    private const int DWMWA_SYSTEMBACKDROP_TYPE = 38;
    private const int DWMSBT_TRANSIENTWINDOW = 3;

    [StructLayout(LayoutKind.Sequential)]
    private struct MEMORYSTATUSEX
    {
        public uint dwLength, dwMemoryLoad;
        public ulong ullTotalPhys, ullAvailPhys, ullTotalPageFile, ullAvailPageFile,
            ullTotalVirtual, ullAvailVirtual, ullAvailExtendedVirtual;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GlobalMemoryStatusEx(ref MEMORYSTATUSEX lpBuffer);
    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int attrValue, int attrSize);
    [DllImport("dwmapi.dll")]
    private static extern int DwmExtendFrameIntoClientArea(IntPtr hwnd, ref MARGINS margins);
    [DllImport("user32.dll")]
    private static extern bool ReleaseCapture();
    [DllImport("user32.dll")]
    private static extern IntPtr SendMessage(IntPtr hWnd, int msg, IntPtr wParam, IntPtr lParam);
    [StructLayout(LayoutKind.Sequential)]
    private struct MARGINS { public int left, right, top, bottom; }

    public MainForm()
    {
        Text = "Aero Monitor";
        ClientSize = new Size(326, 438);
        MinimumSize = MaximumSize = Size;
        FormBorderStyle = FormBorderStyle.None;
        StartPosition = FormStartPosition.CenterScreen;
        ShowInTaskbar = true;
        TopMost = true;
        DoubleBuffered = true;
        BackColor = Color.FromArgb(18, 28, 42);
        ForeColor = Color.White;
        Font = new Font("Segoe UI", 9f);
        Opacity = 0.96;
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.UserPaint |
                 ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
        Region = new Region(RoundedRect(new Rectangle(0, 0, Width, Height), 18));

        try { computer.Open(); } catch { }
        try
        {
            cpuCounter = new PerformanceCounter("Processor", "% Processor Time", "_Total");
            cpuCounter.NextValue();
        }
        catch { }

        timer.Tick += (_, _) => { ReadSensors(); Invalidate(); };
        timer.Start();
        ReadSensors();
    }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        try
        {
            int backdrop = DWMSBT_TRANSIENTWINDOW;
            DwmSetWindowAttribute(Handle, DWMWA_SYSTEMBACKDROP_TYPE, ref backdrop, sizeof(int));
            var margins = new MARGINS { left = -1, right = -1, top = -1, bottom = -1 };
            DwmExtendFrameIntoClientArea(Handle, ref margins);
        }
        catch { }
    }

    protected override void OnMouseDown(MouseEventArgs e)
    {
        base.OnMouseDown(e);
        if (e.Button != MouseButtons.Left) return;
        if (closeRect.Contains(e.Location)) { Close(); return; }
        if (minimizeRect.Contains(e.Location)) { WindowState = FormWindowState.Minimized; return; }
        if (e.Y < 48)
        {
            ReleaseCapture();
            SendMessage(Handle, 0xA1, (IntPtr)2, IntPtr.Zero);
        }
    }

    private void ReadSensors()
    {
        try
        {
            cpuTemp = null; gpuTemp = null; gpuLoad = 0;
            foreach (var hw in computer.Hardware)
            {
                UpdateHardware(hw);
                ReadHardware(hw);
            }
            try { cpuLoad = Math.Clamp(cpuCounter?.NextValue() ?? 0, 0, 100); } catch { cpuLoad = 0; }
            ReadMemory();
            ReadDisks();
            ReadNetwork();
        }
        catch { }
    }

    private void ReadHardware(IHardware hw)
    {
        if (hw.HardwareType == HardwareType.Cpu)
            foreach (var s in hw.Sensors)
                if (s.SensorType == SensorType.Temperature && s.Value.HasValue) cpuTemp ??= s.Value.Value;

        if (hw.HardwareType is HardwareType.GpuAmd or HardwareType.GpuNvidia or HardwareType.GpuIntel)
        {
            gpuName = hw.Name;
            foreach (var s in hw.Sensors)
            {
                if (s.SensorType == SensorType.Temperature && s.Value.HasValue) gpuTemp ??= s.Value.Value;
                if (s.SensorType == SensorType.Load && s.Value.HasValue) gpuLoad = Math.Max(gpuLoad, s.Value.Value);
            }
        }
        foreach (var sub in hw.SubHardware) ReadHardware(sub);
    }

    private static void UpdateHardware(IHardware hw) => hw.Update();

    private void ReadMemory()
    {
        var m = new MEMORYSTATUSEX { dwLength = (uint)Marshal.SizeOf<MEMORYSTATUSEX>() };
        if (GlobalMemoryStatusEx(ref m))
        {
            ramTotal = m.ullTotalPhys / 1073741824d;
            ramUsed = (m.ullTotalPhys - m.ullAvailPhys) / 1073741824d;
        }
    }

    private void ReadDisks()
    {
        var drives = DriveInfo.GetDrives().Where(d => d.IsReady && d.DriveType == DriveType.Fixed).Take(2).ToArray();
        diskInfo = drives.Length == 0 ? "Диски не найдены" :
            string.Join("     ", drives.Select(d =>
                $"{d.Name.TrimEnd('\\')}  {100d * (d.TotalSize - d.AvailableFreeSpace) / d.TotalSize:0}%"));
    }

    private void ReadNetwork()
    {
        var active = NetworkInterface.GetAllNetworkInterfaces()
            .Where(n => n.OperationalStatus == OperationalStatus.Up &&
                        n.NetworkInterfaceType != NetworkInterfaceType.Loopback &&
                        n.NetworkInterfaceType != NetworkInterfaceType.Tunnel).ToArray();

        string netsh = RunNetsh();
        var match = Regex.Match(netsh, @"(?im)^\s*SSID\s*:\s*(.+?)\s*$");
        wifiName = match.Success ? match.Groups[1].Value.Trim() :
            active.FirstOrDefault()?.Name ?? "Нет подключения";
        var ip = active.SelectMany(n => n.GetIPProperties().UnicastAddresses)
            .FirstOrDefault(a => a.Address.AddressFamily == AddressFamily.InterNetwork);
        ipAddress = ip?.Address.ToString() ?? "IP не получен";

        long received = 0, sent = 0;
        foreach (var nic in active)
        {
            try { var s = nic.GetIPv4Statistics(); received += s.BytesReceived; sent += s.BytesSent; }
            catch { }
        }
        var now = DateTime.UtcNow;
        if (!firstNetworkSample)
        {
            double sec = Math.Max(.2, (now - oldNetworkTime).TotalSeconds);
            downSpeed = Math.Max(0, received - oldReceived) / sec / 1024d;
            upSpeed = Math.Max(0, sent - oldSent) / sec / 1024d;
        }
        firstNetworkSample = false;
        oldReceived = received; oldSent = sent; oldNetworkTime = now;
    }

    private static string RunNetsh()
    {
        try
        {
            using var p = Process.Start(new ProcessStartInfo("netsh", "wlan show interfaces")
            { UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true });
            if (p == null) return "";
            string result = p.StandardOutput.ReadToEnd();
            p.WaitForExit(900);
            return result;
        }
        catch { return ""; }
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        var g = e.Graphics;
        g.SmoothingMode = SmoothingMode.AntiAlias;
        g.TextRenderingHint = System.Drawing.Text.TextRenderingHint.ClearTypeGridFit;

        using (var bg = new LinearGradientBrush(ClientRectangle,
            Color.FromArgb(238, 26, 43, 63), Color.FromArgb(242, 10, 20, 34), 90f))
            g.FillPath(bg, RoundedRect(new Rectangle(0, 0, Width - 1, Height - 1), 18));

        using (var shine = new LinearGradientBrush(new Rectangle(0, 0, Width, 100),
            Color.FromArgb(55, 180, 220, 255), Color.FromArgb(0, 100, 160, 220), 90f))
            g.FillPath(shine, RoundedRect(new Rectangle(1, 1, Width - 2, 100), 17));

        using (var border = new Pen(Color.FromArgb(115, 205, 232, 255), 1f))
            g.DrawPath(border, RoundedRect(new Rectangle(0, 0, Width - 1, Height - 1), 18));

        DrawText(g, "AERO MONITOR", 18, 13, 10, Color.FromArgb(190, 225, 245), true);
        DrawText(g, "СИСТЕМА В РЕАЛЬНОМ ВРЕМЕНИ", 18, 29, 7, Color.FromArgb(135, 185, 210), false);
        closeRect = new Rectangle(294, 12, 18, 18);
        minimizeRect = new Rectangle(270, 12, 18, 18);
        DrawWindowButton(g, minimizeRect, "–");
        DrawWindowButton(g, closeRect, "×");

        DrawMetric(g, 16, 62, 140, 92, "ПРОЦЕССОР", $"{cpuLoad:0}%", cpuTemp, cpuLoad, Color.FromArgb(91, 190, 255));
        DrawMetric(g, 170, 62, 140, 92, "ВИДЕОКАРТА", $"{gpuLoad:0}%", gpuTemp, gpuLoad, Color.FromArgb(120, 220, 180));

        DrawSection(g, 16, 168, 294, 76, "ОПЕРАТИВНАЯ ПАМЯТЬ");
        DrawText(g, $"{ramUsed:0.0} ГБ", 29, 190, 21, Color.White, true);
        DrawText(g, $"из {ramTotal:0.0} ГБ", 113, 198, 10, Color.FromArgb(170, 198, 216), false);
        DrawBar(g, new Rectangle(29, 225, 267, 6), ramTotal > 0 ? ramUsed / ramTotal * 100 : 0, Color.FromArgb(105, 190, 255));

        DrawSection(g, 16, 254, 294, 48, "НАКОПИТЕЛИ");
        DrawText(g, diskInfo, 29, 278, 9, Color.FromArgb(224, 237, 247), false);

        DrawSection(g, 16, 312, 294, 106, "СЕТЬ  •  WI-FI / ETHERNET");
        DrawText(g, ClipText(g, wifiName, 9, 255), 29, 335, 11, Color.White, true);
        DrawText(g, ipAddress, 29, 354, 8, Color.FromArgb(150, 190, 215), false);
        DrawText(g, $"↓ {FormatSpeed(downSpeed)}", 29, 378, 10, Color.FromArgb(115, 210, 255), true);
        DrawText(g, $"↑ {FormatSpeed(upSpeed)}", 166, 378, 10, Color.FromArgb(130, 230, 190), true);
    }

    private void DrawMetric(Graphics g, int x, int y, int w, int h, string title,
        string load, float? temp, float percent, Color accent)
    {
        DrawSection(g, x, y, w, h, title);
        DrawText(g, load, x + 12, y + 26, 25, Color.White, true);
        DrawText(g, "ЗАГРУЗКА", x + 13, y + 57, 7, Color.FromArgb(155, 190, 210), false);
        DrawText(g, temp.HasValue ? $"{temp.Value:0}°C" : "— °C", x + 76, y + 29, 15, accent, true);
        DrawText(g, "ТЕМП.", x + 79, y + 57, 7, Color.FromArgb(155, 190, 210), false);
        DrawBar(g, new Rectangle(x + 12, y + 76, w - 24, 4), percent, accent);
    }

    private void DrawSection(Graphics g, int x, int y, int w, int h, string title)
    {
        var r = new Rectangle(x, y, w, h);
        using var path = RoundedRect(r, 10);
        using var fill = new LinearGradientBrush(r, Color.FromArgb(85, 210, 235, 255),
            Color.FromArgb(36, 105, 145, 180), 90f);
        g.FillPath(fill, path);
        using var pen = new Pen(Color.FromArgb(55, 210, 235, 255));
        g.DrawPath(pen, path);
        DrawText(g, title, x + 12, y + 8, 7, Color.FromArgb(155, 200, 225), true);
    }

    private static void DrawBar(Graphics g, Rectangle r, double value, Color color)
    {
        using var bg = new SolidBrush(Color.FromArgb(55, 220, 240, 255));
        using var p = RoundedRect(r, 3);
        g.FillPath(bg, p);
        int width = (int)(r.Width * Math.Clamp(value, 0, 100) / 100d);
        if (width > 2)
        {
            using var fg = new SolidBrush(color);
            g.FillPath(fg, RoundedRect(new Rectangle(r.X, r.Y, width, r.Height), 3));
        }
    }

    private static void DrawText(Graphics g, string value, int x, int y, float size, Color color, bool bold)
    {
        using var font = new Font("Segoe UI", size, bold ? FontStyle.Bold : FontStyle.Regular, GraphicsUnit.Point);
        using var brush = new SolidBrush(color);
        g.DrawString(value, font, brush, x, y);
    }

    private static void DrawWindowButton(Graphics g, Rectangle r, string symbol)
    {
        using var b = new SolidBrush(Color.FromArgb(48, 220, 240, 255));
        g.FillEllipse(b, r);
        using var f = new Font("Segoe UI", 10, FontStyle.Regular);
        using var t = new SolidBrush(Color.FromArgb(225, 245, 255));
        var s = g.MeasureString(symbol, f);
        g.DrawString(symbol, f, t, r.X + (r.Width - s.Width) / 2, r.Y + (r.Height - s.Height) / 2 - 1);
    }

    private static string ClipText(Graphics g, string value, float size, int width)
    {
        using var f = new Font("Segoe UI", size, FontStyle.Bold);
        while (value.Length > 4 && g.MeasureString(value, f).Width > width) value = value[..^2] + "…";
        return value;
    }

    private static string FormatSpeed(double kb)
        => kb >= 1024 ? $"{kb / 1024:0.00} МБ/с" : $"{kb:0.0} КБ/с";

    private static GraphicsPath RoundedRect(Rectangle r, int radius)
    {
        int d = radius * 2;
        var p = new GraphicsPath();
        p.AddArc(r.X, r.Y, d, d, 180, 90);
        p.AddArc(r.Right - d, r.Y, d, d, 270, 90);
        p.AddArc(r.Right - d, r.Bottom - d, d, d, 0, 90);
        p.AddArc(r.X, r.Bottom - d, d, d, 90, 90);
        p.CloseFigure();
        return p;
    }

    protected override void OnFormClosed(FormClosedEventArgs e)
    {
        timer.Stop();
        try { computer.Close(); } catch { }
        cpuCounter?.Dispose();
        base.OnFormClosed(e);
    }
}