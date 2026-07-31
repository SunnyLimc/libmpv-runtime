$ErrorActionPreference = 'Stop'

$root = [IO.Path]::GetFullPath($env:LIBMPV_RUNTIME_ROOT)
$artifact = [IO.Path]::GetFullPath($env:LIBMPV_RUNTIME_ARTIFACT)
$evidence = [IO.Path]::GetFullPath($env:LIBMPV_RUNTIME_EVIDENCE)
$consumerRoot = Join-Path $root 'work/consumer-android'
$serve = Join-Path $consumerRoot 'server'
$fixture = Join-Path $consumerRoot 'app'
$generated = Join-Path $root 'build/generated-packages-android'
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
        --artifact "android=$artifact" --base-url "http://127.0.0.1:$port" --output $manifest
    libmpv-runtime packages generate --promotion $manifest --platform android --output $generated
    flutter create --platforms=android --project-name libmpv_runtime_consumer $fixture
    Add-Content -LiteralPath (Join-Path $fixture 'android/gradle.properties') -Value @(
        'kotlin.incremental=false',
        'kotlin.compiler.execution.strategy=in-process'
    )
    dart pub add -C $fixture "media_kit_libs_android_video@{path: $generated/media_kit_libs_android_video}"
    $androidManifest = Join-Path $fixture 'android/app/src/main/AndroidManifest.xml'
    $content = Get-Content -Raw -LiteralPath $androidManifest
    $content = $content.Replace('<application', '<application android:usesCleartextTraffic="true"')
    Set-Content -LiteralPath $androidManifest -Value $content -NoNewline
    Push-Location $fixture
    try {
        flutter build apk --debug -t lib/consumer_main.dart `
            --dart-define="LIBMPV_RUNTIME_TEST_URL=http://10.0.2.2:$port/input.wav"
        if ($LASTEXITCODE -ne 0) { throw 'Android MediaKit consumer build failed' }
    } finally {
        Pop-Location
    }
    adb install -r (Join-Path $fixture 'build/app/outputs/flutter-apk/app-debug.apk') | Out-Null
    adb logcat -c
    adb shell am start -n com.example.libmpv_runtime_consumer/.MainActivity | Out-Null
    $passed = $false
    for ($attempt = 0; $attempt -lt 120; $attempt++) {
        $logs = adb logcat -d -v brief
        if ($logs -match 'LIBMPV_RUNTIME_CONSUMER_ERROR') {
            throw (($logs | Select-String 'LIBMPV_RUNTIME_CONSUMER_ERROR') -join "`n")
        }
        if ($logs -match 'LIBMPV_RUNTIME_CONSUMER_OK') { $passed = $true; break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $passed) { throw 'Android MediaKit consumer did not report success' }
    libmpv-runtime evidence consumer --path $evidence --detail platform=android `
        --detail onlinePlayback=passed --detail filterAfterLoad=passed --detail jniHelper=passed
} finally {
    Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
}
