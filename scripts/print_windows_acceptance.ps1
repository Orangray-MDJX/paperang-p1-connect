param([string]$PrinterName = 'Paperang P1 (服务)')
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$document = [System.Drawing.Printing.PrintDocument]::new()
$document.PrinterSettings.PrinterName = $PrinterName
$document.DocumentName = 'P1 Windows native acceptance'
$document.DefaultPageSettings.PaperSize = [System.Drawing.Printing.PaperSize]::new('P1 57x100mm',225,394)
$document.DefaultPageSettings.Margins = [System.Drawing.Printing.Margins]::new(18,18,0,0)
$document.add_PrintPage({
    param($sender,$page)
    $font = [System.Drawing.Font]::new('Microsoft YaHei',10)
    try {
        $page.Graphics.DrawString('Windows 原生打印验证',$font,[System.Drawing.Brushes]::Black,18,8)
        $page.Graphics.DrawString('1234567890',$font,[System.Drawing.Brushes]::Black,18,30)
        for ($bar=0; $bar -lt 10; $bar++) {
            $page.Graphics.FillRectangle([System.Drawing.Brushes]::Black,(18+$bar*18),54,8,18)
        }
        $page.HasMorePages = $false
    } finally { $font.Dispose() }
})
try { $document.Print() } finally { $document.Dispose() }
