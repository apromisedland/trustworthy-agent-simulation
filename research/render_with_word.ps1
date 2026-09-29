param(
    [Parameter(Mandatory = $true)][string]$InputPath,
    [Parameter(Mandatory = $true)][string]$OutputPath
)

$ErrorActionPreference = 'Stop'
$wordApplication = $null
$wordDocument = $null
try {
    $wordApplication = New-Object -ComObject Word.Application
    $wordApplication.Visible = $false
    $wordApplication.DisplayAlerts = 0
    $wordApplication.AutomationSecurity = 3
    $wordApplication.Options.UpdateLinksAtOpen = $false
    $wordDocument = $wordApplication.Documents.Open($InputPath, $false, $true)
    $wordDocument.Repaginate()
    $wordDocument.ExportAsFixedFormat($OutputPath, 17)
    Write-Output "Rendered pages: $($wordDocument.ComputeStatistics(2))"
} finally {
    if ($null -ne $wordDocument) {
        $wordDocument.Close(0)
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($wordDocument) | Out-Null
    }
    if ($null -ne $wordApplication) {
        $wordApplication.Quit(0)
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($wordApplication) | Out-Null
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
