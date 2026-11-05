Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$chromeWindows = [System.Windows.Automation.AutomationElement]::RootElement.FindAll(
    [System.Windows.Automation.TreeScope]::Children,
    [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ClassNameProperty, 'Chrome_WidgetWin_1'))
foreach ($window in $chromeWindows) {
    if ($window.Current.Name -notlike '*IDS13*') { continue }
    Write-Output ('WINDOW: ' + $window.Current.Name)
    $elements = $window.FindAll([System.Windows.Automation.TreeScope]::Descendants,
        [System.Windows.Automation.Condition]::TrueCondition)
    foreach ($element in $elements) {
        $name = $element.Current.Name
        if ($name -match 'Run cell|Stop cell|runtime|Runtime|Connect|Disconnect|setup|Secrets|secret|Notebook access|Mount|mount|Allow|Allow access') {
            [PSCustomObject]@{Name=$name; Type=$element.Current.ControlType.ProgrammaticName; AutomationId=$element.Current.AutomationId; Bounds=$element.Current.BoundingRectangle.ToString()}
        }
    }
}
