$ErrorActionPreference = 'Stop'

$root = [IO.Path]::GetFullPath($env:LIBMPV_RUNTIME_ROOT)
$stage = [IO.Path]::GetFullPath($env:LIBMPV_RUNTIME_STAGE)
$output = [IO.Path]::GetFullPath($env:LIBMPV_RUNTIME_OUTPUT)
$probeBin = [IO.Path]::GetFullPath($env:LIBMPV_RUNTIME_BIN)
$probePlan = [IO.Path]::GetFullPath($env:LIBMPV_RUNTIME_PROBE_PLAN)
$httpFilter = $env:LIBMPV_RUNTIME_HTTP_FILTER
$library = Join-Path $stage 'libmpv-2.dll'
if (-not (Test-Path -LiteralPath $library -PathType Leaf)) {
    throw "libmpv-2.dll is missing: $library"
}

$probe = Join-Path $probeBin 'mpv_dsp_probe.exe'
$probeObject = Join-Path $probeBin 'mpv_dsp_probe.obj'
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
$installation = if (Test-Path -LiteralPath $vswhere) {
    & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -property installationPath
} else {
    Get-ChildItem (Join-Path $env:ProgramFiles 'Microsoft Visual Studio') -Directory -Recurse `
        -Filter Common7 | Select-Object -First 1 -ExpandProperty Parent | Select-Object -ExpandProperty Parent
}
$developerCommand = Join-Path $installation 'Common7/Tools/VsDevCmd.bat'
if (-not (Test-Path -LiteralPath $developerCommand)) { throw 'Visual Studio C++ tools are missing' }
$probeSource = Join-Path $root 'probes/native/mpv_dsp_probe.c'
$compile = 'call "{0}" -arch=x64 && cl.exe /nologo /std:c11 /O2 /W4 /WX /D_CRT_SECURE_NO_WARNINGS "{1}" /Fe:"{2}" /Fo:"{3}"' -f `
    $developerCommand, $probeSource, $probe, $probeObject
cmd.exe /d /s /c $compile
if ($LASTEXITCODE -ne 0) { throw 'MSVC probe build failed' }

$fixture = Join-Path $output 'input.wav'
python -m libmpv_runtime.pcm fixture --output $fixture
if ($LASTEXITCODE -ne 0) { throw 'fixture generation failed' }

$filters = Import-Csv -Delimiter "`t" -LiteralPath $probePlan
foreach ($entry in $filters) {
    & $probe $library $fixture (Join-Path $output "$($entry.name).wav") $entry.expression
    if ($LASTEXITCODE -ne 0) { throw "native filter probe failed: $($entry.name)" }
}

$portFile = Join-Path $output 'http-port.txt'
Remove-Item -LiteralPath $portFile -Force -ErrorAction SilentlyContinue
$server = Start-Process -FilePath python -WindowStyle Hidden -PassThru `
    -ArgumentList @(
        (Join-Path $root 'scripts/probe/http_media_server.py'),
        '--root', $output, '--port-file', $portFile
    )
try {
    for ($attempt = 0; $attempt -lt 100 -and -not (Test-Path -LiteralPath $portFile); $attempt++) {
        Start-Sleep -Milliseconds 100
    }
    if (-not (Test-Path -LiteralPath $portFile)) { throw 'HTTP fixture server did not start' }
    $port = Get-Content -Raw -LiteralPath $portFile
    $url = "http://127.0.0.1:$port/input.wav"
    $expression = ($filters | Where-Object name -eq $httpFilter).expression
    if (-not $expression) { throw "HTTP filter is missing from probe plan: $httpFilter" }
    & $probe $library $url (Join-Path $output 'volume-http.wav') $expression 'after-load'
    if ($LASTEXITCODE -ne 0) { throw 'online after-load filter probe failed' }
} finally {
    Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
}
