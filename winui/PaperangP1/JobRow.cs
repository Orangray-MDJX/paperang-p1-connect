using Microsoft.UI.Xaml;

namespace PaperangP1;

public sealed class JobRow
{
    public int Id { get; init; }
    public string DisplayTitle { get; init; } = "";
    public string Detail { get; init; } = "";
    public string StateLabel { get; init; } = "";
    public string Progress { get; init; } = "";
    public Visibility ResumeVisibility { get; init; } = Visibility.Collapsed;
    public Visibility CancelVisibility { get; init; } = Visibility.Collapsed;
}
