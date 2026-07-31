$ErrorActionPreference = 'Stop'

$root = [IO.Path]::GetFullPath($env:LIBMPV_RUNTIME_ROOT)
$artifact = [IO.Path]::GetFullPath($env:LIBMPV_RUNTIME_ARTIFACT)
$evidence = [IO.Path]::GetFullPath($env:LIBMPV_RUNTIME_EVIDENCE)
$consumerRoot = Join-Path $root 'work/consumer-windows'
$serve = Join-Path $consumerRoot 'server'
$generated = Join-Path $root 'build/generated-packages-windows'
$fixture = Join-Path $consumerRoot 'app'
foreach ($target in @($consumerRoot, $generated)) {
    $full = [IO.Path]::GetFullPath($target)
    if (-not $full.StartsWith($root + [IO.Path]::DirectorySeparatorChar)) {
        throw "Refusing to clean path outside repository: $full"
    }
    if (Test-Path -LiteralPath $full) { Remove-Item -LiteralPath $full -Recurse -Force }
}
New-Item -ItemType Directory -Force -Path $serve | Out-Null
Copy-Item -LiteralPath (Join-Path $root 'fixtures/media_kit_consumer') -Destination $fixture -Recurse
Copy-Item -LiteralPath $artifact -Destination (Join-Path $serve ([IO.Path]::GetFileName($artifact)))
python -m libmpv_runtime.pcm fixture --output (Join-Path $serve 'input.wav')

$portFile = Join-Path $serve 'port.txt'
$server = Start-Process -FilePath python -WindowStyle Hidden -PassThru -ArgumentList @(
    (Join-Path $root 'scripts/probe/http_media_server.py'), '--root', $serve, '--port-file', $portFile
)
try {
    for ($attempt = 0; $attempt -lt 100 -and -not (Test-Path $portFile); $attempt++) {
        Start-Sleep -Milliseconds 100
    }
    $port = Get-Content -Raw -LiteralPath $portFile
    $manifest = Join-Path $serve 'candidate.json'
    libmpv-runtime packages candidate-manifest --id runtime-20000101.1 `
        --artifact "windows-x86_64=$artifact" --base-url "http://127.0.0.1:$port" `
        --output $manifest
    libmpv-runtime packages generate --promotion $manifest --platform windows --output $generated
    flutter create --platforms=windows --project-name libmpv_runtime_consumer $fixture
    dart pub add -C $fixture "media_kit_libs_windows_video@{path: $generated/media_kit_libs_windows_video}"
    Push-Location $fixture
    try {
        flutter build windows --debug -t lib/consumer_main.dart `
            --dart-define="LIBMPV_RUNTIME_TEST_URL=http://127.0.0.1:$port/input.wav"
        if ($LASTEXITCODE -ne 0) { throw 'Windows MediaKit consumer build failed' }
        $executable = Get-ChildItem build/windows -Recurse -Filter libmpv_runtime_consumer.exe `
            | Select-Object -First 1 -ExpandProperty FullName
        & $executable
        if ($LASTEXITCODE -ne 0) { throw 'Windows MediaKit consumer runtime failed' }
    } finally {
        Pop-Location
    }
    libmpv-runtime evidence consumer --path $evidence `
        --detail platform=windows --detail onlinePlayback=passed --detail filterAfterLoad=passed
} finally {
    Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
}
