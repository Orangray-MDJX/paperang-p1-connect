using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace PaperangP1;

internal sealed class ServiceApi : IDisposable
{
    private readonly HttpClient _client;
    public string BaseUrl { get; }
    public string LongBaseUrl { get; }
    public int IppPort { get; }

    public ServiceApi()
    {
        var port = 8765;
        var ippPort = 8631;
        try
        {
            var path = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                                    "PaperangP1", "config.json");
            if (File.Exists(path))
            {
                using var config = JsonDocument.Parse(File.ReadAllText(path));
                if (config.RootElement.TryGetProperty("api_port", out var value) &&
                    value.TryGetInt32(out var configured) && configured is > 0 and <= 65535)
                    port = configured;
                if (config.RootElement.TryGetProperty("ipp_port", out value) &&
                    value.TryGetInt32(out configured) && configured is > 0 and <= 65535)
                    ippPort = configured;
            }
        }
        catch (JsonException) { }
        BaseUrl = $"http://127.0.0.1:{port}/";
        IppPort = ippPort;
        LongBaseUrl = $"http://127.0.0.1:{ippPort}/";
        _client = new HttpClient(new HttpClientHandler { UseProxy = false })
        {
            BaseAddress = new Uri(BaseUrl),
            Timeout = TimeSpan.FromSeconds(30)
        };
    }

    public async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request)
    {
        var response = await _client.SendAsync(request);
        if (response.IsSuccessStatusCode) return response;
        var body = await response.Content.ReadAsStringAsync();
        response.Dispose();
        try
        {
            var error = JsonNode.Parse(body)?["detail"]?.ToString();
            throw new InvalidOperationException(error ?? body);
        }
        catch (JsonException)
        {
            throw new InvalidOperationException(body);
        }
    }

    public async Task<JsonNode> GetAsync(string path)
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, path);
        using var response = await SendAsync(request);
        return JsonNode.Parse(await response.Content.ReadAsStringAsync())!;
    }

    public async Task<JsonNode> PostAsync(string path, object? payload = null)
    {
        using var request = new HttpRequestMessage(HttpMethod.Post, path)
        {
            Content = JsonContent.Create(payload ?? new { })
        };
        using var response = await SendAsync(request);
        return JsonNode.Parse(await response.Content.ReadAsStringAsync())!;
    }

    public async Task<JsonNode> PutAsync(string path, object payload)
    {
        using var request = new HttpRequestMessage(HttpMethod.Put, path)
        {
            Content = JsonContent.Create(payload)
        };
        using var response = await SendAsync(request);
        return JsonNode.Parse(await response.Content.ReadAsStringAsync())!;
    }

    public void Dispose() => _client.Dispose();
}
