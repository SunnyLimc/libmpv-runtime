$ErrorActionPreference = 'Stop'

$root = [IO.Path]::GetFullPath($env:LIBMPV_RUNTIME_ROOT)
$stage = [IO.Path]::GetFullPath($env:LIBMPV_RUNTIME_STAGE)
$work = [IO.Path]::GetFullPath($env:LIBMPV_RUNTIME_WORK)
$evidence = [IO.Path]::GetFullPath($env:LIBMPV_RUNTIME_EVIDENCE)
$sdk = if ($env:ANDROID_SDK_ROOT) { $env:ANDROID_SDK_ROOT } elseif ($env:ANDROID_HOME) {
    $env:ANDROID_HOME
} else {
    Join-Path $env:LOCALAPPDATA 'Android\Sdk'
}
$ndk = if ($env:ANDROID_NDK_HOME) { $env:ANDROID_NDK_HOME } else {
    Get-ChildItem (Join-Path $sdk 'ndk') -Directory | Sort-Object Name | Select-Object -Last 1 -ExpandProperty FullName
}
$clang = Get-ChildItem (Join-Path $ndk 'toolchains\llvm\prebuilt') -Recurse `
    -Filter x86_64-linux-android23-clang.cmd | Select-Object -First 1 -ExpandProperty FullName
if (-not $clang) { throw 'Android NDK x86_64 API 23 clang is missing' }
New-Item -ItemType Directory -Force -Path $work | Out-Null
$probe = Join-Path $work 'mpv_dsp_probe.android'
& $clang -std=c11 -O2 -Wall -Wextra -Werror `
    (Join-Path $root 'probes/native/mpv_dsp_probe.c') -ldl -o $probe
if ($LASTEXITCODE -ne 0) { throw 'Android probe compilation failed' }

$output = Join-Path $work 'output'
New-Item -ItemType Directory -Force -Path $output | Out-Null
$fixture = Join-Path $output 'input.wav'
python -m libmpv_runtime.pcm fixture --output $fixture
$remote = '/data/local/tmp/libmpv-runtime-local'
adb shell "rm -rf '$remote' && mkdir -p '$remote'"
adb push $probe "$remote/mpv_dsp_probe"
adb push (Join-Path $stage 'jniLibs\x86_64\.') "$remote/"
adb push $fixture "$remote/input.wav"
adb shell "chmod 755 '$remote/mpv_dsp_probe'"

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
    adb shell "cd '$remote' && LD_LIBRARY_PATH='$remote' ./mpv_dsp_probe '$remote/libmpv.so' '$remote/input.wav' '$remote/$($entry.Key).wav' '$($entry.Value)'"
    if ($LASTEXITCODE -ne 0) { throw "Android filter failed: $($entry.Key)" }
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
    adb shell "cd '$remote' && LD_LIBRARY_PATH='$remote' ./mpv_dsp_probe '$remote/libmpv.so' 'http://10.0.2.2:$port/input.wav' '$remote/volume-http.wav' 'volume=0.5' after-load"
    if ($LASTEXITCODE -ne 0) { throw 'Android online after-load filter failed' }
    adb pull "$remote/volume-http.wav" (Join-Path $output 'volume-http.wav')
} finally {
    Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
    adb shell "rm -rf '$remote'" | Out-Null
}
python -m libmpv_runtime.pcm verify-gain --original $fixture `
    --processed (Join-Path $output 'volume-http.wav') --expected-db -6.0206 --tolerance-db 0.35
if ($LASTEXITCODE -ne 0) { throw 'Android online decoded PCM gain failed' }
python -m libmpv_runtime.cli evidence behavior --path $evidence `
    --filters @($filters.Keys) --measured-gain-db -6.0206
