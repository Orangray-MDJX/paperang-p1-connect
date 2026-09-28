using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace PaperangP1;

public sealed partial class MainWindow
{
    private JsonNode? _loadedConfig;

    private async Task LoadSettingsAsync()
    {
        try
        {
            var config = await _api.GetAsync("api/config");
            _loadedConfig = config.DeepClone();
            KeepaliveToggle.IsOn = Bool(config["keepalive"]);
            PowerOffToggle.IsOn = Bool(config["disable_auto_poweroff"]);
            LongMediaToggle.IsOn = Bool(config["ipp_long_media"]);
            LanToggle.IsOn = Bool(config["lan_enabled"]);
            DensityNumber.Value = Int(config["density"], 80);
            LanAddressBox.Text = Value(config["lan_address"]);
            LanNetworkBox.Text = Value(config["lan_network"]);
            LanNameBox.Text = Value(config["lan_name"], "Paperang P1");
            var transport = Value(config["transport_pref"], "usb");
            foreach (ComboBoxItem item in TransportCombo.Items)
                if (item.Tag?.ToString() == transport) TransportCombo.SelectedItem = item;
            SettingsInfo.IsOpen = false;
        }
        catch (Exception error) { ShowInfo(SettingsInfo, $"读取设置失败：{error.Message}", InfoBarSeverity.Warning); }
    }

    private async void SaveSettings_Click(object sender, RoutedEventArgs e)
    {
        if (double.IsNaN(DensityNumber.Value))
        {
            ShowInfo(SettingsInfo, "请输入打印浓度。", InfoBarSeverity.Warning);
            return;
        }
        SaveSettingsButton.IsEnabled = false;
        try
        {
            var config = new Dictionary<string, object>
            {
                ["keepalive"] = KeepaliveToggle.IsOn,
                ["disable_auto_poweroff"] = PowerOffToggle.IsOn,
                ["ipp_long_media"] = LongMediaToggle.IsOn,
                ["transport_pref"] = (TransportCombo.SelectedItem as ComboBoxItem)?.Tag?.ToString() ?? "usb",
                ["density"] = (int)Math.Round(DensityNumber.Value),
                ["lan_enabled"] = LanToggle.IsOn,
                ["lan_address"] = LanAddressBox.Text.Trim(),
                ["lan_network"] = LanNetworkBox.Text.Trim(),
                ["lan_name"] = LanNameBox.Text.Trim()
            };
            var changes = config.Where(entry =>
                JsonSerializer.SerializeToNode(entry.Value)?.ToJsonString() !=
                _loadedConfig?[entry.Key]?.ToJsonString()).ToDictionary(entry => entry.Key, entry => entry.Value);
            if (changes.Count == 0)
            {
                ShowInfo(SettingsInfo, "设置未变更。");
                return;
            }
            var result = await _api.PutAsync("api/config", changes);
            await LoadSettingsAsync();
            ShowInfo(SettingsInfo, Bool(result["restart_required"]) ?
                "设置已保存。请重启后台打印服务，使局域网设置生效。" : "设置已保存。", InfoBarSeverity.Success);
            await RefreshAsync();
        }
        catch (Exception error) { ShowInfo(SettingsInfo, error.Message, InfoBarSeverity.Error); }
        finally { SaveSettingsButton.IsEnabled = true; }
    }
}
