using System.Text.Json.Nodes;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace PaperangP1;

public sealed partial class MainWindow
{
    private void UpdateJobs(JsonNode? result)
    {
        var json = result?.ToJsonString() ?? "";
        if (json == _jobsJson) return;
        _jobsJson = json;
        var rows = new List<JobRow>();
        if (result is JsonArray jobs)
        {
            foreach (var job in jobs)
            {
                if (job is null) continue;
                var state = Value(job["state"]);
                var label = state switch
                {
                    "pending" => "等待打印", "receiving" => "正在接收", "printing" => "正在打印", "completed" => "设备已接收",
                    "held" => "已暂停", "failed" => "失败", "cancelled" => "已取消",
                    "unknown" => "结果未知", _ => state
                };
                rows.Add(new JobRow
                {
                    Id = Int(job["id"]),
                    DisplayTitle = $"#{Value(job["id"])} {Value(job["title"])}",
                    Detail = Value(job["error"], Value(job["source"])),
                    StateLabel = label,
                    Progress = $"{Value(job["pages_done"], "0")} / {Value(job["page_count"], "0")} 页",
                    ResumeVisibility = state == "held" ? Visibility.Visible : Visibility.Collapsed,
                    CancelVisibility = state is "pending" or "receiving" or "printing" or "held" ? Visibility.Visible : Visibility.Collapsed
                });
            }
        }
        JobsList.ItemsSource = rows;
    }

    private async void Connect_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            ShowInfo(ServiceInfo, "正在连接打印机…");
            await _api.PostAsync("api/connect");
            await RefreshAsync();
        }
        catch (Exception error) { ShowInfo(ServiceInfo, error.Message, InfoBarSeverity.Error); }
    }

    private async void PrintText_Click(object sender, RoutedEventArgs e)
    {
        if (string.IsNullOrWhiteSpace(PrintText.Text))
        {
            ShowInfo(ServiceInfo, "请输入要打印的文字。", InfoBarSeverity.Warning);
            return;
        }
        PrintButton.IsEnabled = false;
        try
        {
            var result = await _api.PostAsync("api/print/text", new { text = PrintText.Text });
            ShowInfo(ServiceInfo, $"任务 #{Value(result["job_id"])} 已加入队列。", InfoBarSeverity.Success);
            PrintText.Text = "";
            await RefreshAsync();
        }
        catch (Exception error) { ShowInfo(ServiceInfo, error.Message, InfoBarSeverity.Error); }
        finally { PrintButton.IsEnabled = true; }
    }

    private async void ResumeJob_Click(object sender, RoutedEventArgs e) => await ChangeJobAsync(sender, "resume");
    private async void CancelJob_Click(object sender, RoutedEventArgs e) => await ChangeJobAsync(sender, "cancel");

    private async Task ChangeJobAsync(object sender, string action)
    {
        if (sender is not Button button || !int.TryParse(button.Tag?.ToString(), out var id)) return;
        button.IsEnabled = false;
        try
        {
            await _api.PostAsync($"api/jobs/{id}/{action}");
            JobsInfo.IsOpen = false;
            await RefreshAsync();
        }
        catch (Exception error) { ShowInfo(JobsInfo, error.Message, InfoBarSeverity.Error); }
        finally { button.IsEnabled = true; }
    }
}
