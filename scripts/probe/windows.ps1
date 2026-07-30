$ErrorActionPreference = 'Stop'

if (-not $env:LIBMPV_RUNTIME_ROOT) {
    throw 'LIBMPV_RUNTIME_ROOT is required'
}
if (-not $env:LIBMPV_RUNTIME_TARGET) {
    throw 'LIBMPV_RUNTIME_TARGET is required'
}

$root = [IO.Path]::GetFullPath($env:LIBMPV_RUNTIME_ROOT)
$stage = [IO.Path]::GetFullPath($env:LIBMPV_RUNTIME_STAGE)
$work = [IO.Path]::GetFullPath($env:LIBMPV_RUNTIME_WORK)
$evidence = [IO.Path]::GetFullPath($env:LIBMPV_RUNTIME_EVIDENCE)
$include = Join-Path $stage 'include'
$library = Join-Path $stage 'libmpv-2.dll'

if (-not (Test-Path -LiteralPath $library -PathType Leaf)) {
    throw "libmpv-2.dll is missing: $library"
}

$probeBuild = Join-Path $work 'probe-build'
if (Test-Path -LiteralPath $probeBuild) {
    Remove-Item -LiteralPath $probeBuild -Recurse -Force
}
cmake -S (Join-Path $root 'probes/native') -B $probeBuild `
    -DMPV_INCLUDE_DIR="$include"
if ($LASTEXITCODE -ne 0) {
    throw 'CMake configure failed'
}
cmake --build $probeBuild --config Release --parallel
if ($LASTEXITCODE -ne 0) {
    throw 'CMake build failed'
}
$probe = Join-Path $probeBuild 'Release/mpv_dsp_probe.exe'

$output = Join-Path $work 'probe-output'
New-Item -ItemType Directory -Force -Path $output | Out-Null
$fixture = Join-Path $output 'input.wav'
python -m libmpv_runtime.pcm fixture --output $fixture
if ($LASTEXITCODE -ne 0) {
    throw 'fixture generation failed'
}

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
    $processed = Join-Path $output "$($entry.Key).wav"
    & $probe $library $fixture $processed $entry.Value
    if ($LASTEXITCODE -ne 0) {
        throw "native filter probe failed: $($entry.Key)"
    }
}

python -m libmpv_runtime.pcm verify-gain `
    --original $fixture `
    --processed (Join-Path $output 'volume.wav') `
    --expected-db -6.0206 `
    --tolerance-db 0.35
if ($LASTEXITCODE -ne 0) {
    throw 'decoded PCM gain verification failed'
}

python -m libmpv_runtime.cli evidence record `
    --target $env:LIBMPV_RUNTIME_TARGET `
    --output $evidence `
    --filters @($filters.Keys)
if ($LASTEXITCODE -ne 0) {
    throw 'evidence recording failed'
}
