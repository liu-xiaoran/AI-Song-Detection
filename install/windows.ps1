$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try {
    $sourceDir = Split-Path -Parent $PSScriptRoot
    $architecture = $env:PROCESSOR_ARCHITECTURE
    if ($env:PROCESSOR_ARCHITEW6432) { $architecture = $env:PROCESSOR_ARCHITEW6432 }
    if ($architecture -ne 'AMD64') { throw 'This installer currently supports 64-bit x86 Windows.' }
    $installRoot = $env:AI_SONG_DETECTION_INSTALL_DIR
    if (-not $installRoot) { $installRoot = Join-Path $env:LOCALAPPDATA 'AI Song Detection' }
    $version = '0.13.5'
    $target = 'x86_64-pc-windows-msvc'
    $expected = 'a38b8d1902b7cfbc76b423ba1bb456f623f42064cdc72628b6075b89afd1019a'
    $bootstrap = Join-Path $installRoot "bootstrap\uv-$version-$target"
    $uv = Join-Path $bootstrap 'uv.exe'
    $downloads = Join-Path $installRoot 'downloads'
    New-Item -ItemType Directory -Force -Path $downloads, $bootstrap | Out-Null
    if (-not (Test-Path -LiteralPath $uv)) {
        Write-Host 'Preparing the private installer. No system Python or Git is required.'
        $archive = Join-Path $downloads "uv-$version-$target.zip"
        if (-not (Test-Path -LiteralPath $archive) -or (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/astral-sh/uv/releases/download/$version/uv-$target.zip" -OutFile "$archive.part" -TimeoutSec 300
            if ((Get-FileHash -LiteralPath "$archive.part" -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
                Remove-Item -LiteralPath "$archive.part" -Force
                throw 'Installer checksum verification failed. Nothing was executed.'
            }
            Move-Item -LiteralPath "$archive.part" -Destination $archive -Force
        }
        $stage = Join-Path $installRoot ('bootstrap\stage-' + [guid]::NewGuid().ToString('N'))
        try {
            Expand-Archive -LiteralPath $archive -DestinationPath $stage
            $binary = Get-ChildItem -LiteralPath $stage -Recurse -Filter 'uv.exe' | Select-Object -First 1
            if (-not $binary) { throw 'The verified installer archive did not contain uv.exe.' }
            Copy-Item -LiteralPath $binary.FullName -Destination $uv
        } finally {
            if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
        }
    }
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $installRoot 'runtime\python'
    $env:UV_CACHE_DIR = Join-Path $installRoot 'cache\uv'
    $env:UV_PYTHON_PREFERENCE = 'only-managed'
    $env:UV_NO_MODIFY_PATH = '1'
    $env:UV_PYTHON_INSTALL_BIN = '0'
    Write-Host 'Preparing private Python 3.12...'
    & $uv python install 3.12
    if ($LASTEXITCODE -ne 0) { throw 'Private Python installation failed. Check the network connection and retry.' }
    & $uv run --no-project --no-config --python 3.12 python (Join-Path $sourceDir 'src\ai_song_detection\installer.py') --source $sourceDir --uv $uv @args
    if ($LASTEXITCODE -ne 0) { throw 'Application installation failed. Read the preceding error and retry.' }
    exit 0
} catch {
    Write-Host ('Installation failed: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
