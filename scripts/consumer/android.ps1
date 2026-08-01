$ErrorActionPreference = 'Stop'

$root = [IO.Path]::GetFullPath($env:LIBMPV_RUNTIME_ROOT)
$artifact = [IO.Path]::GetFullPath($env:LIBMPV_RUNTIME_ARTIFACT)
$consumerRoot = [IO.Path]::GetFullPath($env:LIBMPV_RUNTIME_WORK)
$plan = [IO.Path]::GetFullPath($env:LIBMPV_RUNTIME_PLAN)
$report = [IO.Path]::GetFullPath($env:LIBMPV_RUNTIME_REPORT)
$serve = Join-Path $consumerRoot 'server'
$fixture = Join-Path $consumerRoot 'app'
$generated = Join-Path $consumerRoot 'generated'
New-Item -ItemType Directory -Force -Path $serve | Out-Null
Copy-Item -LiteralPath (Join-Path $root 'fixtures/media_kit_consumer') -Destination $fixture -Recurse
Copy-Item -LiteralPath $artifact -Destination (Join-Path $serve ([IO.Path]::GetFileName($artifact)))
python -m libmpv_runtime.pcm fixture --output (Join-Path $serve 'input.wav')
$portFile = Join-Path $serve 'port.txt'
Remove-Item -LiteralPath $portFile -Force -ErrorAction SilentlyContinue
$port = $null
$server = Start-Process -FilePath python -WindowStyle Hidden -PassThru -ArgumentList @(
    (Join-Path $root 'scripts/probe/http_media_server.py'), '--root', $serve, '--port-file', $portFile
)
try {
    for ($attempt = 0; $attempt -lt 100 -and -not (Test-Path $portFile); $attempt++) {
        Start-Sleep -Milliseconds 100
    }
    if (-not (Test-Path -LiteralPath $portFile)) { throw 'HTTP fixture server did not start' }
    $port = Get-Content -Raw -LiteralPath $portFile
    adb reverse "tcp:$port" "tcp:$port" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Android reverse HTTP tunnel failed' }
    $manifest = Join-Path $serve 'candidate.json'
    libmpv-runtime packages candidate-manifest --id runtime-20000101.1 `
        --artifact "android=$artifact" --base-url "http://127.0.0.1:$port" --output $manifest
    libmpv-runtime packages generate --promotion $manifest --platform android --output $generated
    flutter create --platforms=android --project-name libmpv_runtime_consumer $fixture
    dart pub add -C $fixture "media_kit:$env:LIBMPV_RUNTIME_MEDIA_KIT" `
        "media_kit_video:$env:LIBMPV_RUNTIME_MEDIA_KIT_VIDEO"
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
            --dart-define="LIBMPV_RUNTIME_TEST_URL=http://127.0.0.1:$port/input.wav"
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
    if (-not $passed) {
        $tail = ($logs | Select-Object -Last 300) -join "`n"
        throw "Android MediaKit consumer did not report success.`n$tail"
    }
    libmpv-runtime consumer report --plan $plan --target android `
        --profile $env:LIBMPV_RUNTIME_PROFILE --app $fixture --artifact $artifact `
        --output $report `
        --detail platform=android `
        --detail onlinePlayback=passed --detail filterAfterLoad=passed --detail jniHelper=passed
} finally {
    if ($port) { adb reverse --remove "tcp:$port" | Out-Null }
    Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
}
