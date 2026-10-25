$ErrorActionPreference = 'Stop'
$archiveRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$entries = Get-Content -LiteralPath (Join-Path $archiveRoot 'SHA256SUMS.json') -Raw | ConvertFrom-Json
$count = 0
foreach ($entry in $entries) {
    $file = [System.IO.Path]::GetFullPath((Join-Path $archiveRoot $entry.path))
    if (-not $file.StartsWith($archiveRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Path outside the recovery archive: $($entry.path)"
    }
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
        throw "Missing recovery file: $($entry.path)"
    }
    $actual = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash
    if ($actual -ne $entry.sha256) {
        throw "SHA-256 mismatch: $($entry.path)"
    }
    $count++
}
Write-Output "Verified $count recovery files. All SHA-256 hashes match."
