$ErrorActionPreference = 'Stop'

$root = [IO.Path]::GetFullPath($env:LIBMPV_RUNTIME_ROOT)
$stage = [IO.Path]::GetFullPath($env:LIBMPV_RUNTIME_STAGE)
$output = [IO.Path]::GetFullPath($env:LIBMPV_RUNTIME_OUTPUT)
$probeBin = [IO.Path]::GetFullPath($env:LIBMPV_RUNTIME_BIN)
$probePlan = [IO.Path]::GetFullPath($env:LIBMPV_RUNTIME_PROBE_PLAN)
$httpFilter = $env:LIBMPV_RUNTIME_HTTP_FILTER
$androidMinSdk = $env:LIBMPV_RUNTIME_ANDROID_MIN_SDK
$sdk = if ($env:ANDROID_SDK_ROOT) { $env:ANDROID_SDK_ROOT } elseif ($env:ANDROID_HOME) {
    $env:ANDROID_HOME
} else {
    Join-Path $env:LOCALAPPDATA 'Android\Sdk'
}
$ndk = if ($env:ANDROID_NDK_HOME) { $env:ANDROID_NDK_HOME } else {
    Get-ChildItem (Join-Path $sdk 'ndk') -Directory | Sort-Object Name | Select-Object -Last 1 -ExpandProperty FullName
}
$clang = Get-ChildItem (Join-Path $ndk 'toolchains\llvm\prebuilt') -Recurse `
    -Filter "x86_64-linux-android$androidMinSdk-clang.cmd" `
    | Select-Object -First 1 -ExpandProperty FullName
if (-not $clang) { throw "Android NDK x86_64 API $androidMinSdk clang is missing" }
$probe = Join-Path $probeBin 'mpv_dsp_probe.android'
& $clang -std=c11 -O2 -Wall -Wextra -Werror `
    (Join-Path $root 'probes/native/mpv_dsp_probe.c') -ldl -o $probe
if ($LASTEXITCODE -ne 0) { throw 'Android probe compilation failed' }

$fixture = Join-Path $output 'input.wav'
python -m libmpv_runtime.pcm fixture --output $fixture
$remote = '/data/local/tmp/libmpv-runtime-local'
adb shell "rm -rf '$remote' && mkdir -p '$remote'"
adb push $probe "$remote/mpv_dsp_probe"
adb push (Join-Path $stage 'jniLibs\x86_64\.') "$remote/"
adb push $fixture "$remote/input.wav"
adb shell "chmod 755 '$remote/mpv_dsp_probe'"

$filters = Import-Csv -Delimiter "`t" -LiteralPath $probePlan
foreach ($entry in $filters) {
    adb shell "cd '$remote' && LD_LIBRARY_PATH='$remote' ./mpv_dsp_probe '$remote/libmpv.so' '$remote/input.wav' '$remote/$($entry.name).wav' '$($entry.expression)'"
    if ($LASTEXITCODE -ne 0) { throw "Android filter failed: $($entry.name)" }
    adb pull "$remote/$($entry.name).wav" (Join-Path $output "$($entry.name).wav") | Out-Null
}

$portFile = Join-Path $output 'port.txt'
$server = Start-Process -FilePath python -WindowStyle Hidden -PassThru -ArgumentList @(
    (Join-Path $root 'scripts/probe/http_media_server.py'), '--root', $output, '--port-file', $portFile
)
try {
    for ($attempt = 0; $attempt -lt 100 -and -not (Test-Path $portFile); $attempt++) {
        Start-Sleep -Milliseconds 100
    }
    $port = Get-Content -Raw -LiteralPath $portFile
    $expression = ($filters | Where-Object name -eq $httpFilter).expression
    if (-not $expression) { throw "HTTP filter is missing from probe plan: $httpFilter" }
    adb shell "cd '$remote' && LD_LIBRARY_PATH='$remote' ./mpv_dsp_probe '$remote/libmpv.so' 'http://10.0.2.2:$port/input.wav' '$remote/volume-http.wav' '$expression' after-load"
    if ($LASTEXITCODE -ne 0) { throw 'Android online after-load filter failed' }
    adb pull "$remote/volume-http.wav" (Join-Path $output 'volume-http.wav')
} finally {
    Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
    adb shell "rm -rf '$remote'" | Out-Null
}
