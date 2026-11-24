using System.Diagnostics;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using LibreHardwareMonitor.Hardware;

namespace PCMonitorWidget;

public sealed class MainForm : Form
{
    private readonly Label cpuLabel = MakeValue();
    private readonly Label gpuLabel = MakeValue();
    private readonly Label ramLabel = MakeValue();
    private readonly Label diskLabel = MakeValue();
    private readonly Label wifiLabel = MakeValue();
    private readonly Label netLabel = MakeValue();
    private readonly System.Windows.Forms.Timer timer = new() { Interval = 1500 };
    private readonly Computer computer = new()
    {
        IsCpuEnabled = true,
        IsGpuEnabled = true,
        IsMemoryEnabled = true,
        IsStorageEnabled = true
    };
    private readonly PerformanceCounter? cpuCounter;
    private long previousReceived;
    private long previousSent;
    private DateTime previousNetworkTime = DateTime.UtcNow;

    public MainForm()
    {
        Text = "PC Monitor Widget";
        Width = 390;
        Height = 540;
        MinimumSize = new Size(340, 430);
        BackColor = Color.FromArgb(19, 22, 29);
        ForeColor = Color.White;
        Font = new Font("Segoe UI", 10);
        FormBorderStyle = FormBorderStyle.SizableToolWindow;
        TopMost = false;
        StartPosition = FormStartPosition.CenterScreen;

        var header = new Label
        {
            Text = "PC MONITOR",
            Dock = DockStyle.Top,
            Height = 48,
            TextAlign = ContentAlignment.MiddleCenter,
            Font = new Font("Segoe UI Semibold", 15),
            ForeColor = Color.FromArgb(90, 190, 255)
        };
        Controls.Add(header);

        var grid = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            Padding = new Padding(12),
            ColumnCount = 2,
            RowCount = 3,
            BackColor = BackColor
        };
        grid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
        grid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
        for (int i = 0; i < 3; i++) grid.RowStyles.Add(new RowStyle(SizeType.Percent, 33.33f));
        AddTile(grid, "ПРОЦЕССОР", cpuLabel, 0, 0);
        AddTile(grid, "ВИДЕОКАРТА", gpuLabel, 1, 0);
        AddTile(grid, "ОПЕРАТИВНАЯ ПАМЯТЬ", ramLabel, 0, 1);
        AddTile(grid, "ДИСКИ", diskLabel, 1, 1);
        AddTile(grid, "WI-FI / ETHERNET", wifiLabel, 0, 2);
        AddTile(grid, "СЕТЕВОЙ ТРАФИК", netLabel, 1, 2);
        Controls.Add(grid);
        Controls.SetChildIndex(header, 0);

