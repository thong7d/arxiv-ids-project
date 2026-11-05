$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
$windows = [System.Windows.Automation.AutomationElement]::RootElement.FindAll(
    [System.Windows.Automation.TreeScope]::Children,
    [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ClassNameProperty, 'Chrome_WidgetWin_1'))
$target = $null
foreach ($window in $windows) {
    if ($window.Current.Name -eq 'IDS13_M1_Colab.ipynb - Colab - Google Chrome') {
        $target = $window
        break
    }
}
if ($null -eq $target) { throw 'The verified IDS13 Colab window is not available' }
Add-Type @'
using System;
using System.Runtime.InteropServices;
public class ColabWindowFocus {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr window);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr window, int state);
}
'@
$handle = [IntPtr]$target.Current.NativeWindowHandle
if ($handle -eq [IntPtr]::Zero) { throw 'Colab window has no native handle' }
[void][ColabWindowFocus]::ShowWindowAsync($handle, 9)
[void][ColabWindowFocus]::SetForegroundWindow($handle)
if ([ColabWindowFocus]::GetForegroundWindow() -ne $handle) {
    throw 'Windows did not grant foreground focus; no keyboard input sent'
}
[System.Windows.Forms.SendKeys]::SendWait('^{F9}')
Write-Output 'Sent Run All to the verified IDS13 Colab window.'
