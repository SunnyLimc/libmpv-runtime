$ErrorActionPreference = 'Stop'

$root = [IO.Path]::GetFullPath($env:LIBMPV_RUNTIME_ROOT)
$stage = [IO.Path]::GetFullPath($env:LIBMPV_RUNTIME_STAGE)
$work = [IO.Path]::GetFullPath($env:LIBMPV_RUNTIME_WORK)
$evidence = [IO.Path]::GetFullPath($env:LIBMPV_RUNTIME_EVIDENCE)
$library = Join-Path $stage 'libmpv-2.dll'
if (-not (Test-Path -LiteralPath $library -PathType Leaf)) {
    throw "libmpv-2.dll is missing: $library"
}

$probeBuild = Join-Path $work 'probe-build'
New-Item -ItemType Directory -Force -Path $probeBuild | Out-Null
$probe = Join-Path $probeBuild 'mpv_dsp_probe.exe'
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
$compile = 'call "{0}" -arch=x64 && cl.exe /nologo /std:c11 /O2 /W4 /WX /D_CRT_SECURE_NO_WARNINGS "{1}" /Fe:"{2}"' -f `
    $developerCommand, $probeSource, $probe
cmd.exe /d /s /c $compile
if ($LASTEXITCODE -ne 0) { throw 'MSVC probe build failed' }

$output = Join-Path $work 'probe-output'
New-Item -ItemType Directory -Force -Path $output | Out-Null
$fixture = Join-Path $output 'input.wav'
python -m libmpv_runtime.pcm fixture --output $fixture
if ($LASTEXITCODE -ne 0) { throw 'fixture generation failed' }

$filters = [ordered]@{
    loudnorm = 'loudnorm=I=-16:TP=-1.5:LRA=11'
    dynaudnorm = 'dynaudnorm=f=250:g=9:p=0.9:m=10'
    acompressor = 'acompressor=threshold=0.25:ratio=2:attack=20:release=250'
    alimiter = 'alimiter=limit=0.95:attack=5:release=50'
    volume = 'volume=0.5'
    aresample = 'aresample=48000'
    ebur128 = 'ebur128=metadata=1'
    astats = 'astats=metadata=1:reset=1'
}
foreach ($entry in $filters.GetEnumerator()) {
    & $probe $library $fixture (Join-Path $output "$($entry.Key).wav") $entry.Value
    if ($LASTEXITCODE -ne 0) { throw "native filter probe failed: $($entry.Key)" }
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
    & $probe $library $url (Join-Path $output 'volume-http.wav') 'volume=0.5' 'after-load'
    if ($LASTEXITCODE -ne 0) { throw 'online after-load filter probe failed' }
} finally {
    Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
}

python -m libmpv_runtime.pcm verify-gain --original $fixture `
    --processed (Join-Path $output 'volume-http.wav') --expected-db -6.0206 --tolerance-db 0.35
if ($LASTEXITCODE -ne 0) { throw 'decoded online PCM gain verification failed' }
python -m libmpv_runtime.cli evidence behavior --path $evidence `
    --filters @($filters.Keys) --measured-gain-db -6.0206
if ($LASTEXITCODE -ne 0) { throw 'behavior evidence update failed' }
