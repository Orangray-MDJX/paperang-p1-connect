using System.Net.Http;
using System.Text.Json.Nodes;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.Windows.Storage.Pickers;

namespace PaperangP1;

public sealed partial class MainWindow
{
    private async void ChooseImage_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileOpenPicker(AppWindow.Id);
        picker.FileTypeFilter.Add(".png");
        picker.FileTypeFilter.Add(".jpg");
        picker.FileTypeFilter.Add(".jpeg");
        try
        {
            var file = await picker.PickSingleFileAsync();
            if (file is null) return;
            var info = new FileInfo(file.Path);
            if (info.Length > 40L * 1024 * 1024) throw new InvalidOperationException("图片超过 40 MB。");
            _selectedImage = await File.ReadAllBytesAsync(file.Path);
            SelectedImageText.Text = info.Name;
            PreviewButton.IsEnabled = true;
            InvalidatePreview();
            LongInfo.IsOpen = false;
        }
        catch (Exception error) { ShowInfo(LongInfo, error.Message, InfoBarSeverity.Error); }
    }

    private void TrimChanged_Click(object sender, RoutedEventArgs e) => InvalidatePreview();

    private void InvalidatePreview()
    {
        _previewToken = null;
        _longJobId = null;
        SubmitLongButton.IsEnabled = false;
        CancelLongButton.IsEnabled = false;
        LongPreviewImage.Visibility = Visibility.Collapsed;
        PreviewSizeText.Text = "";
    }

    private async void Preview_Click(object sender, RoutedEventArgs e)
    {
        if (_selectedImage is null) return;
        PreviewButton.IsEnabled = false;
        InvalidatePreview();
        try
        {
            var trim = TrimCheck.IsChecked == true ? "true" : "false";
            using var request = new HttpRequestMessage(HttpMethod.Post, $"{_api.LongBaseUrl}long-image/preview?trim={trim}")
            {
                Content = new ByteArrayContent(_selectedImage)
            };
            request.Headers.Add("X-P1-Upload", "1");
            using var response = await _api.SendAsync(request);
            var preview = JsonNode.Parse(await response.Content.ReadAsStringAsync())!;
            _previewToken = Value(preview["token"]);
            using var imageRequest = new HttpRequestMessage(HttpMethod.Get, $"{_api.LongBaseUrl}long-image/preview.png");
            imageRequest.Headers.Add("X-P1-Token", _previewToken);
            using var imageResponse = await _api.SendAsync(imageRequest);
            LongPreviewImage.Source = await BitmapFromBytesAsync(await imageResponse.Content.ReadAsByteArrayAsync());
            LongPreviewImage.Visibility = Visibility.Visible;
            PreviewSizeText.Text = $"384 点宽 · 预计纸长 {Value(preview["length_mm"])} mm";
            SubmitLongButton.IsEnabled = true;
            ShowInfo(LongInfo, "预览已生成，请检查图像并确认打印一次。", InfoBarSeverity.Success);
        }
        catch (Exception error) { ShowInfo(LongInfo, error.Message, InfoBarSeverity.Error); }
        finally { PreviewButton.IsEnabled = true; }
    }

    private async Task<JsonNode> LongRequestAsync(string action, bool post = false)
    {
        using var request = new HttpRequestMessage(post ? HttpMethod.Post : HttpMethod.Get, $"{_api.LongBaseUrl}long-image/{action}");
        request.Headers.Add("X-P1-Token", _previewToken);
        if (post) request.Headers.Add("X-P1-Upload", "1");
        using var response = await _api.SendAsync(request);
        return JsonNode.Parse(await response.Content.ReadAsStringAsync())!;
    }

    private async void SubmitLong_Click(object sender, RoutedEventArgs e)
    {
        if (_previewToken is null) return;
        SubmitLongButton.IsEnabled = false;
        try
        {
            var result = await LongRequestAsync("submit", true);
            _longJobId = Int(result["job_id"]);
            CancelLongButton.IsEnabled = true;
            ShowInfo(LongInfo, $"任务 #{_longJobId} 已提交，正在等待设备接收。", InfoBarSeverity.Success);
            await RefreshAsync();
        }
        catch (Exception error)
        {
            SubmitLongButton.IsEnabled = true;
            ShowInfo(LongInfo, error.Message, InfoBarSeverity.Error);
        }
    }

    private async Task RefreshLongJobAsync()
    {
        try
        {
            var job = await LongRequestAsync("job");
            var state = Value(job["state"]);
            var label = state switch
            {
                "completed" => "设备已接收", "unknown" => "结果未知，请核对纸面",
                "printing" => "正在打印", "pending" => "等待打印", "failed" => "打印失败",
                "cancelled" => "已取消", "held" => "已暂停", _ => state
            };
            ShowInfo(LongInfo, $"任务 #{_longJobId}：{label}。{Value(job["error"])}",
                state == "failed" ? InfoBarSeverity.Error : InfoBarSeverity.Informational);
            CancelLongButton.IsEnabled = state is "pending" or "printing" or "held";
            if (state is "completed" or "unknown" or "failed" or "cancelled") _longJobId = null;
        }
        catch (Exception error) { ShowInfo(LongInfo, error.Message, InfoBarSeverity.Warning); }
    }

    private async void CancelLong_Click(object sender, RoutedEventArgs e)
    {
        if (_longJobId is null) return;
        CancelLongButton.IsEnabled = false;
        try
        {
            await LongRequestAsync("cancel", true);
            ShowInfo(LongInfo, $"任务 #{_longJobId} 已请求取消。", InfoBarSeverity.Warning);
            _longJobId = null;
            await RefreshAsync();
        }
        catch (Exception error)
        {
            CancelLongButton.IsEnabled = true;
            ShowInfo(LongInfo, error.Message, InfoBarSeverity.Error);
        }
    }
}