        try { computer.Open(); } catch { }
        try { cpuCounter = new PerformanceCounter("Processor", "% Processor Time", "_Total"); cpuCounter.NextValue(); } catch { }
        timer.Tick += (_, _) => RefreshStats();
        timer.Start();
        RefreshStats();
    }

    private static Label MakeValue() => new()
    {
        Dock = DockStyle.Fill,
        ForeColor = Color.White,
        Font = new Font("Segoe UI Semibold", 12),
        TextAlign = ContentAlignment.MiddleCenter,
        AutoEllipsis = true
    };

    private static void AddTile(TableLayoutPanel grid, string title, Label value, int col, int row)
    {
        var panel = new Panel
        {
            Dock = DockStyle.Fill,
            BackColor = Color.FromArgb(31, 37, 48),
            Margin = new Padding(6),
            Padding = new Padding(7)
        };
        var caption = new Label
        {
            Text = title,
            Dock = DockStyle.Top,
            Height = 28,
            ForeColor = Color.FromArgb(150, 165, 185),
            Font = new Font("Segoe UI Semibold", 8),
            TextAlign = ContentAlignment.MiddleCenter
        };
        panel.Controls.Add(value);
        panel.Controls.Add(caption);
        grid.Controls.Add(panel, col, row);
    }

    private void RefreshStats()
    {
        try
        {
            float? cpuTemp = null, gpuTemp = null, gpuLoad = null;
            foreach (var hw in computer.Hardware)
            {
                UpdateHardware(hw);
                foreach (var sensor in hw.Sensors)
                {
                    if (hw.HardwareType == HardwareType.Cpu && sensor.SensorType == SensorType.Temperature && sensor.Value.HasValue)
                        cpuTemp ??= sensor.Value.Value;
                    if ((hw.HardwareType == HardwareType.GpuAmd || hw.HardwareType == HardwareType.GpuNvidia || hw.HardwareType == HardwareType.GpuIntel) && sensor.Value.HasValue)
                    {
                        if (sensor.SensorType == SensorType.Temperature) gpuTemp ??= sensor.Value.Value;
                        if (sensor.SensorType == SensorType.Load) gpuLoad ??= sensor.Value.Value;
                    }
                }
            }

            float cpuLoad = 0;
            try { cpuLoad = cpuCounter?.NextValue() ?? 0; } catch { }
            cpuLabel.Text = $"Загрузка: {cpuLoad:0}%\nТемпература: {(cpuTemp.HasValue ? $"{cpuTemp:0} °C" : "нет датчика")}";
            gpuLabel.Text = $"Загрузка: {(gpuLoad.HasValue ? $"{gpuLoad:0}%" : "—")}\nТемпература: {(gpuTemp.HasValue ? $"{gpuTemp:0} °C" : "нет датчика")}";

            var mem = GC.GetGCMemoryInfo();
            var totalRam = GetTotalPhysicalMemory();
            var usedRam = totalRam > 0 ? totalRam - GetAvailablePhysicalMemory() : 0;
            ramLabel.Text = totalRam > 0 ? $"{usedRam / 1073741824d:0.0} / {totalRam / 1073741824d:0.0} ГБ" : "Недоступно";

            var drives = DriveInfo.GetDrives().Where(d => d.IsReady && d.DriveType == DriveType.Fixed)
                .Take(3).Select(d => $"{d.Name.TrimEnd('\\')}  {100d * (d.TotalSize - d.AvailableFreeSpace) / d.TotalSize:0}%");
            diskLabel.Text = string.Join("\n", drives);
            if (string.IsNullOrWhiteSpace(diskLabel.Text)) diskLabel.Text = "Нет данных";

            wifiLabel.Text = GetNetworkStatus();
            netLabel.Text = GetNetworkSpeed();
        }
        catch (Exception ex)
        {
            Text = "PC Monitor Widget — " + ex.Message;
        }
    }

    private static void UpdateHardware(IHardware hardware)
    {
        hardware.Update();
        foreach (var sub in hardware.SubHardware) UpdateHardware(sub);
    }

    private static string GetNetworkStatus()
    {
        var active = NetworkInterface.GetAllNetworkInterfaces()
            .Where(n => n.OperationalStatus == OperationalStatus.Up &&
                n.NetworkInterfaceType != NetworkInterfaceType.Loopback &&
                n.NetworkInterfaceType != NetworkInterfaceType.Tunnel).ToArray();
        string ssid = RunCommand("netsh", "wlan show interfaces");
        var nameLine = ssid.Split('\n').FirstOrDefault(x => x.TrimStart().StartsWith("SSID", StringComparison.OrdinalIgnoreCase) && !x.TrimStart().StartsWith("BSSID", StringComparison.OrdinalIgnoreCase));
        string wifiName = nameLine?.Split(':').Skip(1).FirstOrDefault()?.Trim() ?? "";
        string ip = active.SelectMany(n => n.GetIPProperties().UnicastAddresses)
            .FirstOrDefault(a => a.Address.AddressFamily == AddressFamily.InterNetwork)?.Address.ToString() ?? "IP нет";
        return $"{(wifiName.Length > 0 ? wifiName : active.Length > 0 ? active[0].Name : "Нет подключения")}\n{ip}";
    }

    private string GetNetworkSpeed()
    {
        long received = 0, sent = 0;
        foreach (var nic in NetworkInterface.GetAllNetworkInterfaces().Where(n => n.OperationalStatus == OperationalStatus.Up))
        {
            try { var s = nic.GetIPv4Statistics(); received += s.BytesReceived; sent += s.BytesSent; } catch { }
        }
        var now = DateTime.UtcNow;
        double seconds = Math.Max(0.2, (now - previousNetworkTime).TotalSeconds);
        double down = Math.Max(0, received - previousReceived) / seconds / 1024;
        double up = Math.Max(0, sent - previousSent) / seconds / 1024;
        previousReceived = received; previousSent = sent; previousNetworkTime = now;
        return $"↓ {down:0.0} КБ/с\n↑ {up:0.0} КБ/с";
    }

    private static string RunCommand(string file, string args)
    {
        try
        {
            using var p = Process.Start(new ProcessStartInfo(file, args) { UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true });
            if (p == null) return "";
            string output = p.StandardOutput.ReadToEnd();
            p.WaitForExit(1500);
            return output;
        }
        catch { return ""; }
    }

    private static ulong GetTotalPhysicalMemory()
    {
        try { return new Microsoft.VisualBasic.Devices.ComputerInfo().TotalPhysicalMemory; } catch { return 0; }
    }

    private static ulong GetAvailablePhysicalMemory()
    {
        try { return new Microsoft.VisualBasic.Devices.ComputerInfo().AvailablePhysicalMemory; } catch { return 0; }
    }

    protected override void OnFormClosed(FormClosedEventArgs e)
    {
        timer.Stop();
        computer.Close();
        cpuCounter?.Dispose();
        base.OnFormClosed(e);
    }
}