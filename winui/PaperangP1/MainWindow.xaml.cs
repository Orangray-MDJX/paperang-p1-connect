using System.Globalization;
using System.Text.Json.Nodes;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media.Imaging;
using QRCoder;
using Windows.Graphics;
using Windows.Storage.Streams;

namespace PaperangP1;

public sealed partial class MainWindow : Window
{
    private readonly ServiceApi _api = new();
    private readonly DispatcherQueueTimer _refreshTimer;
    private bool _refreshing;
    private string _jobsJson = "";
    private string _qrUrl = "";
    private byte[]? _selectedImage;
    private string? _previewToken;
    private int? _longJobId;
    private readonly EventWaitHandle _showLanEvent = new(false, EventResetMode.AutoReset, @"Local\PaperangP1ShowLan");
    private volatile bool _closing;

    public MainWindow()
    {
        InitializeComponent();
        Title = "喵喵机 P1";
        ExtendsContentIntoTitleBar = true;
        SetTitleBar(AppTitleBar);
        AppWindow.Resize(new SizeInt32(1120, 820));
        AppNav.SelectedItem = AppNav.MenuItems[Environment.GetCommandLineArgs().Contains("--lan") ? 3 : 0];
        _refreshTimer = DispatcherQueue.CreateTimer();
        _refreshTimer.Interval = TimeSpan.FromSeconds(3);
        _refreshTimer.Tick += async (_, _) => await RefreshAsync();
        _ = Task.Run(() =>
        {
            while (!_closing)
            {
                _showLanEvent.WaitOne();
                if (!_closing) DispatcherQueue.TryEnqueue(() => AppNav.SelectedItem = AppNav.MenuItems[3]);
            }
        });
        ((FrameworkElement)Content).Loaded += async (_, _) =>
        {
            await LoadSettingsAsync();
            await RefreshAsync();
            _refreshTimer.Start();
        };
        Closed += (_, _) => { _closing = true; _showLanEvent.Set(); _refreshTimer.Stop(); _api.Dispose(); };
    }

    private static string Value(JsonNode? node, string fallback = "") => node?.ToString() ?? fallback;
    private static bool Bool(JsonNode? node) => bool.TryParse(Value(node), out var value) && value;
    private static int Int(JsonNode? node, int fallback = 0) =>
        int.TryParse(Value(node), NumberStyles.Integer, CultureInfo.InvariantCulture, out var value) ? value : fallback;
    private static double Double(JsonNode? node, double fallback = 0) =>
        double.TryParse(Value(node), NumberStyles.Float, CultureInfo.InvariantCulture, out var value) ? value : fallback;

    private static void ShowInfo(InfoBar bar, string message, InfoBarSeverity severity = InfoBarSeverity.Informational)
    {
        bar.Message = message;
        bar.Severity = severity;
        bar.IsOpen = true;
    }

    private void AppNav_SelectionChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        var section = (args.SelectedItem as NavigationViewItem)?.Tag?.ToString();
        OverviewView.Visibility = section == "overview" ? Visibility.Visible : Visibility.Collapsed;
        JobsView.Visibility = section == "jobs" ? Visibility.Visible : Visibility.Collapsed;
        LongView.Visibility = section == "long" ? Visibility.Visible : Visibility.Collapsed;
        SettingsView.Visibility = section == "settings" ? Visibility.Visible : Visibility.Collapsed;
    }

    private void OpenLong_Click(object sender, RoutedEventArgs e) => AppNav.SelectedItem = AppNav.MenuItems[2];

    private async Task RefreshAsync()
    {
        if (_refreshing) return;
        _refreshing = true;
        try
        {
            var status = await _api.GetAsync("api/status");
            ServiceInfo.IsOpen = false;
            UpdateDevice(status);
            await UpdateLanAsync(status["lan"]);
            UpdateJobs(await _api.GetAsync("api/jobs"));
            if (_longJobId.HasValue) await RefreshLongJobAsync();
        }
        catch (Exception error)
        {
            DeviceStatus.Text = "打印服务未连接";
            ShowInfo(ServiceInfo, $"无法连接本机打印服务：{error.Message}", InfoBarSeverity.Warning);
        }
        finally { _refreshing = false; }
    }

    private void UpdateDevice(JsonNode status)
    {
        var connected = Bool(status["connected"]);
        var printing = Bool(status["queue"]?["printing"]);
        DeviceStatus.Text = !connected ? "等待打印机" :
            Value(status["lid_closed"]) == "false" ? "请合好纸仓盖" :
            Value(status["paper_present"]) == "false" ? "打印机缺纸" :
            printing ? "正在打印" : "设备已就绪";
        var transport = Value(status["transport"], "未连接");
        ConnectionText.Text = connected ? $"{transport.ToUpperInvariant()} · {Value(status["protocol"], "设备已连接")}" :
            Value(status["last_error"], "检查设备电源、USB 或蓝牙连接。");
        // 服务返回的电量是 0.1% 步进的浮点（如 54.3），整数解析会失败成"未知"。
        var battery = Double(status["battery"], -1);
        BatteryText.Text = battery < 0 ? "未知" : $"{battery:0}%";
        if (battery >= 0 && battery < 20) BatteryText.Text += "（低）";
        BatteryBar.Value = Math.Clamp(battery, 0, 100);
        PendingText.Text = Value(status["queue"]?["pending"], "0");
    }

    private async Task UpdateLanAsync(JsonNode? lan)
    {
        if (!Bool(lan?["enabled"]))
        {
            LanStatus.Text = Bool(lan?["restart_required"]) ? "局域网设置待服务重启后生效。" : "局域网打印未开启。可在高级设置中配置。";
            LanQrImage.Visibility = Visibility.Collapsed;
            LanUrl.Text = "";
            return;
        }
        var url = Value(lan?["long_image_url"]);
        if (string.IsNullOrEmpty(url))
        {
            var address = Value(lan?["address"]);
            url = string.IsNullOrEmpty(address) ? "" : $"http://{address}:{_api.IppPort}/long-image";
        }
        var restartRequired = Bool(lan?["restart_required"]);
        LanStatus.Text = restartRequired ? "网络设置待服务重启后生效。" : "同一 Wi-Fi 下用手机扫码上传长图。";
        LanUrl.Text = url;
        if (restartRequired || string.IsNullOrEmpty(url))
        {
            LanQrImage.Visibility = Visibility.Collapsed;
            return;
        }
        if (_qrUrl == url) return;
        try
        {
            using var generator = new QRCodeGenerator();
            using var data = generator.CreateQrCode(url, QRCodeGenerator.ECCLevel.Q);
            using var qr = new PngByteQRCode(data);
            LanQrImage.Source = await BitmapFromBytesAsync(qr.GetGraphic(6));
            LanQrImage.Visibility = Visibility.Visible;
            _qrUrl = url;
        }
        catch (Exception error)
        {
            LanQrImage.Visibility = Visibility.Collapsed;
            LanStatus.Text = $"二维码不可用：{error.Message}";
        }
    }

    private static async Task<BitmapImage> BitmapFromBytesAsync(byte[] bytes)
    {
        using var stream = new InMemoryRandomAccessStream();
        using (var writer = new DataWriter(stream))
        {
            writer.WriteBytes(bytes);
            await writer.StoreAsync();
            writer.DetachStream();
        }
        stream.Seek(0);
        var bitmap = new BitmapImage();
        await bitmap.SetSourceAsync(stream);
        return bitmap;
    }
}
