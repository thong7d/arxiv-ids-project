param()

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$root = (Get-Item (Split-Path -Parent $PSScriptRoot)).FullName
$allowed = @('.py', '.tex', '.bib', '.json', '.md', '.yaml', '.yml', '.toml', '.txt', '.csv', '.ipynb')
$candidates = [System.Collections.Generic.List[string]]::new()

foreach ($d in @('src', 'tests', 'configs', 'scripts', 'book')) {
    $dirPath = Join-Path $root $d
    if (Test-Path $dirPath) {
        Get-ChildItem -Path $dirPath -Recurse -File | ForEach-Object {
            if ($allowed -contains $_.Extension -and $_.FullName -notmatch '__pycache__') {
                $candidates.Add($_.FullName)
            }
        }
    }
}

foreach ($top in @('pyproject.toml', 'requirements.txt', 'README.md', 'PLAN.md')) {
    $topPath = Join-Path $root $top
    if (Test-Path $topPath) {
        $candidates.Add($topPath)
    }
}

$sortedCandidates = $candidates | Sort-Object -Unique
$outDir = Join-Path $root 'artifacts\release'
if (-not (Test-Path $outDir)) {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
}

$tempZip = Join-Path $outDir 'temp_bundle.zip'
if (Test-Path $tempZip) {
    Remove-Item -Force $tempZip
}

$zip = [System.IO.Compression.ZipFile]::Open($tempZip, [System.IO.Compression.ZipArchiveMode]::Create)
try {
    foreach ($file in $sortedCandidates) {
        $relPath = $file.Substring($root.Length).TrimStart('\', '/') -replace '\\', '/'
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $file, $relPath, [System.IO.Compression.CompressionLevel]::Optimal) | Out-Null
    }
} finally {
    $zip.Dispose()
}

$hash = (Get-FileHash -Path $tempZip -Algorithm SHA256).Hash.ToLowerInvariant()
$shortHash = $hash.Substring(0, 12)
$finalZip = Join-Path $outDir ("ids13-code-" + $shortHash + ".zip")
$finalSha = Join-Path $outDir ("ids13-code-" + $shortHash + ".sha256")

if (Test-Path $finalZip) {
    Remove-Item -Force $finalZip
}
Move-Item -Path $tempZip -Destination $finalZip -Force
Set-Content -Path $finalSha -Value ($hash + "`n") -NoNewline -Encoding utf8

Copy-Item -Path $finalZip -Destination (Join-Path $outDir 'ids13-code.zip') -Force
Copy-Item -Path $finalSha -Destination (Join-Path $outDir 'ids13-code.sha256') -Force

Write-Host "Bundle: $finalZip"
Write-Host "SHA256: $hash"
Write-Host "Short: $shortHash"
Write-Host "Files: $($sortedCandidates.Count)"

