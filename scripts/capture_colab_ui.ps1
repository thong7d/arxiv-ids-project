$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Drawing
$windows = [System.Windows.Automation.AutomationElement]::RootElement.FindAll(
    [System.Windows.Automation.TreeScope]::Children,
    [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ClassNameProperty, 'Chrome_WidgetWin_1'))
foreach ($window in $windows) {
    if ($window.Current.Name -ne 'IDS13_M1_Colab.ipynb - Colab - Google Chrome') { continue }
    $rect = $window.Current.BoundingRectangle
    if ($rect.Width -lt 100 -or $rect.Height -lt 100) { throw 'Colab window is not visible' }
    $image = New-Object System.Drawing.Bitmap([int]$rect.Width, [int]$rect.Height)
    $graphics = [System.Drawing.Graphics]::FromImage($image)
    try {
        $graphics.CopyFromScreen([int]$rect.X, [int]$rect.Y, 0, 0, $image.Size)
        $target = Join-Path (Get-Location) 'artifacts/colab-resume-20261102/window.png'
        $image.Save($target, [System.Drawing.Imaging.ImageFormat]::Png)
        Write-Output 'Captured only the verified Colab window into local artifacts.'
    } finally {
        $graphics.Dispose()
        $image.Dispose()
    }
    break
}
